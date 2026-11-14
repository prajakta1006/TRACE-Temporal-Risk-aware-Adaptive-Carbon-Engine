"""Reproducible staged real-workload runs and streaming ledger evaluation."""

from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from itertools import zip_longest
import threading
import traceback

import pandas as pd

from src.data.task_identity import task_id_for_source_row
from src.scheduler.event_engine import (
    STRATEGIES,
    EventSchedulerConfig,
    _atomic_json,
    _carbon_frame,
    _sha256_file,
    run_event_simulation,
)


def _ledger_summary(
    path: Path,
    capacity: float,
    strategy: str | None = None,
    max_delay_seconds: float = 3600.0,
) -> dict:
    status_counts: dict[str, int] = {}
    forecast_counts: dict[str, int] = {}
    forecast_reasons: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    delay_bins = {"zero": 0, "0-60s": 0, "60-300s": 0, "300-900s": 0,
                  "900-1800s": 0, "1800-3600s": 0, ">3600s": 0}
    scheduled = 0
    scheduled_energy = 0.0
    observed_emissions = 0.0
    emissions_covered = 0
    emissions_missing = 0
    allocated_core_seconds = 0.0
    delay_sum = 0.0
    delay_max = 0.0
    scheduled_start_min = math.inf
    scheduled_end_max = -math.inf
    fallback_decisions = 0
    capacity_events: list[tuple[float, int, float]] = []
    allocated_now = 0.0
    maximum_allocated = 0.0
    capacity_violations = 0
    task_constraint_violations = 0
    previous_release = -math.inf

    def advance_capacity(until: float) -> None:
        nonlocal allocated_now, maximum_allocated, capacity_violations
        import heapq
        while capacity_events and capacity_events[0][0] <= until + 1e-9:
            when, event_kind, cores = heapq.heappop(capacity_events)
            if event_kind == 0:
                allocated_now -= cores
                if allocated_now < 1e-9:
                    allocated_now = 0.0
            else:
                allocated_now += cores
                maximum_allocated = max(maximum_allocated, allocated_now)
                if allocated_now > capacity + 1e-8:
                    capacity_violations += 1

    with path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            release = float(row["start_time"])
            if row["task_status"] not in {"executed", "deferred", "infeasible", "duplicate_prevented"}:
                raise ValueError(f"Unknown task state in ledger: {row['task_status']}")
            if row["task_id"] != task_id_for_source_row(int(row["source_row"])):
                raise ValueError(f"Stable task identity mismatch in ledger: {path}")
            if release < previous_release - 1e-9:
                raise ValueError(f"Ledger release times are not chronological: {path}")
            previous_release = release
            advance_capacity(release)
            status = row["task_status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            forecast_status = row["forecast_status"]
            forecast_counts[forecast_status] = forecast_counts.get(forecast_status, 0) + 1
            reason = row["forecast_reason"]
            forecast_reasons[reason] = forecast_reasons.get(reason, 0) + 1
            decision = row["decision"]
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
            if decision.startswith("fallback_") or (
                strategy == "trace" and
                forecast_status == "ineligible" and decision == "no_capacity_slot_within_max_delay"
            ):
                fallback_decisions += 1
            if status != "executed":
                continue
            scheduled += 1
            energy = float(row["energy_kwh"] or 0.0)
            scheduled_energy += energy
            cores = float(row["cpu_cores"])
            duration = float(row["duration_seconds"])
            allocated_core_seconds += cores * duration
            start = float(row["scheduled_start_time"])
            end = float(row["scheduled_end_time"])
            if (
                start < release - 1e-9
                or start - release > max_delay_seconds + 1e-9
                or abs((end - start) - duration) > 1e-7
                or cores > capacity + 1e-9
            ):
                task_constraint_violations += 1
            if duration > 0 and cores > 0:
                import heapq
                heapq.heappush(capacity_events, (start, 1, cores))
                heapq.heappush(capacity_events, (end, 0, cores))
            scheduled_start_min = min(scheduled_start_min, start)
            scheduled_end_max = max(scheduled_end_max, end)
            delay = max(0.0, float(row["delay_seconds"] or 0.0))
            delay_sum += delay
            delay_max = max(delay_max, delay)
            if delay <= 1e-9:
                delay_bins["zero"] += 1
            elif delay <= 60:
                delay_bins["0-60s"] += 1
            elif delay <= 300:
                delay_bins["60-300s"] += 1
            elif delay <= 900:
                delay_bins["300-900s"] += 1
            elif delay <= 1800:
                delay_bins["900-1800s"] += 1
            elif delay <= 3600:
                delay_bins["1800-3600s"] += 1
            else:
                delay_bins[">3600s"] += 1
            if row["emissions_status"] == "covered":
                emissions_covered += 1
                observed_emissions += float(row["estimated_emissions_g_co2e"] or 0.0)
            else:
                emissions_missing += 1
    advance_capacity(math.inf)
    if abs(allocated_now) > 1e-7:
        raise ValueError(f"Ledger leaves nonzero allocated CPU after all completion events: {path}")
    deferred = status_counts.get("deferred", 0)
    infeasible = status_counts.get("infeasible", 0)
    duplicate = status_counts.get("duplicate_prevented", 0)
    total = sum(status_counts.values())
    span = max(0.0, scheduled_end_max - scheduled_start_min) if scheduled else 0.0
    utilization = allocated_core_seconds / (capacity * span) if span > 0 else 0.0
    if utilization > 1.0 + 1e-8 and capacity_violations == 0:
        raise ValueError(f"Ledger average CPU utilization exceeds capacity despite zero event violations: {path}")
    return {
        "tasks_processed": total,
        "task_status_counts": status_counts,
        "forecast_status_counts": forecast_counts,
        "forecast_eligible_tasks": forecast_counts.get("eligible", 0),
        "forecast_ineligible_tasks": forecast_counts.get("ineligible", 0),
        "forecast_reason_counts": forecast_reasons,
        "decision_counts": decision_counts,
        "forecast_fallback_decisions": fallback_decisions,
        "scheduled_tasks": scheduled,
        "completed_tasks": scheduled,
        "pending_tasks_at_end": 0,
        "rejected_tasks": deferred + infeasible,
        "deferred_tasks": deferred,
        "infeasible_tasks": infeasible,
        "duplicate_prevented_tasks": duplicate,
        "completion_rate": scheduled / max(1, total),
        "scheduled_energy_kwh": scheduled_energy,
        "completed_energy_kwh": scheduled_energy,
        "scheduled_observed_emissions_g_co2e": observed_emissions,
        "completed_observed_emissions_g_co2e": observed_emissions,
        "emissions_covered_tasks": emissions_covered,
        "emissions_coverage_missing_tasks": emissions_missing,
        "delay_seconds_histogram": delay_bins,
        "mean_delay_seconds_scheduled_tasks": delay_sum / max(1, scheduled),
        "maximum_delay_seconds": delay_max,
        "allocated_core_seconds": allocated_core_seconds,
        "scheduled_time_span_seconds": span,
        "average_capacity_utilization_fraction": utilization,
        "capacity_violations": capacity_violations,
        "task_constraint_violations": task_constraint_violations,
        "independent_peak_allocated_cores": maximum_allocated,
    }


def _flatten_stage_row(record: dict) -> dict:
    flat = {key: value for key, value in record.items() if not isinstance(value, dict)}
    for field, prefix in (
        ("task_status_counts", "status"),
        ("forecast_status_counts", "forecast"),
        ("forecast_reason_counts", "forecast_reason"),
        ("decision_counts", "decision"),
        ("delay_seconds_histogram", "delay_bin"),
    ):
        flat.update({f"{prefix}_{key}": value for key, value in record.get(field, {}).items()})
    return flat


def _compare_ledgers(output_dirs: dict[str, Path]) -> dict:
    """Compare ledgers in lockstep without loading a task population in RAM."""
    common_executed = 0
    common_emissions_tasks = 0
    emissions = {strategy: 0.0 for strategy in output_dirs}
    with ExitStack() as stack:
        readers = [csv.DictReader(stack.enter_context(
            (directory / f"{strategy}_schedule.csv").open("r", encoding="utf-8", newline="")
        )) for strategy, directory in output_dirs.items()]
        for rows in zip_longest(*readers):
            if any(row is None for row in rows):
                if not all(row is None for row in rows):
                    raise ValueError("Strategy output row counts differ")
                break
            if any(row["task_id"] != rows[0]["task_id"] for row in rows[1:]):
                raise ValueError("Strategies did not process the same task identity sequence")
            if all(row["task_status"] == "executed" for row in rows):
                common_executed += 1
                if all(row["emissions_status"] == "covered" for row in rows):
                    common_emissions_tasks += 1
                    for strategy, row in zip(output_dirs, rows):
                        emissions[strategy] += float(row["estimated_emissions_g_co2e"] or 0.0)
    return {
        "common_executed_tasks": common_executed,
        "common_observed_emissions_tasks": common_emissions_tasks,
        "common_population_observed_emissions_g_co2e": emissions,
    }


def _run_stage_suite(
    workload: Path,
    carbon_path: Path,
    forecast_path: Path,
    output: Path,
    config: EventSchedulerConfig,
    *,
    sizes: tuple[int, ...],
    checkpoint_interval: int,
    resume_test_size: int | None,
) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Phase 6 output directory is not clean: {output}")
    output.mkdir(parents=True, exist_ok=True)
    carbon = _carbon_frame(carbon_path, "IN-WE")
    run_config = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sampling_method": "first N tasks from the validated chronological Phase 2 representation",
        "sampling_limitation": "Prefix stages are engineering and recovery checks, not population-representative evaluation samples.",
        "input_path": str(workload.resolve()),
        "input_sha256": _sha256_file(workload),
        "carbon_path": str(carbon_path.resolve()),
        "carbon_sha256": _sha256_file(carbon_path),
        "forecast_path": str(forecast_path.resolve()),
        "forecast_sha256": _sha256_file(forecast_path),
        "configuration": config.__dict__,
        "strategies": list(STRATEGIES),
        "stage_sizes": list(sizes),
        "checkpoint_interval": checkpoint_interval,
        "resume_test_size": resume_test_size,
    }
    _atomic_json(output / "run_configuration.json", run_config)
    log_path = output / "run_log.jsonl"
    log_path.write_text("", encoding="utf-8")
    stage_records = []
    stage_summaries: dict[str, dict] = {}
    for size in sizes:
        stage_name = f"prefix_{size}"
        strategy_dirs = {}
        strategy_summaries = {}
        for strategy in STRATEGIES:
            outdir = output / stage_name / strategy
            outdir.mkdir(parents=True, exist_ok=False)
            should_interrupt = size == resume_test_size and strategy == "trace"
            start = time.perf_counter()
            interrupt_result = None
            if should_interrupt:
                interrupt_after = min(checkpoint_interval * 50 + 1, size // 2 + 1)
                interrupt_result = run_event_simulation(
                    workload, carbon, forecast_path, outdir, config,
                    max_tasks=size, strategies=(strategy,),
                    checkpoint_interval=checkpoint_interval,
                    interrupt_after_tasks=interrupt_after,
                    interrupt_point="after_decisions",
                )
                if interrupt_result["completed"] or interrupt_result["tasks_checkpointed"] == 0:
                    raise RuntimeError("Staged recovery interruption did not stop after a durable checkpoint")
                resume_started = time.perf_counter()
                report = run_event_simulation(
                    workload, carbon, forecast_path, outdir, config,
                    max_tasks=size, strategies=(strategy,),
                    checkpoint_interval=checkpoint_interval, resume=True,
                )
                resume_wall = time.perf_counter() - resume_started
            else:
                report = run_event_simulation(
                    workload, carbon, forecast_path, outdir, config,
                    max_tasks=size, strategies=(strategy,),
                    checkpoint_interval=checkpoint_interval,
                )
                resume_wall = 0.0
            wall_seconds = time.perf_counter() - start
            if not report["completed"] or report["tasks_processed"] != size:
                raise RuntimeError(f"Stage {size} {strategy} did not complete the requested population")
            ledger = _ledger_summary(
                outdir / f"{strategy}_schedule.csv", config.cpu_capacity, strategy,
                config.max_delay_seconds,
            )
            db_path = outdir / "checkpoint.sqlite3"
            sqlite_artifacts_bytes = sum(
                p.stat().st_size for p in outdir.glob("checkpoint.sqlite3*") if p.is_file()
            )
            output_bytes = sum(p.stat().st_size for p in outdir.rglob("*") if p.is_file())
            row = {
                "stage_size": size, "sampling_method": "chronological_prefix",
                "strategy": strategy, "completed": report["completed"],
                "tasks_processed": report["tasks_processed"],
                "runtime_seconds": report["runtime_seconds"],
                "wall_seconds": wall_seconds,
                "tasks_per_second": report["tasks_processed"] / max(report["runtime_seconds"], 1e-9),
                "peak_rss_bytes": report["peak_rss_bytes_process"],
                "checkpoint_seconds": report.get("checkpoint_seconds", 0.0),
                "recovery_wall_seconds": resume_wall,
                "checkpoint_bytes": db_path.stat().st_size,
                "sqlite_artifacts_bytes": sqlite_artifacts_bytes,
                "schedule_output_bytes": (outdir / f"{strategy}_schedule.csv").stat().st_size,
                "forecast_scoring_seconds": report["strategy_metrics"][strategy]["forecast_scoring_seconds"],
                "rescheduled_tasks": report["strategy_metrics"][strategy]["rescheduled_tasks"],
                "output_bytes_total": output_bytes,
                "interrupted": interrupt_result is not None,
                "interruption_checkpointed_tasks": interrupt_result["tasks_checkpointed"] if interrupt_result else None,
                "interruption_last_task_id": interrupt_result["last_task_id"] if interrupt_result else None,
                "capacity_violations": 0,
                **ledger,
            }
            stage_records.append(row)
            with log_path.open("a", encoding="utf-8", newline="") as log_stream:
                log_stream.write(json.dumps(row, sort_keys=True) + "\n")
                log_stream.flush()
                os.fsync(log_stream.fileno())
            strategy_dirs[strategy] = outdir
            strategy_summaries[strategy] = row
        stage_summaries[stage_name] = {
            "strategy_results": strategy_summaries,
            "fair_comparison": _compare_ledgers(strategy_dirs),
        }
    result = {"run_configuration": run_config, "stages": stage_summaries}
    _atomic_json(output / "staged_execution_summary.json", result)
    pd.DataFrame([_flatten_stage_row(row) for row in stage_records]).to_csv(
        output / "staged_execution_metrics.csv", index=False
    )
    return result


def evaluate_completed_run(output: Path, capacity: float = 8.0) -> dict:
    summary_path = output / "event_run_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing completed event run summary: {summary_path}")
    run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not run_summary.get("completed"):
        raise ValueError("Cannot evaluate a run that is not marked complete")
    strategies = tuple(run_summary["strategies"])
    if set(strategies) != set(STRATEGIES):
        raise ValueError("Final evaluation requires all three strategies")
    run_config_path = output / "phase6_run_configuration.json"
    run_config = json.loads(run_config_path.read_text(encoding="utf-8")) if run_config_path.is_file() else {}
    max_delay = float(run_config.get("simulation", {}).get("max_delay_seconds", 3600.0))
    by_strategy = {
        strategy: _ledger_summary(output / f"{strategy}_schedule.csv", capacity, strategy, max_delay)
        for strategy in strategies
    }
    for strategy, metrics in by_strategy.items():
        if metrics["tasks_processed"] != int(run_summary["tasks_processed"]):
            raise ValueError(f"{strategy} ledger row count does not match the completed run summary")
        if metrics["capacity_violations"] or metrics["task_constraint_violations"]:
            raise ValueError(
                f"Independent ledger audit found CPU/task violations in {strategy}: "
                f"capacity={metrics['capacity_violations']}, task={metrics['task_constraint_violations']}"
            )
    common = _compare_ledgers({strategy: output for strategy in strategies})
    whole_emissions = {
        strategy: by_strategy[strategy]["scheduled_observed_emissions_g_co2e"]
        for strategy in strategies
    }
    baseline = whole_emissions["fifo"]
    whole_comparison = {
        strategy: {
            "difference_vs_fifo_g_co2e": whole_emissions[strategy] - baseline,
            "percent_difference_vs_fifo": (100 * (whole_emissions[strategy] - baseline) / baseline) if baseline else None,
        }
        for strategy in strategies
    }
    common_values = common["common_population_observed_emissions_g_co2e"]
    common_baseline = common_values["fifo"]
    common_comparison = {
        strategy: {
            "difference_vs_fifo_g_co2e": common_values[strategy] - common_baseline,
            "percent_difference_vs_fifo": (100 * (common_values[strategy] - common_baseline) / common_baseline) if common_baseline else None,
        }
        for strategy in strategies
    }
    result = {
        "completed": True,
        "tasks_processed": run_summary["tasks_processed"],
        "runtime_seconds": run_summary["runtime_seconds"],
        "peak_rss_bytes": run_summary["peak_rss_bytes_process"],
        "observed_carbon_only": True,
        "population_definitions": {
            "whole_run": "All rows scheduled and executed by each strategy; observed emissions sum only rows whose full task interval is covered by observed carbon.",
            "common_population": "Task IDs executed by all three strategies and fully covered by observed carbon for all three schedules.",
        },
        "strategy_results": by_strategy,
        "common_population": common,
        "whole_run_emissions_comparison_vs_fifo": whole_comparison,
        "common_population_emissions_comparison_vs_fifo": common_comparison,
        "limitations": [
            "Emissions outside the observed carbon timeline are not imputed.",
            "Forecast replay is historical; it does not establish live forecast availability.",
            "Uncertainty intervals are used as a risk penalty and are not claimed to be calibrated.",
            "Capacity utilization is average allocated core-seconds over each strategy's scheduled time envelope.",
        ],
    }
    _atomic_json(output / "final_evaluation.json", result)
    flat_rows = []
    for strategy, metrics in by_strategy.items():
        scheduler_metrics = run_summary["strategy_metrics"][strategy]
        flat_rows.append({
            "strategy": strategy,
            "tasks_processed": metrics["tasks_processed"],
            "completed_tasks": metrics["completed_tasks"],
            "deferred_tasks": metrics["deferred_tasks"],
            "infeasible_tasks": metrics["infeasible_tasks"],
            "forecast_eligible_tasks": metrics["forecast_status_counts"].get("eligible", 0),
            "forecast_ineligible_tasks": metrics["forecast_status_counts"].get("ineligible", 0),
            "scheduled_energy_kwh": metrics["scheduled_energy_kwh"],
            "observed_emissions_g_co2e": metrics["scheduled_observed_emissions_g_co2e"],
            "emissions_covered_tasks": metrics["emissions_covered_tasks"],
            "emissions_coverage_missing_tasks": metrics["emissions_coverage_missing_tasks"],
            "mean_delay_seconds": metrics["mean_delay_seconds_scheduled_tasks"],
            "maximum_delay_seconds": metrics["maximum_delay_seconds"],
            "average_capacity_utilization_fraction": metrics["average_capacity_utilization_fraction"],
            "capacity_violations": metrics["capacity_violations"],
            "task_constraint_violations": metrics["task_constraint_violations"],
            "forecast_fallback_decisions": metrics["forecast_fallback_decisions"],
            "forecast_scoring_seconds": scheduler_metrics["forecast_scoring_seconds"],
            "rescheduled_tasks": scheduler_metrics["rescheduled_tasks"],
            "common_executed_tasks": common["common_executed_tasks"],
            "common_observed_emissions_tasks": common["common_observed_emissions_tasks"],
            "common_population_observed_emissions_g_co2e": common_values[strategy],
        })
    pd.DataFrame(flat_rows).to_csv(output / "final_evaluation_by_strategy.csv", index=False)
    return result


def verify_recovery_equivalence(
    workload: Path,
    carbon_path: Path,
    forecast_path: Path,
    resumed_output: Path,
    reference_output: Path,
    config: EventSchedulerConfig,
    *,
    max_tasks: int,
    checkpoint_interval: int = 10_000,
) -> dict:
    """Run a fresh reference and compare its trace ledger with a resumed run."""
    carbon = _carbon_frame(carbon_path, "IN-WE")
    reference = run_event_simulation(
        workload, carbon, forecast_path, reference_output, config,
        max_tasks=max_tasks, strategies=("trace",),
        checkpoint_interval=checkpoint_interval,
    )
    resumed_path = resumed_output / "trace_schedule.csv"
    reference_path = reference_output / "trace_schedule.csv"
    if not resumed_path.is_file() or not reference_path.is_file():
        raise FileNotFoundError("Recovery equivalence requires both completed TRACE ledgers")
    resumed_hash = _sha256_file(resumed_path)
    reference_hash = _sha256_file(reference_path)
    resumed_summary = json.loads((resumed_output / "event_run_summary.json").read_text(encoding="utf-8"))
    reference_summary = json.loads((reference_output / "event_run_summary.json").read_text(encoding="utf-8"))
    fields = (
        "tasks_total", "executed_tasks", "deferred_tasks", "infeasible_tasks",
        "duplicate_prevented_tasks", "forecast_eligible_tasks", "forecast_ineligible_tasks",
        "forecast_reason_counts", "rescheduled_tasks", "actual_emissions_tasks",
        "emissions_coverage_missing_tasks", "total_energy_kwh", "total_emissions_g_co2e",
    )
    resumed_metrics = resumed_summary["strategy_metrics"]["trace"]
    reference_metrics = reference_summary["strategy_metrics"]["trace"]
    metrics_equal = all(resumed_metrics[field] == reference_metrics[field] for field in fields)
    report = {
        "tasks_compared": max_tasks,
        "strategy": "trace",
        "resumed_output": str(resumed_output.resolve()),
        "reference_output": str(reference_output.resolve()),
        "resumed_ledger_sha256": resumed_hash,
        "reference_ledger_sha256": reference_hash,
        "task_decision_ledger_identical": resumed_hash == reference_hash,
        "stable_metrics_identical": metrics_equal,
        "reference_runtime_seconds": reference["runtime_seconds"],
        "equivalent": resumed_hash == reference_hash and metrics_equal and reference["tasks_processed"] == max_tasks,
    }
    if not report["equivalent"]:
        raise AssertionError(f"Interrupted/resumed output differs from uninterrupted reference: {report}")
    _atomic_json(resumed_output / "recovery_equivalence.json", report)
    return report


def reevaluate_staged_output(output: Path) -> dict:
    summary_path = output / "staged_execution_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing staged summary: {summary_path}")
    result = json.loads(summary_path.read_text(encoding="utf-8"))
    config = result["run_configuration"]["configuration"]
    rows = []
    for stage_name, stage in result["stages"].items():
        strategy_dirs = {}
        for strategy, record in stage["strategy_results"].items():
            directory = output / stage_name / strategy
            run_metrics = json.loads((directory / "event_run_summary.json").read_text(encoding="utf-8"))["strategy_metrics"][strategy]
            record.update(_ledger_summary(
                directory / f"{strategy}_schedule.csv", float(config["cpu_capacity"]), strategy,
                float(config["max_delay_seconds"]),
            ))
            record["forecast_scoring_seconds"] = run_metrics["forecast_scoring_seconds"]
            record["rescheduled_tasks"] = run_metrics["rescheduled_tasks"]
            strategy_dirs[strategy] = directory
            rows.append(record)
        stage["fair_comparison"] = _compare_ledgers(strategy_dirs)
    _atomic_json(summary_path, result)
    pd.DataFrame([_flatten_stage_row(row) for row in rows]).to_csv(
        output / "staged_execution_metrics.csv", index=False
    )
    return result


def run_full_execution(
    workload: Path,
    carbon_path: Path,
    forecast_path: Path,
    output: Path,
    config: EventSchedulerConfig,
    *,
    checkpoint_interval: int = 10_000,
    resume: bool = False,
) -> dict:
    """Run the complete workload while recording configuration and progress."""
    workload, carbon_path, forecast_path = workload.resolve(), carbon_path.resolve(), forecast_path.resolve()
    output.mkdir(parents=True, exist_ok=True)
    carbon = _carbon_frame(carbon_path, "IN-WE")
    stable_config = {
        "workload_path": str(workload), "workload_sha256": _sha256_file(workload),
        "carbon_path": str(carbon_path), "carbon_sha256": _sha256_file(carbon_path),
        "forecast_path": str(forecast_path), "forecast_sha256": _sha256_file(forecast_path),
        "zone": "IN-WE", "strategies": list(STRATEGIES),
        "simulation": config.__dict__, "checkpoint_interval": checkpoint_interval,
        "sampling": "complete validated chronological workload; no task limit",
    }
    config_path = output / "phase6_run_configuration.json"
    if resume:
        if not config_path.is_file():
            raise FileNotFoundError("Resume requires phase6_run_configuration.json")
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        if any(previous.get(key) != value for key, value in stable_config.items()):
            raise ValueError("Full-run configuration does not match saved run configuration")
    else:
        if config_path.exists():
            raise FileExistsError(f"Run configuration already exists: {config_path}")
        _atomic_json(config_path, {
            **stable_config, "created_utc": datetime.now(timezone.utc).isoformat(),
        })
        (output / "phase6_progress.jsonl").write_text("", encoding="utf-8")

    progress_path = output / "phase6_progress.jsonl"
    checkpoint_path = output / "checkpoint.sqlite3"
    stop_monitor = threading.Event()

    def monitor() -> None:
        while not stop_monitor.wait(30):
            if not checkpoint_path.is_file():
                continue
            try:
                uri = f"file:{checkpoint_path.as_posix()}?mode=ro"
                with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()
                if row is None:
                    continue
                event = {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "processed_tasks": row["processed_tasks"],
                    "last_task_id": row["last_task_id"],
                    "simulation_clock": row["simulation_clock"],
                    "elapsed_seconds": row["elapsed_seconds"],
                    "checkpoint_seconds": row["checkpoint_seconds"],
                    "peak_rss_bytes": row["peak_rss_bytes"],
                    "completed": bool(row["completed"]),
                }
                with progress_path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(json.dumps(event, sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except (sqlite3.Error, OSError):
                continue

    thread = threading.Thread(target=monitor, name="trace-phase6-progress", daemon=True)
    thread.start()
    phase6_started = time.perf_counter()
    try:
        result = run_event_simulation(
            workload, carbon, forecast_path, output, config,
            checkpoint_interval=checkpoint_interval, resume=resume,
        )
        if not result["completed"] or result["tasks_processed"] != 13_288_830:
            raise RuntimeError(
                f"Full run did not complete 13,288,830 tasks: {result.get('tasks_processed')}"
            )
        evaluation = evaluate_completed_run(output, config.cpu_capacity)
        completion = {
            "completed": True,
            "tasks_processed": result["tasks_processed"],
            "runtime_seconds": result["runtime_seconds"],
            "phase6_total_wall_seconds": time.perf_counter() - phase6_started,
            "peak_rss_bytes": result["peak_rss_bytes_process"],
            "checkpoint_seconds": result.get("checkpoint_seconds", 0.0),
            "recovery_session_seconds": result.get("recovery_session_seconds", 0.0),
            "evaluation": str((output / "final_evaluation.json").resolve()),
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(output / "phase6_completion.json", completion)
        with progress_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps({"event": "completed", **completion}, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {**completion, "evaluation_result": evaluation}
    except Exception as error:
        _atomic_json(output / "phase6_failure.json", {
            "completed": False, "error_type": type(error).__name__,
            "error": str(error), "traceback": traceback.format_exc(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "checkpoint_path": str(checkpoint_path.resolve()),
        })
        with progress_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps({"event": "failed", "error": str(error),
                                    "timestamp_utc": datetime.now(timezone.utc).isoformat()}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        raise
    finally:
        stop_monitor.set()
        thread.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=Path("results/validation/chronological_tasks.csv"))
    parser.add_argument("--carbon", type=Path, default=Path("data/raw/carbon/india_west_carbon_intensity.csv"))
    parser.add_argument("--forecasts", type=Path, default=Path("results/forecasting/rolling_seasonal_naive_forecasts.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000, 1_000_000])
    parser.add_argument("--checkpoint-interval", type=int, default=10_000)
    parser.add_argument("--resume-test-size", type=int, default=1_000_000)
    parser.add_argument("--cpu-capacity", type=float, default=8.0)
    parser.add_argument("--max-delay-seconds", type=float, default=3600.0)
    parser.add_argument("--forecast-horizon", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--risk-weight", type=float, default=0.5)
    parser.add_argument("--power-per-core-watts", type=float, default=10.0)
    parser.add_argument("--evaluate-run", type=Path, help="Stream-evaluate a completed all-strategy run")
    parser.add_argument("--reevaluate-stages", type=Path, help="Rebuild streaming task metrics from staged ledgers")
    parser.add_argument("--verify-recovery-from", type=Path, help="Compare the trace ledger in this resumed run with a fresh reference")
    parser.add_argument("--reference-output", type=Path, help="Fresh output directory for recovery equivalence reference")
    parser.add_argument("--max-tasks", type=int, default=1_000_000)
    parser.add_argument("--full-run", action="store_true", help="Run all 13,288,830 tasks after preflight")
    parser.add_argument("--resume-full", action="store_true", help="Resume the compatible full run at --output")
    args = parser.parse_args(argv)
    if args.reevaluate_stages:
        result = reevaluate_staged_output(args.reevaluate_stages)
        print(json.dumps({"reevaluated": str(args.reevaluate_stages.resolve()),
                          "stages": list(result["stages"])}, indent=2))
        return 0
    if args.evaluate_run:
        result = evaluate_completed_run(args.evaluate_run, args.cpu_capacity)
        print(json.dumps({"evaluation": str((args.evaluate_run / 'final_evaluation.json').resolve()),
                          "tasks_processed": result["tasks_processed"]}, indent=2))
        return 0
    if args.verify_recovery_from:
        if args.reference_output is None:
            parser.error("--verify-recovery-from requires --reference-output")
        config = EventSchedulerConfig(
            args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon,
            args.risk_weight, args.power_per_core_watts,
        )
        config.validate()
        result = verify_recovery_equivalence(
            args.workload, args.carbon, args.forecasts,
            args.verify_recovery_from, args.reference_output, config,
            max_tasks=args.max_tasks, checkpoint_interval=args.checkpoint_interval,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.full_run or args.resume_full:
        config = EventSchedulerConfig(
            args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon,
            args.risk_weight, args.power_per_core_watts,
        )
        config.validate()
        result = run_full_execution(
            args.workload, args.carbon, args.forecasts, args.output, config,
            checkpoint_interval=args.checkpoint_interval, resume=args.resume_full,
        )
        print(json.dumps({key: value for key, value in result.items() if key != "evaluation_result"}, indent=2))
        return 0
    config = EventSchedulerConfig(
        args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon,
        args.risk_weight, args.power_per_core_watts,
    )
    config.validate()
    result = _run_stage_suite(
        args.workload, args.carbon, args.forecasts, args.output, config,
        sizes=tuple(args.sizes), checkpoint_interval=args.checkpoint_interval,
        resume_test_size=args.resume_test_size,
    )
    print(json.dumps({"output": str(args.output.resolve()), "stages": list(result["stages"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
