"""End-to-end, observed-carbon workload scheduling simulation.

The simulator treats workload timestamps as seconds from the first observed
carbon hour. Tasks are non-preemptive and assignments are immutable once
created. All policy comparisons use the same task rows and observed carbon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import math

from src.data.energy_model import estimate_energy_kwh
from src.data.hourly_emissions import allocate_hourly_emissions
from src.data.task_identity import DEFAULT_TASK_ID_PREFIX, task_id_for_source_row
from src.scheduler.constraints import validate_schedule_capacity
from src.scheduler.forecast_adapter import load_scheduler_forecasts
from src.scheduler.rolling_scheduler import select_task_candidate_at_origin


@dataclass(frozen=True)
class SimulationConfig:
    cpu_capacity: float = 8.0
    max_delay_seconds: float = 3600.0
    forecast_horizon: int = 4
    risk_weight: float = 0.5
    power_per_core_watts: float = 10.0


def iter_workload_chunks(path: str | Path, chunk_size: int = 100_000) -> Iterable[pd.DataFrame]:
    """Yield validated-size CSV chunks with canonical task columns."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    offset = 0
    for chunk in pd.read_csv(path, chunksize=chunk_size):
        row_count = len(chunk)
        chunk["source_row"] = range(offset, offset + row_count)
        offset += row_count
        yield normalize_workload(chunk)


def normalize_workload(workload: pd.DataFrame, power_per_core_watts: float = 10.0) -> pd.DataFrame:
    """Validate workload fields and add stable row IDs and estimated energy."""
    df = workload.copy().reset_index(drop=True)
    if "job_name" not in df and "job_id" in df:
        df["job_name"] = df["job_id"]
    if "task_name" not in df and "task_id" in df:
        df["source_task_id"] = df["task_id"]
        df["task_name"] = df["task_id"]
    if "duration_seconds" not in df and "duration" in df:
        df["duration_seconds"] = df["duration"]
    required = {"job_name", "task_name", "start_time", "duration_seconds", "cpu_cores"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Workload is missing columns: {sorted(missing)}")
    for column in ("start_time", "duration_seconds", "cpu_cores"):
        df[column] = pd.to_numeric(df[column], errors="raise")
    if df[list(required - {"job_name", "task_name"})].isna().any().any():
        raise ValueError("Workload numeric fields cannot be missing")
    if not df[["start_time", "duration_seconds", "cpu_cores"]].map(math.isfinite).all().all():
        raise ValueError("Workload numeric values must be finite")
    if (df["start_time"] < 0).any() or (df["duration_seconds"] < 0).any() or (df["cpu_cores"] < 0).any():
        raise ValueError("Workload times, durations, and CPU requests must be non-negative")
    # The configured CPU power model is authoritative for every strategy.
    df["energy_kwh"] = [estimate_energy_kwh(d, c, power_per_core_watts) for d, c in zip(df.duration_seconds, df.cpu_cores)]
    if "source_row" not in df:
        df["source_row"] = range(len(df))
    source_rows = pd.to_numeric(df["source_row"], errors="raise")
    if source_rows.isna().any() or (source_rows < 0).any() or (source_rows % 1 != 0).any() or source_rows.duplicated().any():
        raise ValueError("source_row must contain unique, non-negative integers")
    df["source_row"] = source_rows.astype("int64")
    expected_ids = [task_id_for_source_row(row) for row in df.source_row]
    if "task_id" in df and "source_row" in workload.columns:
        if df["task_id"].astype(str).tolist() != expected_ids:
            raise ValueError("task_id does not match its deterministic source_row")
    df["task_id"] = expected_ids
    df["task_uid"] = range(len(df))
    return df


def load_forecast_window_sample(
    workload_path: str | Path,
    forecast_path: str | Path,
    carbon: pd.DataFrame,
    max_tasks: int = 1000,
    chunk_size: int = 100_000,
) -> tuple[pd.DataFrame, dict]:
    """Stream the workload and retain a bounded, forecast-window sample.

    Sampling is stratified between tasks whose baseline interval overlaps
    forecast-covered target hours and tasks outside those hours. Source row
    order is restored before execution so the FIFO baseline remains faithful.
    """
    if max_tasks <= 0:
        raise ValueError("max_tasks must be positive")
    if carbon.empty:
        raise ValueError("Carbon timeline must not be empty")
    start = pd.Timestamp(carbon.timestamp.iloc[0])
    forecasts = load_scheduler_forecasts(forecast_path, str(start))
    covered_hours = set(forecasts.simulation_hour.astype(int))
    eligible_selected, outside_selected, total = [], [], 0
    quota = max_tasks // 2
    for chunk in iter_workload_chunks(workload_path, chunk_size):
        total += len(chunk)
        end_hour = ((chunk.start_time + chunk.duration_seconds - 1e-9).clip(lower=0) // 3600).astype(int)
        first_hour = (chunk.start_time // 3600).astype(int)
        mask = [any(hour in covered_hours for hour in range(int(a), int(b) + 1)) for a, b in zip(first_hour, end_hour)]
        eligible = chunk.loc[mask]
        outside = chunk.loc[[not value for value in mask]]
        eligible_needed = max(0, quota - sum(len(x) for x in eligible_selected))
        outside_needed = max(0, max_tasks - quota - sum(len(x) for x in outside_selected))
        if eligible_needed and not eligible.empty:
            eligible_selected.append(eligible.iloc[:eligible_needed])
        if outside_needed and not outside.empty:
            outside_selected.append(outside.iloc[:outside_needed])
        if sum(len(x) for x in eligible_selected) >= quota and sum(len(x) for x in outside_selected) >= max_tasks - quota:
            break
    eligible_count = sum(len(x) for x in eligible_selected)
    outside_count = sum(len(x) for x in outside_selected)
    if eligible_count + outside_count < max_tasks:
        if eligible_count < quota:
            missing = max_tasks - eligible_count - outside_count
            for chunk in iter_workload_chunks(workload_path, chunk_size):
                first_hour = (chunk.start_time // 3600).astype(int)
                end_hour = ((chunk.start_time + chunk.duration_seconds - 1e-9).clip(lower=0) // 3600).astype(int)
                mask = [any(hour in covered_hours for hour in range(int(a), int(b) + 1)) for a, b in zip(first_hour, end_hour)]
                outside = chunk.loc[[not value for value in mask]]
                if not outside.empty:
                    outside_selected.append(outside.iloc[:missing])
                    missing -= min(missing, len(outside))
                if missing <= 0:
                    break
        else:
            missing = max_tasks - eligible_count - outside_count
            for chunk in iter_workload_chunks(workload_path, chunk_size):
                first_hour = (chunk.start_time // 3600).astype(int)
                end_hour = ((chunk.start_time + chunk.duration_seconds - 1e-9).clip(lower=0) // 3600).astype(int)
                mask = [any(hour in covered_hours for hour in range(int(a), int(b) + 1)) for a, b in zip(first_hour, end_hour)]
                eligible = chunk.loc[mask]
                if not eligible.empty:
                    eligible_selected.append(eligible.iloc[:missing])
                    missing -= min(missing, len(eligible))
                if missing <= 0:
                    break
    if not eligible_selected and not outside_selected:
        raise ValueError("No tasks overlap the available forecast target hours")
    pieces = outside_selected + eligible_selected
    sample = pd.concat(pieces, ignore_index=True).sort_values("source_row", kind="stable").iloc[:max_tasks].copy()
    return sample, {"rows_scanned": total, "sampled_tasks": len(sample), "outside_coverage_sample": min(outside_count, len(sample)), "forecast_eligible_sample": min(eligible_count, len(sample)), "selection": "balanced sample of forecast-covered and uncovered tasks", "forecast_target_hours": len(covered_hours)}


def _earliest_capacity_start(task: pd.Series, assigned: list[dict], capacity: float, delay: float) -> float | None:
    release = float(task.start_time)
    latest = release + delay
    duration, cores = float(task.duration_seconds), float(task.cpu_cores)
    if cores > capacity:
        return None
    candidates = sorted({release, *(float(x["end_time"]) for x in assigned if release <= float(x["end_time"]) <= latest)})
    for start in candidates:
        if start > latest:
            continue
        proposed = pd.DataFrame([{"start_time": start, "duration_seconds": duration, "cpu_cores": cores}])
        existing = pd.DataFrame(assigned, columns=["start_time", "duration_seconds", "cpu_cores"])
        try:
            schedule = proposed if existing.empty else pd.concat([existing, proposed], ignore_index=True)
            validate_schedule_capacity(schedule, capacity)
            return start
        except ValueError:
            continue
    return None


def _observed_metrics(tasks: pd.DataFrame, carbon: pd.DataFrame) -> tuple[float, float, int]:
    if tasks.empty:
        return 0.0, 0.0, 0
    task_count = len(tasks)
    tasks = tasks.loc[tasks.duration_seconds > 0]
    if tasks.empty:
        return 0.0, 0.0, task_count
    tasks = tasks.copy()
    if "scheduled_start_time" in tasks:
        tasks["start_time"] = tasks["scheduled_start_time"]
    factors = carbon[["timestamp", "carbon_intensity"]].copy()
    factors["timestamp"] = pd.to_datetime(factors.timestamp, utc=True)
    hourly = allocate_hourly_emissions(tasks, factors)
    return float(tasks.energy_kwh.sum()), float(hourly.co2_g.sum()), task_count


def _run_policy(workload: pd.DataFrame, carbon: pd.DataFrame, forecasts: pd.DataFrame, config: SimulationConfig, policy: str, simulation_start_utc: str) -> tuple[pd.DataFrame, dict]:
    assigned: list[dict] = []
    decisions = []
    origin_lookup = {pd.Timestamp(key): group for key, group in forecasts.groupby("forecast_origin_utc")} if "forecast_origin_utc" in forecasts else {}
    forecast_hours = set(forecasts.simulation_hour.astype(int))
    carbon_hours = len(carbon)
    if policy == "fifo":
        order_column = "source_row" if "source_row" in workload else "task_uid"
        ordered = workload.sort_values(order_column, kind="stable")
    else:
        ordered = workload.sort_values(["start_time", "task_uid"], kind="stable")
    for _, task in ordered.iterrows():
        release, duration = float(task.start_time), float(task.duration_seconds)
        requested = float(task.cpu_cores)
        record = {**task.to_dict(), "policy": policy, "scheduled_start_time": float("nan"), "scheduled_end_time": float("nan"), "task_status": "deferred", "decision": "no_feasible_slot", "forecast_status": "outside_coverage", "delay_seconds": float("nan")}
        if requested > config.cpu_capacity:
            record.update(task_status="infeasible", decision="cpu_request_exceeds_capacity")
            decisions.append(record)
            continue
        if duration == 0:
            record.update(task_status="executed", decision="zero_duration", scheduled_start_time=release, scheduled_end_time=release, delay_seconds=0.0)
            decisions.append(record)
            continue
        start = None
        origin_time = pd.Timestamp(simulation_start_utc) + pd.Timedelta(seconds=(int(release // 3600) - 1) * 3600)
        first_hour = int(release // 3600)
        last_hour = int((release + duration - 1e-9) // 3600)
        baseline_covered = all(hour in forecast_hours for hour in range(first_hour, last_hour + 1))
        origin_hours = set(origin_lookup[origin_time].simulation_hour.astype(int)) if origin_time in origin_lookup else set()
        origin_covers_baseline = all(hour in origin_hours for hour in range(first_hour, last_hour + 1))
        if baseline_covered and origin_time in origin_lookup:
            record["forecast_status"] = "eligible" if origin_covers_baseline else "incomplete_origin_coverage"
        if policy == "trace" and record["forecast_status"] == "eligible":
            try:
                proposal = select_task_candidate_at_origin(
                    task=pd.Series(task), rolling_forecasts=forecasts,
                    forecast_origin_utc=str(origin_time), simulation_start_utc=simulation_start_utc,
                    scheduled_tasks=pd.DataFrame(assigned) if assigned else None, cpu_capacity=config.cpu_capacity,
                    forecast_hours=config.forecast_horizon, max_delay_seconds=config.max_delay_seconds,
                    risk_weight=config.risk_weight,
                )
                if proposal:
                    start = float(proposal["start_time"])
                    record["decision"] = "rescheduled"
            except ValueError:
                raise
        if start is None:
            start = _earliest_capacity_start(task, assigned, config.cpu_capacity, config.max_delay_seconds)
            if start is not None:
                record["decision"] = "original_or_earliest_feasible"
        if start is not None and start + duration <= carbon_hours * 3600:
            reservation = {"start_time": start, "duration_seconds": duration, "cpu_cores": requested, "end_time": start + duration, "task_uid": int(task.task_uid)}
            assigned.append(reservation)
            record.update(scheduled_start_time=start, scheduled_end_time=start + duration, task_status="executed", delay_seconds=start - release)
        elif start is not None:
            record.update(scheduled_start_time=start, scheduled_end_time=start + duration, task_status="deferred", decision="outside_observed_carbon_timeline", delay_seconds=start - release)
        decisions.append(record)
    ledger = pd.DataFrame(decisions)
    executed = ledger.loc[(ledger.task_status == "executed") & (ledger.duration_seconds > 0)].copy()
    energy, emissions, _ = _observed_metrics(executed, carbon)
    count = int((ledger.task_status == "executed").sum())
    delays = ledger.loc[ledger.task_status == "executed", "delay_seconds"]
    try:
        capacity_rows = executed[["scheduled_start_time", "duration_seconds", "cpu_cores"]].rename(columns={"scheduled_start_time": "start_time"})
        validate_schedule_capacity(capacity_rows, config.cpu_capacity)
        violations = 0
    except ValueError:
        violations = 1
    stats = {
        "strategy": policy, "tasks_total": len(workload), "scheduled_tasks": int(ledger.scheduled_start_time.notna().sum()),
        "executed_tasks": count, "deferred_tasks": int((ledger.task_status == "deferred").sum()),
        "infeasible_tasks": int((ledger.task_status == "infeasible").sum()),
        "total_energy_kwh": energy, "total_emissions_g_co2e": emissions,
        "average_task_delay_seconds": float(delays.mean()) if count else 0.0,
        "maximum_task_delay_seconds": float(delays.max()) if count else 0.0,
        "cpu_capacity_violations": violations,
        "forecast_eligible_tasks": int((ledger.forecast_status == "eligible").sum()) if policy == "trace" else 0,
        "forecast_outside_coverage_tasks": int((ledger.forecast_status == "outside_coverage").sum()) if policy == "trace" else 0,
        "forecast_incomplete_origin_tasks": int((ledger.forecast_status == "incomplete_origin_coverage").sum()) if policy == "trace" else 0,
        "rescheduled_tasks": int((ledger.decision == "rescheduled").sum()) if policy == "trace" else 0,
    }
    return ledger, stats


def run_simulation(workload: pd.DataFrame, carbon: pd.DataFrame, forecast_csv: str | Path, config: SimulationConfig = SimulationConfig()) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run FIFO, earliest-feasible, and TRACE and return ledgers and metrics."""
    if not 1 <= config.forecast_horizon <= 4:
        raise ValueError("Current rolling forecast integration supports horizons from one to four hours")
    if not math.isfinite(config.cpu_capacity) or config.cpu_capacity <= 0:
        raise ValueError("cpu_capacity must be positive and finite")
    if not math.isfinite(config.max_delay_seconds) or config.max_delay_seconds < 0:
        raise ValueError("max_delay_seconds must be non-negative and finite")
    if not math.isfinite(config.power_per_core_watts) or config.power_per_core_watts < 0:
        raise ValueError("power_per_core_watts must be non-negative and finite")
    if not math.isfinite(config.risk_weight) or not 0 <= config.risk_weight <= 1:
        raise ValueError("risk_weight must be between 0 and 1")
    tasks = normalize_workload(workload, config.power_per_core_watts)
    carbon = carbon.sort_values("timestamp").reset_index(drop=True).copy()
    forecasts = load_scheduler_forecasts(forecast_csv, str(pd.Timestamp(carbon.timestamp.iloc[0])))
    ledgers, metrics = [], []
    for policy in ("fifo", "earliest_feasible", "trace"):
        ledger, stats = _run_policy(tasks, carbon, forecasts, config, policy, str(pd.Timestamp(carbon.timestamp.iloc[0])))
        ledgers.append(ledger)
        metrics.append(stats)
    combined = pd.concat(ledgers, ignore_index=True)
    common_ids = None
    for policy in ("fifo", "earliest_feasible", "trace"):
        policy_ledger = combined.loc[(combined.policy == policy) & (combined.task_status == "executed")]
        ids = set(policy_ledger.task_uid)
        common_ids = ids if common_ids is None else common_ids.intersection(ids)
    comparison = pd.DataFrame(metrics)
    common_emissions = {}
    for policy in ("fifo", "earliest_feasible", "trace"):
        rows = combined.loc[(combined.policy == policy) & combined.task_uid.isin(common_ids) & (combined.task_status == "executed") & (combined.duration_seconds > 0)]
        energy, emissions, count = _observed_metrics(rows, carbon)
        common_emissions[policy] = emissions
        comparison.loc[comparison.strategy == policy, "common_population_tasks"] = len(common_ids)
        comparison.loc[comparison.strategy == policy, "common_population_energy_kwh"] = energy
        comparison.loc[comparison.strategy == policy, "common_population_emissions_g_co2e"] = emissions
    fifo_emissions = common_emissions["fifo"]
    savings = {strategy: fifo_emissions - common_emissions[strategy] for strategy in common_emissions}
    savings = {strategy: (0.0 if abs(value) < 1e-12 else value) for strategy, value in savings.items()}
    comparison["carbon_savings_vs_fifo_g"] = comparison.strategy.map(savings)
    comparison["carbon_reduction_vs_fifo_percentage"] = comparison.strategy.map(lambda strategy: (savings[strategy] / fifo_emissions * 100) if fifo_emissions else 0.0)
    return combined, comparison, forecasts


def write_simulation_outputs(ledger: pd.DataFrame, metrics: pd.DataFrame, output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    (output_dir / "simulation").mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation").mkdir(parents=True, exist_ok=True)
    ledger.to_csv(output_dir / "simulation" / "task_schedule.csv", index=False)
    ledger[["source_row", "task_id", "task_uid", "policy", "decision", "task_status", "forecast_status"]].to_csv(output_dir / "simulation" / "scheduling_decisions.csv", index=False)
    metrics.to_csv(output_dir / "simulation" / "execution_summary.csv", index=False)
    metrics.to_csv(output_dir / "evaluation" / "strategy_comparison.csv", index=False)
    metrics.loc[metrics.strategy == "trace"].to_csv(output_dir / "evaluation" / "trace_metrics.csv", index=False)
    metrics[["strategy", "cpu_capacity_violations"]].assign(capacity_valid=metrics.cpu_capacity_violations.eq(0)).to_csv(output_dir / "evaluation" / "capacity_validation.csv", index=False)
