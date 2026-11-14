"""Memory-bounded validation and chronological ordering for workload CSVs.

The run state and cross-chunk duplicate index are stored in SQLite. Sorted CSV
runs are written per input chunk, then externally merged by (start_time,
source-row task ID). No full-workload pandas frame is constructed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import logging
import math
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import psutil
from src.data.task_identity import DEFAULT_TASK_ID_PREFIX, task_id_for_source_row

LOGGER = logging.getLogger("trace.validation")
REQUIRED_COLUMNS = ("job_name", "task_name", "start_time", "end_time", "duration_seconds", "cpu_cores")
NUMERIC_COLUMNS = ("start_time", "end_time", "duration_seconds", "cpu_cores")
TASK_ID_PREFIX = DEFAULT_TASK_ID_PREFIX


@dataclass(frozen=True)
class ValidationConfig:
    cpu_capacity: float = 8.0
    duration_tolerance_seconds: float = 1.0
    chunk_size: int = 100_000
    task_id_prefix: str = TASK_ID_PREFIX
    carbon_timeline_hours: int = 216
    carbon_zone: str = "IN-WE"
    carbon_start_timestamp_utc: str | None = None

    def validate(self) -> None:
        if not math.isfinite(self.cpu_capacity) or self.cpu_capacity <= 0:
            raise ValueError("cpu_capacity must be positive and finite")
        if not math.isfinite(self.duration_tolerance_seconds) or self.duration_tolerance_seconds < 0:
            raise ValueError("duration_tolerance_seconds must be non-negative and finite")
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.carbon_timeline_hours <= 0:
            raise ValueError("carbon_timeline_hours must be positive")
        if not self.carbon_zone:
            raise ValueError("carbon_zone cannot be empty")
        if not self.task_id_prefix:
            raise ValueError("task_id_prefix cannot be empty")


class _PeakRssMonitor:
    """Sample resident memory during pandas and merge work, including spikes."""

    def __init__(self, interval_seconds: float = 0.1) -> None:
        self.process = psutil.Process(os.getpid())
        self.interval = interval_seconds
        self.peak_bytes = self.process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.peak_bytes = max(self.peak_bytes, self.process.memory_info().rss)
            except psutil.Error:
                return

    def __enter__(self) -> "_PeakRssMonitor":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()
        self.peak_bytes = max(self.peak_bytes, self.process.memory_info().rss)


def sha256_file(path: str | Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _empty_counts(columns: list[str]) -> dict[str, Any]:
    return {
        "total_source_rows": 0, "valid_rows": 0, "invalid_rows": 0,
        "duplicate_rows": 0, "excluded_rows": 0, "chunks_processed": 0,
        "missing_values_by_column": {column: 0 for column in columns},
        "invalid_start_time_rows": 0, "invalid_end_time_rows": 0,
        "invalid_duration_rows": 0, "nonpositive_duration_rows": 0,
        "invalid_cpu_rows": 0, "negative_cpu_rows": 0,
        "tasks_exceeding_cpu_capacity": 0, "duration_mismatch_rows": 0,
        "tasks_outside_carbon_timeline": 0,
        "minimum_start_time_seconds": None, "maximum_start_time_seconds": None,
        "minimum_end_time_seconds": None, "maximum_end_time_seconds": None,
        "maximum_duration_seconds": None, "maximum_cpu_requirement": None,
        "elapsed_runtime_seconds": 0.0, "peak_memory_bytes": 0,
        "temporary_disk_bytes_peak": 0,
    }


def _merge_extreme(counts: dict[str, Any], field: str, value: float, choose_min: bool) -> None:
    previous = counts[field]
    if previous is None or (value < previous if choose_min else value > previous):
        counts[field] = float(value)


def _read_chunk(path: Path, chunk_size: int):
    return pd.read_csv(
        path,
        chunksize=chunk_size,
        dtype={"job_name": "string", "task_name": "string"},
        low_memory=False,
    )


def _validate_chunk(raw: pd.DataFrame, source_start: int, config: ValidationConfig) -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    frame = raw.copy()
    frame.insert(0, "source_row", range(source_start, source_start + len(frame)))
    frame.insert(1, "task_id", [task_id_for_source_row(row, config.task_id_prefix) for row in frame.source_row])
    missing = {column: int(frame[column].isna().sum()) for column in raw.columns}
    numeric = {column: pd.to_numeric(frame[column], errors="coerce") for column in NUMERIC_COLUMNS}

    finite = {
        column: pd.Series(
            np.isfinite(numeric[column].to_numpy(dtype="float64", na_value=np.nan)),
            index=frame.index,
        )
        for column in NUMERIC_COLUMNS
    }
    bad_start = ~finite["start_time"] | (numeric["start_time"] < 0)
    bad_end = ~finite["end_time"] | (numeric["end_time"] < 0)
    bad_duration = ~finite["duration_seconds"] | (numeric["duration_seconds"] <= 0)
    nonpositive_duration = finite["duration_seconds"] & (numeric["duration_seconds"] <= 0)
    bad_cpu = ~finite["cpu_cores"] | (numeric["cpu_cores"] < 0)
    negative_cpu = finite["cpu_cores"] & (numeric["cpu_cores"] < 0)
    bad_identity = frame["job_name"].isna() | frame["task_name"].isna()
    end_before_start = finite["start_time"] & finite["end_time"] & (numeric["end_time"] < numeric["start_time"])
    comparable_duration = finite["start_time"] & finite["end_time"] & finite["duration_seconds"]
    mismatch = comparable_duration & ((numeric["end_time"] - numeric["start_time"] - numeric["duration_seconds"]).abs() > config.duration_tolerance_seconds)

    error_flags = {
        "missing_or_invalid_job_name": frame["job_name"].isna(),
        "missing_or_invalid_task_name": frame["task_name"].isna(),
        "invalid_start_time": bad_start,
        "invalid_end_time": bad_end,
        "invalid_or_nonpositive_duration": bad_duration,
        "invalid_or_negative_cpu": bad_cpu,
        "end_before_start": end_before_start,
        "duration_mismatch": mismatch,
    }
    invalid = pd.Series(False, index=frame.index)
    codes = pd.Series("", index=frame.index, dtype="string")
    for code, flag in error_flags.items():
        flag = flag.fillna(True)
        invalid |= flag
        separator = codes.ne("").map({True: ";", False: ""})
        codes = codes.mask(flag, codes + separator + code)

    # Normalize numeric values in outputs so ordering and downstream ingestion
    # do not depend on pandas' per-chunk dtype inference.
    for column in NUMERIC_COLUMNS:
        frame[column] = numeric[column]
    frame["validation_errors"] = codes
    stats = {
        "invalid_start_time_rows": int(bad_start.sum()),
        "invalid_end_time_rows": int(bad_end.sum()),
        "invalid_duration_rows": int(bad_duration.sum()),
        "nonpositive_duration_rows": int(nonpositive_duration.sum()),
        "invalid_cpu_rows": int(bad_cpu.sum()),
        "negative_cpu_rows": int(negative_cpu.sum()),
        "duration_mismatch_rows": int(mismatch.sum()),
    }
    return frame, invalid.astype(bool), {**stats, **{f"missing::{key}": value for key, value in missing.items()}}


def _connect_state(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=120)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-65536")  # bounded ~64 MiB page cache
    connection.execute("""
        CREATE TABLE IF NOT EXISTS identities (
            job_name TEXT NOT NULL,
            task_name TEXT NOT NULL,
            first_source_row INTEGER NOT NULL,
            PRIMARY KEY(job_name, task_name)
        ) WITHOUT ROWID
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS run_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            input_sha256 TEXT NOT NULL,
            config_json TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            started_utc TEXT NOT NULL,
            next_source_row INTEGER NOT NULL,
            chunks_processed INTEGER NOT NULL,
            counts_json TEXT NOT NULL,
            elapsed_runtime_seconds REAL NOT NULL,
            peak_memory_bytes INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.commit()
    return connection


def _insert_stage_and_find_duplicates(connection: sqlite3.Connection, frame: pd.DataFrame, valid_mask: pd.Series) -> tuple[set[int], list[tuple[int, str, str, int]]]:
    valid = frame.loc[valid_mask, ["source_row", "job_name", "task_name"]]
    connection.execute("DROP TABLE IF EXISTS temp.stage_rows")
    connection.execute("CREATE TEMP TABLE stage_rows(source_row INTEGER, job_name TEXT, task_name TEXT)")
    connection.executemany(
        "INSERT INTO stage_rows VALUES (?, ?, ?)",
        ((int(row.source_row), str(row.job_name), str(row.task_name)) for row in valid.itertuples(index=False)),
    )
    duplicates = connection.execute("""
        WITH first_in_chunk AS (
            SELECT job_name, task_name, MIN(source_row) AS first_row
            FROM stage_rows GROUP BY job_name, task_name
        )
        SELECT s.source_row, s.job_name, s.task_name,
               COALESCE(i.first_source_row, f.first_row) AS duplicate_of
        FROM stage_rows AS s
        JOIN first_in_chunk AS f USING(job_name, task_name)
        LEFT JOIN identities AS i USING(job_name, task_name)
        WHERE s.source_row > COALESCE(i.first_source_row, f.first_row)
        ORDER BY s.source_row
    """).fetchall()
    duplicate_rows = {int(row[0]) for row in duplicates}
    return duplicate_rows, [(int(r), str(j), str(t), int(first)) for r, j, t, first in duplicates]


def _insert_new_identities(connection: sqlite3.Connection) -> None:
    connection.execute("""
        INSERT OR IGNORE INTO identities(job_name, task_name, first_source_row)
        SELECT job_name, task_name, MIN(source_row)
        FROM stage_rows GROUP BY job_name, task_name
    """)


def _write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    frame.to_csv(temporary, index=False)
    with temporary.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _append_detail_runs(output: Path, prefix: str, destination: Path, columns: list[str]) -> int:
    partial = output / f"{destination.name}.partial"
    with partial.open("w", encoding="utf-8", newline="") as output_stream:
        writer = csv.writer(output_stream)
        writer.writerow(columns)
        for run in sorted(output.glob(f"{prefix}-*.csv")):
            with run.open("r", encoding="utf-8", newline="") as source:
                reader = csv.reader(source)
                next(reader, None)
                for row in reader:
                    writer.writerow(row)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    disk_peak = _directory_bytes(output)
    os.replace(partial, destination)
    return disk_peak


def _external_merge(runs: list[Path], destination: Path, columns: list[str]) -> None:
    partial = destination.with_suffix(destination.suffix + ".partial")
    streams = [path.open("r", encoding="utf-8", newline="") for path in runs]
    try:
        readers = [csv.DictReader(stream) for stream in streams]
        heap: list[tuple[float, int, int, dict[str, str]]] = []
        for index, reader in enumerate(readers):
            row = next(reader, None)
            if row is not None:
                heapq.heappush(heap, (float(row["start_time"]), int(row["source_row"]), index, row))
        with partial.open("w", encoding="utf-8", newline="") as output_stream:
            writer = csv.DictWriter(output_stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            while heap:
                _, _, index, row = heapq.heappop(heap)
                writer.writerow(row)
                next_row = next(readers[index], None)
                if next_row is not None:
                    heapq.heappush(heap, (float(next_row["start_time"]), int(next_row["source_row"]), index, next_row))
            output_stream.flush()
            os.fsync(output_stream.fileno())
        with partial.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, destination)
    finally:
        for stream in streams:
            stream.close()


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _read_state(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM run_state WHERE singleton=1").fetchone()
    if row is None:
        return None
    names = [item[1] for item in connection.execute("PRAGMA table_info(run_state)")]
    return dict(zip(names, row))


def validate_workload_file(
    input_path: str | Path,
    output_dir: str | Path = "results/validation",
    config: ValidationConfig = ValidationConfig(),
    resume: bool = False,
    log_every_chunks: int = 10,
    stop_after_chunks: int | None = None,
) -> dict[str, Any]:
    """Validate every row, externally sort valid unique tasks, and checkpoint.

    Invalid rows and duplicate valid task identities are written to separate
    detailed CSVs. The chronological file contains every structurally valid,
    unique row, including rows whose CPU request exceeds configured capacity.
    """
    config.validate()
    if stop_after_chunks is not None and stop_after_chunks <= 0:
        raise ValueError("stop_after_chunks must be positive when provided")
    input_path, output_dir = Path(input_path), Path(output_dir)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "_validation_work"
    temp_dir.mkdir(parents=True, exist_ok=True)
    database = temp_dir / "validation_state.sqlite3"
    started_call = time.perf_counter()
    input_hash = sha256_file(input_path)
    memory_monitor = _PeakRssMonitor()

    # Read the header once; all source columns are retained in valid task output.
    columns = list(pd.read_csv(input_path, nrows=0).columns)
    missing_required = sorted(set(REQUIRED_COLUMNS) - set(columns))
    if missing_required:
        raise ValueError(f"Workload is missing required columns: {missing_required}")
    config_json = json.dumps(asdict(config), sort_keys=True)
    connection = _connect_state(database)
    state = _read_state(connection)
    if state is None:
        if resume:
            raise ValueError("No validation checkpoint exists to resume")
        counts = _empty_counts(columns)
        started_utc = datetime.now(timezone.utc).isoformat()
        with connection:
            connection.execute(
                "INSERT INTO run_state VALUES (1,?,?,?,?,0,0,?,?,0,0)",
                (input_hash, config_json, json.dumps(columns), started_utc, json.dumps(counts), 0.0),
            )
        state = _read_state(connection)
    else:
        if not resume:
            connection.close()
            raise FileExistsError(f"Validation state exists at {database}; use --resume or a new output directory")
        if state["input_sha256"] != input_hash:
            raise ValueError("Input SHA-256 differs from the checkpoint; refusing to resume")
        if state["config_json"] != config_json:
            raise ValueError("Validation configuration differs from the checkpoint; refusing to resume")
        if json.loads(state["columns_json"]) != columns:
            raise ValueError("Input columns differ from the checkpoint; refusing to resume")
        if state["completed"]:
            connection.close()
            summary_path = output_dir / "validation_summary.json"
            return json.loads(summary_path.read_text(encoding="utf-8"))

    counts = json.loads(state["counts_json"])
    next_source_row = int(state["next_source_row"])
    chunk_number = int(state["chunks_processed"])
    prior_runtime = float(state["elapsed_runtime_seconds"])
    started_utc = state["started_utc"]
    # Files are published before each database checkpoint. Any file from a
    # chunk not represented by the committed checkpoint is an orphan.
    for pattern in ("ordered-run-*.csv", "invalid-run-*.csv", "duplicate-run-*.csv"):
        for run in temp_dir.glob(pattern):
            try:
                number = int(run.stem.rsplit("-", 1)[1])
            except ValueError:
                run.unlink(missing_ok=True)
                continue
            if number >= chunk_number:
                run.unlink(missing_ok=True)
    for partial in temp_dir.glob("*.partial"):
        partial.unlink(missing_ok=True)

    process_start = started_call
    chunks_this_call = 0
    interrupted = False
    with memory_monitor:
        source_row = 0
        for raw in _read_chunk(input_path, config.chunk_size):
            chunk_start = source_row
            source_row += len(raw)
            if source_row <= next_source_row:
                continue
            if chunk_start < next_source_row:
                raw = raw.iloc[next_source_row - chunk_start :].copy()
                chunk_start = next_source_row
            frame, invalid_mask, chunk_counts = _validate_chunk(raw, chunk_start, config)
            structurally_valid = ~invalid_mask

            connection.execute("BEGIN")
            try:
                duplicate_ids, duplicate_records = _insert_stage_and_find_duplicates(connection, frame, structurally_valid)
                unique_valid_mask = structurally_valid & ~frame.source_row.isin(duplicate_ids)
                invalid = frame.loc[invalid_mask].copy()
                invalid["validation_errors"] = frame.loc[invalid_mask, "validation_errors"].astype(str)
                if not invalid.empty:
                    _write_csv_atomic(temp_dir / f"invalid-run-{chunk_number:08d}.csv", invalid)
                duplicate_path = temp_dir / f"duplicate-run-{chunk_number:08d}.csv"
                duplicate_partial = duplicate_path.with_suffix(duplicate_path.suffix + ".partial")
                with duplicate_partial.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["source_row", "task_id", "job_name", "task_name", "duplicate_of_source_row"])
                    writer.writerows((row, task_id_for_source_row(row, config.task_id_prefix), job, task, first) for row, job, task, first in duplicate_records)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(duplicate_partial, duplicate_path)

                valid = frame.loc[unique_valid_mask].drop(columns=["validation_errors"]).copy()
                valid.sort_values(["start_time", "source_row"], kind="stable", inplace=True)
                run_path = temp_dir / f"ordered-run-{chunk_number:08d}.csv"
                _write_csv_atomic(run_path, valid)

                valid_count = int(unique_valid_mask.sum())
                invalid_count = int(invalid_mask.sum())
                duplicate_count = len(duplicate_ids)
                counts["total_source_rows"] += len(frame)
                counts["valid_rows"] += valid_count
                counts["invalid_rows"] += invalid_count
                counts["duplicate_rows"] += duplicate_count
                counts["excluded_rows"] += invalid_count + duplicate_count
                counts["chunks_processed"] += 1
                for key, value in chunk_counts.items():
                    if key.startswith("missing::"):
                        col = key.split("::", 1)[1]
                        counts["missing_values_by_column"][col] += value
                    else:
                        counts[key] += value
                within_capacity_data = frame.loc[unique_valid_mask]
                over_capacity = within_capacity_data.cpu_cores > config.cpu_capacity
                counts["tasks_exceeding_cpu_capacity"] += int(over_capacity.sum())
                counts["tasks_outside_carbon_timeline"] += int(
                    (within_capacity_data.end_time > config.carbon_timeline_hours * 3600).sum()
                )
                for column, selector, take_min in (
                    ("start_time", unique_valid_mask, True),
                    ("end_time", unique_valid_mask, True),
                ):
                    values = frame.loc[selector, column].dropna()
                    if not values.empty:
                        _merge_extreme(counts, f"minimum_{column}_seconds", float(values.min()), True)
                        _merge_extreme(counts, f"maximum_{column}_seconds", float(values.max()), False)
                if valid_count:
                    _merge_extreme(counts, "maximum_duration_seconds", float(within_capacity_data.duration_seconds.max()), False)
                    _merge_extreme(counts, "maximum_cpu_requirement", float(within_capacity_data.cpu_cores.max()), False)
                next_source_row = chunk_start + len(frame)
                elapsed = prior_runtime + (time.perf_counter() - process_start)
                counts["elapsed_runtime_seconds"] = elapsed
                counts["peak_memory_bytes"] = max(counts["peak_memory_bytes"], memory_monitor.peak_bytes)
                counts["temporary_disk_bytes_peak"] = max(counts["temporary_disk_bytes_peak"], _directory_bytes(temp_dir))
                _insert_new_identities(connection)
                connection.execute(
                    "UPDATE run_state SET next_source_row=?,chunks_processed=?,counts_json=?,elapsed_runtime_seconds=?,peak_memory_bytes=? WHERE singleton=1",
                    (next_source_row, counts["chunks_processed"], json.dumps(counts), elapsed, counts["peak_memory_bytes"]),
                )
                connection.commit()
                connection.execute("DROP TABLE IF EXISTS temp.stage_rows")
            except Exception:
                connection.rollback()
                raise
            if counts["chunks_processed"] % max(1, log_every_chunks) == 0:
                rate = counts["total_source_rows"] / max(elapsed, 1e-9)
                LOGGER.info("validated %s rows (%d chunks), %.0f rows/s; RSS peak %.1f MiB", f"{counts['total_source_rows']:,}", counts["chunks_processed"], rate, counts["peak_memory_bytes"] / 1024**2)
            chunk_number += 1
            chunks_this_call += 1
            if stop_after_chunks is not None and chunks_this_call >= stop_after_chunks:
                interrupted = True
                break

    if interrupted:
        connection.close()
        return {
            **counts,
            "completed": False,
            "input_path": str(input_path.resolve()),
            "input_sha256": input_hash,
            "execution_timestamp_utc": started_utc,
            "validation_configuration": asdict(config),
            "next_source_row": next_source_row,
            "checkpoint_path": str(database.resolve()),
        }

    # The source has been fully read. Merge sorted runs without materializing
    # the merged task set in memory.
    ordered_columns = ["source_row", "task_id", *columns]
    run_files = sorted(temp_dir.glob("ordered-run-*.csv"))
    merged_temporary = temp_dir / "chronological_tasks.csv"
    _external_merge(run_files, merged_temporary, ordered_columns)
    counts["temporary_disk_bytes_peak"] = max(counts["temporary_disk_bytes_peak"], _directory_bytes(temp_dir))
    os.replace(merged_temporary, output_dir / "chronological_tasks.csv")
    invalid_columns = ["source_row", "task_id", *columns, "validation_errors"]
    counts["temporary_disk_bytes_peak"] = max(
        counts["temporary_disk_bytes_peak"],
        _append_detail_runs(temp_dir, "invalid-run", output_dir / "invalid_rows.csv", invalid_columns),
    )
    duplicate_columns = ["source_row", "task_id", "job_name", "task_name", "duplicate_of_source_row"]
    counts["temporary_disk_bytes_peak"] = max(
        counts["temporary_disk_bytes_peak"],
        _append_detail_runs(temp_dir, "duplicate-run", output_dir / "duplicate_rows.csv", duplicate_columns),
    )
    elapsed = prior_runtime + (time.perf_counter() - process_start)
    counts["elapsed_runtime_seconds"] = elapsed
    counts["peak_memory_bytes"] = max(counts["peak_memory_bytes"], memory_monitor.peak_bytes)
    counts["temporary_disk_bytes_peak"] = max(counts["temporary_disk_bytes_peak"], _directory_bytes(temp_dir))
    validation_summary = {
        **counts,
        "completed": True,
        "input_path": str(input_path.resolve()),
        "input_sha256": input_hash,
        "execution_timestamp_utc": started_utc,
        "completed_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "validation_configuration": asdict(config),
        "simulation_time_unit": "seconds relative to the first observed carbon timestamp",
        "carbon_timeline_hours": config.carbon_timeline_hours,
        "carbon_zone": config.carbon_zone,
        "carbon_start_timestamp_utc": config.carbon_start_timestamp_utc,
        "rows_per_second": counts["total_source_rows"] / max(elapsed, 1e-9),
        "temporary_directory": str(temp_dir.resolve()),
        "chronological_output": str((output_dir / "chronological_tasks.csv").resolve()),
        "invalid_rows_output": str((output_dir / "invalid_rows.csv").resolve()),
        "duplicate_rows_output": str((output_dir / "duplicate_rows.csv").resolve()),
    }
    summary_path = output_dir / "validation_summary.json"
    summary_path.write_text(json.dumps(validation_summary, indent=2), encoding="utf-8")
    (output_dir / "validation_config.json").write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    summary_rows = [{"metric": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value} for key, value in validation_summary.items()]
    pd.DataFrame(summary_rows).to_csv(output_dir / "validation_summary.csv", index=False)
    pd.DataFrame([{"column": key, "missing_count": value} for key, value in counts["missing_values_by_column"].items()]).to_csv(output_dir / "missing_values_by_column.csv", index=False)
    connection.execute("UPDATE run_state SET completed=1,counts_json=?,elapsed_runtime_seconds=?,peak_memory_bytes=? WHERE singleton=1", (json.dumps(counts), elapsed, counts["peak_memory_bytes"]))
    connection.commit()
    connection.close()
    LOGGER.info("complete: %s rows, %.0f rows/s, RSS peak %.1f MiB, temp peak %.2f GiB", f"{counts['total_source_rows']:,}", validation_summary["rows_per_second"], counts["peak_memory_bytes"] / 1024**2, counts["temporary_disk_bytes_peak"] / 1024**3)
    return validation_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stream-validate and externally sort the TRACE workload")
    parser.add_argument("--input", type=Path, default=Path("data/processed/workload/workload_cleaned.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/validation"))
    parser.add_argument("--chunk-size", type=int, default=100_000)
    parser.add_argument("--cpu-capacity", type=float, default=8.0)
    parser.add_argument("--duration-tolerance-seconds", type=float, default=1.0)
    parser.add_argument("--carbon", type=Path, default=Path("data/raw/carbon/india_west_carbon_intensity.csv"))
    parser.add_argument("--zone", default="IN-WE")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-every-chunks", type=int, default=10)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from src.data.prepare_carbon import load_carbon

    carbon = load_carbon(args.carbon, zone=args.zone)
    intervals = carbon.timestamp.diff().dropna()
    if not intervals.eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Carbon timeline must be continuous and hourly for simulation-time alignment")
    config = ValidationConfig(
        cpu_capacity=args.cpu_capacity,
        duration_tolerance_seconds=args.duration_tolerance_seconds,
        chunk_size=args.chunk_size,
        carbon_timeline_hours=len(carbon),
        carbon_zone=args.zone,
        carbon_start_timestamp_utc=str(carbon.timestamp.iloc[0]),
    )
    summary = validate_workload_file(args.input, args.output_dir, config, resume=args.resume, log_every_chunks=args.log_every_chunks)
    print(json.dumps({key: summary[key] for key in ("total_source_rows", "valid_rows", "invalid_rows", "duplicate_rows", "excluded_rows", "tasks_exceeding_cpu_capacity", "tasks_outside_carbon_timeline", "elapsed_runtime_seconds", "peak_memory_bytes", "temporary_disk_bytes_peak", "rows_per_second")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
