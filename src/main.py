"""Command-line entry point for the TRACE integrated simulation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data.prepare_carbon import load_carbon
from src.experiments import generate_figures, run_sensitivity
from src.forecasting.rolling_forecast import generate_rolling_forecasts
from src.simulation import (
    SimulationConfig,
    load_forecast_window_sample,
    normalize_workload,
    run_simulation,
    write_simulation_outputs,
)
from src.scheduler.event_engine import EventSchedulerConfig, run_event_simulation

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKLOAD = ROOT / "data/processed/workload/workload_cleaned.csv"
DEFAULT_CARBON = ROOT / "data/raw/carbon/india_west_carbon_intensity.csv"
DEFAULT_FORECASTS = ROOT / "results/forecasting/rolling_seasonal_naive_forecasts.csv"
DEFAULT_OUTPUT = ROOT / "results"


def _input_data(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    carbon = load_carbon(args.carbon, zone=args.zone)
    forecast_file = args.forecasts
    if not forecast_file.is_file():
        forecast_file.parent.mkdir(parents=True, exist_ok=True)
        generated = generate_rolling_forecasts(carbon)
        generated.to_csv(forecast_file, index=False)
    if args.mode == "full":
        chunks = []
        for chunk in pd.read_csv(args.workload, chunksize=args.chunk_size):
            chunks.append(chunk)
            if args.max_tasks and sum(map(len, chunks)) >= args.max_tasks:
                break
        workload = pd.concat(chunks, ignore_index=True)
        if args.max_tasks:
            workload = workload.iloc[: args.max_tasks]
        workload = normalize_workload(workload, args.power_per_core_watts)
    else:
        workload, sample_info = load_forecast_window_sample(
            args.workload, forecast_file, carbon, max_tasks=args.max_tasks or 500,
            chunk_size=args.chunk_size,
        )
        workload = normalize_workload(workload, args.power_per_core_watts)
        print("Sample selection:", sample_info)
    return workload, carbon, forecast_file


def _write_report(metrics: pd.DataFrame, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fifo = metrics.loc[metrics.strategy == "fifo"].iloc[0]
    trace = metrics.loc[metrics.strategy == "trace"].iloc[0]
    text = f"""# TRACE simulation results

Generated from the persisted evaluation CSVs using observed carbon intensity.

- Tasks in common executed population: {int(trace.common_population_tasks)}
- FIFO emissions on that population: {fifo.common_population_emissions_g_co2e:.6f} g CO2e
- TRACE emissions on that population: {trace.common_population_emissions_g_co2e:.6f} g CO2e
- TRACE savings versus FIFO: {trace.carbon_savings_vs_fifo_g:.6f} g CO2e ({trace.carbon_reduction_vs_fifo_percentage:.4f}%)
- TRACE executed / deferred / infeasible: {int(trace.executed_tasks)} / {int(trace.deferred_tasks)} / {int(trace.infeasible_tasks)}
- TRACE forecast-eligible tasks: {int(trace.forecast_eligible_tasks)}
- TRACE tasks outside forecast coverage: {int(trace.forecast_outside_coverage_tasks)}
- TRACE rescheduled tasks actually executed: {int(trace.rescheduled_tasks)}

The common-population emissions comparison includes only task IDs executed by all three strategies. Per-strategy completion counts include every task in the chosen workload sample. These are simulation outputs under configured assumptions, not measured data-center energy.
"""
    (output / "simulation_report.md").write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the TRACE end-to-end scheduling simulation")
    parser.add_argument("--mode", choices=("small", "full", "sensitivity", "report"), default="small")
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--ordered-workload", type=Path, default=ROOT / "results/validation/chronological_tasks.csv", help="Phase 2 external-sort output used by scalable full mode")
    parser.add_argument("--carbon", type=Path, default=DEFAULT_CARBON)
    parser.add_argument("--forecasts", type=Path, default=DEFAULT_FORECASTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zone", default="IN-WE")
    parser.add_argument("--max-tasks", type=int, default=None, help="Small mode defaults to 500 tasks; full mode can be bounded with this option")
    parser.add_argument("--chunk-size", type=int, default=100_000)
    parser.add_argument("--cpu-capacity", type=float, default=8.0)
    parser.add_argument("--max-delay-seconds", type=float, default=3600.0)
    parser.add_argument("--forecast-horizon", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--risk-weight", type=float, default=0.5)
    parser.add_argument("--power-per-core-watts", type=float, default=10.0)
    parser.add_argument("--checkpoint-interval", type=int, default=10_000)
    parser.add_argument("--resume", action="store_true", help="Resume a compatible event-based full-mode checkpoint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "report":
        path = args.output / "evaluation" / "strategy_comparison.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Run a simulation first; missing {path}")
        metrics = pd.read_csv(path)
        _write_report(metrics, args.output / "evaluation")
        return 0
    if args.mode == "full":
        if not args.ordered_workload.is_file():
            raise FileNotFoundError(
                f"Full mode requires Phase 2 chronological data: {args.ordered_workload}"
            )
        carbon = load_carbon(args.carbon, zone=args.zone)
        forecast_file = args.forecasts
        if not forecast_file.is_file():
            forecast_file.parent.mkdir(parents=True, exist_ok=True)
            generate_rolling_forecasts(carbon).to_csv(forecast_file, index=False)
        event_config = EventSchedulerConfig(
            cpu_capacity=args.cpu_capacity,
            max_delay_seconds=args.max_delay_seconds,
            forecast_horizon=args.forecast_horizon,
            risk_weight=args.risk_weight,
            power_per_core_watts=args.power_per_core_watts,
        )
        report = run_event_simulation(
            args.ordered_workload,
            carbon,
            forecast_file,
            args.output / "simulation" / "event_based",
            event_config,
            max_tasks=args.max_tasks,
            checkpoint_interval=args.checkpoint_interval,
            resume=args.resume,
        )
        print(pd.Series(report).to_string())
        return 0
    workload, carbon, forecast_file = _input_data(args)
    config = SimulationConfig(args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon, args.risk_weight, args.power_per_core_watts)
    if args.mode == "sensitivity":
        sensitivity = run_sensitivity(workload, carbon, forecast_file, args.output, config)
        ledger, metrics, forecasts = run_simulation(workload, carbon, forecast_file, config)
    else:
        sensitivity = None
        ledger, metrics, forecasts = run_simulation(workload, carbon, forecast_file, config)
    write_simulation_outputs(ledger, metrics, args.output)
    generate_figures(ledger, metrics, carbon, forecasts, args.output, sensitivity)
    _write_report(metrics, args.output / "evaluation")
    print(metrics.to_string(index=False))
    print(f"Outputs written under {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
