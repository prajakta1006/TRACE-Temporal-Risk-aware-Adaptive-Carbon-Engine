"""Independently reconcile completed Phase 6 ledgers against the workload."""

from __future__ import annotations

import csv
import hashlib
import json
from itertools import zip_longest
from pathlib import Path
import sqlite3

from src.data.task_identity import task_id_for_source_row
from src.evaluation.phase6_execution import _ledger_summary


def main() -> None:
    run_dir = Path("results/phase6/full_real_20261111_run1")
    output_dir = Path("results/phase6/independent_validation")
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_total = 13_288_830
    workload = Path("results/validation/chronological_tasks.csv")
    with sqlite3.connect(output_dir / "ledger_ids.sqlite3") as database:
        database.execute("CREATE TABLE IF NOT EXISTS seen(strategy TEXT, task_id TEXT, PRIMARY KEY(strategy, task_id)) WITHOUT ROWID")
        database.execute("DELETE FROM seen")
        checkpoint = sqlite3.connect(f"file:{(run_dir / 'checkpoint.sqlite3').resolve().as_posix()}?mode=ro", uri=True)
        checkpoint.row_factory = sqlite3.Row
        stored = dict(checkpoint.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone())
        offsets = json.loads(stored["output_offsets_json"])
        reports = {}
        all_passed = True
        for strategy in ("fifo", "earliest_feasible", "trace"):
            path = run_dir / f"{strategy}_schedule.csv"
            digest = hashlib.sha256()
            with path.open("rb") as raw:
                for block in iter(lambda: raw.read(4 * 1024 * 1024), b""):
                    digest.update(block)
            count = unique = duplicates = missing = unexpected = sequence_errors = identity_errors = 0
            workload_rows = 0
            with workload.open("r", encoding="utf-8", newline="") as expected_stream, path.open("r", encoding="utf-8", newline="") as ledger_stream:
                expected_reader = csv.DictReader(expected_stream)
                ledger_reader = csv.DictReader(ledger_stream)
                for expected, row in zip_longest(expected_reader, ledger_reader):
                    if expected is None:
                        count += 1
                        unexpected += 1
                        continue
                    workload_rows += 1
                    expected_id = task_id_for_source_row(int(expected["source_row"]))
                    if row is None:
                        missing += 1
                        sequence_errors += 1
                        continue
                    count += 1
                    task_id = row["task_id"]
                    if task_id != expected_id:
                        sequence_errors += 1
                        if task_id not in {expected_id}:
                            unexpected += 1
                        if expected_id != task_id:
                            missing += 1
                    try:
                        source_row = int(row["source_row"])
                        if task_id_for_source_row(source_row) != task_id:
                            identity_errors += 1
                    except (ValueError, TypeError):
                        identity_errors += 1
                    inserted = database.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (strategy, task_id)).rowcount
                    if inserted:
                        unique += 1
                    else:
                        duplicates += 1
                database.commit()
            metrics = _ledger_summary(path, 8.0, strategy, 3600.0)
            file_size = path.stat().st_size
            passed = all((count == expected_total, workload_rows == expected_total,
                          unique == expected_total, duplicates == 0, missing == 0,
                          unexpected == 0, sequence_errors == 0, identity_errors == 0,
                          file_size == int(offsets[strategy]),
                          metrics["capacity_violations"] == 0,
                          metrics["task_constraint_violations"] == 0))
            all_passed &= passed
            reports[strategy] = {
                "path": str(path.resolve()), "row_count": count, "expected_row_count": expected_total,
                "unique_id_count": unique, "duplicate_id_count": duplicates,
                "missing_id_count": missing, "unexpected_id_count": unexpected,
                "id_sequence_error_count": sequence_errors, "source_row_identity_error_count": identity_errors,
                "sha256": digest.hexdigest(), "byte_size": file_size,
                "checkpoint_offset": int(offsets[strategy]), "checkpoint_offset_agrees": file_size == int(offsets[strategy]),
                "task_status_counts": metrics["task_status_counts"],
                "forecast_status_counts": metrics["forecast_status_counts"],
                "forecast_reason_counts": metrics["forecast_reason_counts"],
                "decision_counts": metrics["decision_counts"],
                "forecast_fallback_decisions": metrics["forecast_fallback_decisions"],
                "scheduled_energy_kwh": metrics["scheduled_energy_kwh"],
                "scheduled_observed_emissions_g_co2e": metrics["scheduled_observed_emissions_g_co2e"],
                "emissions_covered_tasks": metrics["emissions_covered_tasks"],
                "emissions_coverage_missing_tasks": metrics["emissions_coverage_missing_tasks"],
                "capacity_violations": metrics["capacity_violations"],
                "task_constraint_violations": metrics["task_constraint_violations"],
                "independent_peak_allocated_cores": metrics["independent_peak_allocated_cores"],
                "passed": passed,
            }
        report = {
            "completed": all_passed, "independent": True, "workload_path": str(workload.resolve()),
            "workload_rows": workload_rows, "checkpoint_processed_tasks": stored["processed_tasks"],
            "checkpoint_completed": bool(stored["completed"]), "checkpoint_last_task_id": stored["last_task_id"],
            "strategies": reports,
        }
        (output_dir / "independent_validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        checkpoint.close()
        print(json.dumps(report, indent=2))
        if not all_passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
