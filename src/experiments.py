"""Reproducible scheduling sensitivity runs and publication-style figures."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.simulation import SimulationConfig, run_simulation

RISK_WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)


def run_sensitivity(workload: pd.DataFrame, carbon: pd.DataFrame, forecast_csv: str | Path, output_dir: str | Path, base: SimulationConfig = SimulationConfig()) -> dict[str, pd.DataFrame]:
    """Run risk, CPU, delay, and forecast-horizon sensitivity scenarios."""
    output_dir = Path(output_dir) / "experiments"
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = {
        "risk_weight": [("risk_weight", x) for x in RISK_WEIGHTS],
        "cpu_capacity": [("cpu_capacity", x) for x in (4.0, 8.0, 12.0)],
        "scheduling_delay": [("max_delay_seconds", x) for x in (0.0, 1800.0, 3600.0)],
        "forecast_horizon": [("forecast_horizon", x) for x in (1, 2, 3, 4)],
        "power_per_core_watts": [("power_per_core_watts", x) for x in (5.0, 10.0, 20.0, 30.0)],
    }
    results = {}
    for name, values in cases.items():
        rows = []
        for field, value in values:
            config = SimulationConfig(**{**base.__dict__, field: value})
            _, metrics, _ = run_simulation(workload, carbon, forecast_csv, config)
            trace = metrics.loc[metrics.strategy == "trace"].iloc[0].to_dict()
            trace["parameter"] = value
            rows.append(trace)
        frame = pd.DataFrame(rows)
        frame.to_csv(output_dir / f"{name}_sensitivity.csv", index=False)
        results[name] = frame
    pd.DataFrame([{"sample_tasks": len(workload), "risk_values": ",".join(map(str, RISK_WEIGHTS)), "base_cpu_capacity": base.cpu_capacity, "base_delay_seconds": base.max_delay_seconds, "base_horizon_hours": base.forecast_horizon}]).to_csv(output_dir / "experiment_summary.csv", index=False)
    return results


def generate_figures(ledger: pd.DataFrame, metrics: pd.DataFrame, carbon: pd.DataFrame, forecasts: pd.DataFrame, output_dir: str | Path, sensitivity: dict[str, pd.DataFrame] | None = None) -> None:
    """Save labelled PNG figures from executed simulation outputs."""
    out = Path(output_dir) / "figures"
    out.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    def save_bar(column: str, ylabel: str, file: str, percentage: bool = False) -> None:
        fig, ax = plt.subplots(figsize=(7.2, 4.4), layout="constrained")
        ax.bar(metrics.strategy, metrics[column], color=["#64748b", "#0f766e", "#2563eb"])
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Scheduling strategy")
        ax.set_title(ylabel + " by strategy")
        ax.tick_params(axis="x", rotation=15)
        if percentage:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.1f}%"))
        fig.savefig(out / file, dpi=300)
        plt.close(fig)

    save_bar("common_population_emissions_g_co2e", "Observed emissions on common executed tasks (g CO2e)", "carbon_emissions_comparison.png")
    baseline = float(metrics.loc[metrics.strategy == "fifo", "common_population_emissions_g_co2e"].iloc[0])
    comparison = metrics.copy()
    comparison["carbon_reduction_percentage"] = (baseline - comparison.common_population_emissions_g_co2e) / baseline * 100 if baseline else 0.0
    fig, ax = plt.subplots(figsize=(7.2, 4.4), layout="constrained")
    ax.bar(comparison.strategy, comparison.carbon_reduction_percentage, color=["#64748b", "#0f766e", "#2563eb"])
    ax.set_ylabel("Reduction relative to FIFO (%)")
    ax.set_xlabel("Scheduling strategy")
    ax.set_title("Observed-carbon reduction")
    fig.savefig(out / "carbon_reduction_comparison.png", dpi=300)
    plt.close(fig)
    delays = ledger.loc[ledger.task_status == "executed"].groupby("policy").delay_seconds.mean()
    fig, ax = plt.subplots(figsize=(7.2, 4.4), layout="constrained")
    delays.reindex(["fifo", "earliest_feasible", "trace"]).plot.bar(ax=ax, color=["#64748b", "#0f766e", "#2563eb"])
    ax.set_ylabel("Average task delay (seconds)")
    ax.set_xlabel("Scheduling strategy")
    ax.set_title("Average delay of executed tasks")
    fig.savefig(out / "task_delay_comparison.png", dpi=300)
    plt.close(fig)
    if sensitivity and "risk_weight" in sensitivity:
        frame = sensitivity["risk_weight"]
        fig, ax = plt.subplots(figsize=(7.2, 4.4), layout="constrained")
        ax.plot(frame.parameter, frame.common_population_emissions_g_co2e, marker="o", color="#2563eb")
        ax.set(xlabel="Risk weight", ylabel="Observed emissions (g CO2e)", title="Risk-weight sensitivity")
        fig.savefig(out / "risk_weight_sensitivity.png", dpi=300)
        plt.close(fig)
    if not ledger.empty:
        executed = ledger[(ledger.policy == "trace") & (ledger.task_status == "executed") & (ledger.duration_seconds > 0)]
        util = []
        for hour in range(len(carbon)):
            a, b = hour * 3600, (hour + 1) * 3600
            core_seconds = 0.0
            for row in executed.itertuples():
                core_seconds += max(0.0, min(row.scheduled_end_time, b) - max(row.scheduled_start_time, a)) * row.cpu_cores
            util.append(core_seconds / 3600)
        fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
        ax.plot(range(len(util)), util, color="#0f766e")
        ax.set(xlabel="Simulation hour", ylabel="Average allocated cores", title="TRACE CPU utilization over time")
        fig.savefig(out / "cpu_utilization_over_time.png", dpi=300)
        plt.close(fig)
    if not forecasts.empty:
        actual = carbon.copy().reset_index(drop=True)
        target = forecasts.drop_duplicates("simulation_hour").sort_values("simulation_hour")
        target = target.loc[target.simulation_hour < len(actual)]
        fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
        hours = target.simulation_hour.astype(int)
        ax.plot(hours, actual.loc[hours, "carbon_intensity"].to_numpy(), label="Observed", color="#111827")
        ax.plot(hours, target.predicted_carbon_intensity, label="Seasonal-naive replay forecast", color="#2563eb")
        ax.fill_between(hours, target.lower_bound, target.upper_bound, color="#2563eb", alpha=0.15, label="90% interval")
        ax.set(xlabel="Simulation hour", ylabel="Carbon intensity (g CO2e/kWh)", title="Historical forecast replay versus observed carbon")
        ax.legend()
        fig.savefig(out / "forecast_vs_actual_carbon.png", dpi=300)
        plt.close(fig)
