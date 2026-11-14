"""Read-only (with a temporary write probe) full-scale scheduler preflight."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from src.scheduler.event_engine import (
    STRATEGIES,
    EventScheduler,
    EventSchedulerConfig,
    _checkpoint_config_signature,
    _carbon_frame,
    _read_ordered_tasks,
    _sha256_file,
    load_scheduler_forecasts,
)


def _carbon_hash(carbon: pd.DataFrame) -> str:
    signature = pd.DataFrame({
        "timestamp": pd.to_datetime(carbon.timestamp, utc=True).astype(str),
        "carbon_intensity": pd.to_numeric(carbon.carbon_intensity).astype(float),
    }).to_csv(index=False).encode("utf-8")
    import hashlib
    return hashlib.sha256(signature).hexdigest()


def _validation_temp_bytes(workload_path: Path) -> int:
    root = workload_path.parents[2] / "results" / "validation" / "_validation_work"
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def run_preflight(
    workload: Path,
    carbon_path: Path,
    forecast_path: Path,
    output_dir: Path,
    config: EventSchedulerConfig,
    *,
    zone: str = "IN-WE",
    strategies: tuple[str, ...] = STRATEGIES,
    checkpoint_interval: int = 10_000,
    max_tasks: int | None = None,
    resume: bool = False,
    minimum_free_gb: float = 15.0,
) -> dict:
    """Check all run prerequisites without creating scheduler state."""
    config.validate()
    if checkpoint_interval <= 0:
        raise ValueError("checkpoint_interval must be positive")
    if not strategies or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies):
        raise ValueError("Invalid strategy selection")
    if max_tasks is not None and max_tasks < 0:
        raise ValueError("max_tasks must be non-negative")
    if minimum_free_gb <= 0:
        raise ValueError("minimum_free_gb must be positive")
    for path in (workload, carbon_path, forecast_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    workload = workload.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not resume:
        conflicts = [
            output_dir / name for name in (
                "checkpoint.sqlite3", "execution_summary.csv", "event_run_summary.json",
                *(f"{strategy}_schedule.csv" for strategy in strategies),
            ) if (output_dir / name).exists()
        ]
        if conflicts:
            raise FileExistsError(f"Output directory is not clean: {conflicts}")
    with tempfile.NamedTemporaryFile(prefix=".trace_preflight_", dir=output_dir, delete=True) as probe:
        probe.write(b"preflight-writable\n")
        probe.flush()
        os.fsync(probe.fileno())

    input_sha = _sha256_file(workload)
    carbon = _carbon_frame(carbon_path, zone)
    carbon_sha = _carbon_hash(carbon)
    forecast_sha = _sha256_file(forecast_path)
    forecasts = load_scheduler_forecasts(forecast_path, str(carbon.timestamp.iloc[0]))
    forecast_projection = forecasts[[
        "timestamp_utc", "forecast_origin_utc", "horizon_hours",
        "simulation_hour", "predicted_carbon_intensity", "lower_bound",
        "upper_bound",
    ]].copy()
    for strategy in strategies:
        EventScheduler(strategy, carbon, forecast_projection, config, track_seen=False)

    task_count = 0
    previous = None
    identity_batch: list[tuple[str]] = []
    unique_identity_rows = 0
    with tempfile.TemporaryDirectory(prefix=".trace_identity_check_", dir=output_dir) as temp_dir:
        with closing(sqlite3.connect(Path(temp_dir) / "identity.sqlite3")) as identity_db:
            identity_db.execute("PRAGMA journal_mode=OFF")
            identity_db.execute("PRAGMA synchronous=OFF")
            identity_db.execute("PRAGMA temp_store=FILE")
            identity_db.execute("CREATE TABLE seen(task_id TEXT PRIMARY KEY)")
            try:
                for task in _read_ordered_tasks(workload):
                    key = (task["start_time"], task["task_id"])
                    if previous is not None and key < previous:
                        raise ValueError("Chronological workload ordering check failed")
                    previous = key
                    identity_batch.append((task["task_id"],))
                    task_count += 1
                    if len(identity_batch) >= 20_000:
                        cursor = identity_db.executemany("INSERT OR IGNORE INTO seen VALUES (?)", identity_batch)
                        unique_identity_rows += cursor.rowcount
                        if unique_identity_rows != task_count:
                            raise ValueError("Chronological workload contains duplicate task IDs")
                        identity_db.commit()
                        identity_batch.clear()
                if identity_batch:
                    cursor = identity_db.executemany("INSERT OR IGNORE INTO seen VALUES (?)", identity_batch)
                    unique_identity_rows += cursor.rowcount
                    if unique_identity_rows != task_count:
                        raise ValueError("Chronological workload contains duplicate task IDs")
                    identity_db.commit()
            finally:
                identity_db.rollback()

    free_bytes = shutil.disk_usage(output_dir).free
    minimum_bytes = int(minimum_free_gb * 1024**3)
    checkpoint_path = output_dir / "checkpoint.sqlite3"
    config_signature = _checkpoint_config_signature(
        config, max_tasks=max_tasks,
        forecast_sha256=forecast_sha, carbon_sha256=carbon_sha,
    )
    strategies_json = json.dumps(list(strategies), separators=(",", ":"))
    checkpoint_status = "not_requested"
    if resume:
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"No checkpoint to resume: {checkpoint_path}")
        uri = f"file:{checkpoint_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("Checkpoint has no committed state")
        expected = {
            "input_sha256": input_sha,
            "input_path": str(workload),
            "output_dir": str(output_dir.resolve()),
            "config_json": config_signature,
            "strategies_json": strategies_json,
            "checkpoint_interval": checkpoint_interval,
        }
        mismatch = [key for key, value in expected.items() if row[key] != value]
        if mismatch:
            raise ValueError(f"Checkpoint is incompatible; mismatched fields: {mismatch}")
        offsets = json.loads(row["output_offsets_json"])
        for strategy in strategies:
            path = output_dir / f"{strategy}_schedule.csv"
            expected_size = int(offsets[strategy])
            invalid_size = (
                path.stat().st_size != expected_size if row["completed"]
                else path.stat().st_size < expected_size
            ) if path.is_file() else True
            if invalid_size:
                raise ValueError(f"Checkpoint output is missing or truncated: {path}")
        if row["completed"] and not all((output_dir / name).is_file() for name in ("event_run_summary.json", "execution_summary.csv")):
            raise ValueError("Completed checkpoint is missing final summary output")
        checkpoint_status = "complete" if row["completed"] else "compatible_incomplete"

    if free_bytes < minimum_bytes:
        raise OSError(f"Insufficient free disk: {free_bytes / 1024**3:.2f} GiB available, {minimum_free_gb:.2f} GiB required")
    return {
        "preflight_passed": True,
        "simulation_started": False,
        "workload_path": str(workload),
        "workload_sha256": input_sha,
        "chronological_rows_checked": task_count,
        "unique_task_ids_checked": unique_identity_rows,
        "carbon_sha256": carbon_sha,
        "forecast_sha256": forecast_sha,
        "forecast_rows_checked": len(forecast_projection),
        "zone": zone,
        "strategies": list(strategies),
        "simulation_configuration": config.__dict__,
        "checkpoint_interval": checkpoint_interval,
        "checkpoint_status": checkpoint_status,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "available_disk_bytes": free_bytes,
        "minimum_required_disk_bytes": minimum_bytes,
        "existing_phase2_temporary_sort_bytes": _validation_temp_bytes(workload),
        "output_directory_writable": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=Path("results/validation/chronological_tasks.csv"))
    parser.add_argument("--carbon", type=Path, default=Path("data/raw/carbon/india_west_carbon_intensity.csv"))
    parser.add_argument("--forecasts", type=Path, default=Path("results/forecasting/rolling_seasonal_naive_forecasts.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/simulation/event_based"))
    parser.add_argument("--zone", default="IN-WE")
    parser.add_argument("--cpu-capacity", type=float, default=8.0)
    parser.add_argument("--max-delay-seconds", type=float, default=3600.0)
    parser.add_argument("--forecast-horizon", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--risk-weight", type=float, default=0.5)
    parser.add_argument("--power-per-core-watts", type=float, default=10.0)
    parser.add_argument("--checkpoint-interval", type=int, default=10_000)
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--minimum-free-gb", type=float, default=15.0)
    args = parser.parse_args(argv)
    config = EventSchedulerConfig(args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon, args.risk_weight, args.power_per_core_watts)
    report = run_preflight(
        args.workload, args.carbon, args.forecasts, args.output, config,
        zone=args.zone, strategies=tuple(args.strategies),
        checkpoint_interval=args.checkpoint_interval, max_tasks=args.max_tasks,
        resume=args.resume, minimum_free_gb=args.minimum_free_gb,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
