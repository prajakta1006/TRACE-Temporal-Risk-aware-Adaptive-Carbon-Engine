import json

import pandas as pd

from src.data.validate_workload_stream import ValidationConfig, validate_workload_file


def validation_rows():
    return [
        {"job_name": "j", "task_name": "A", "start_time": 4, "end_time": 5, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "B", "start_time": 2, "end_time": 3, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "C", "start_time": 1, "end_time": 2, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "D", "start_time": 1, "end_time": 2, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "D", "start_time": 5, "end_time": 6, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "E0", "start_time": None, "end_time": 3, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "E1", "start_time": 2, "end_time": 2, "duration_seconds": 0, "cpu_cores": 1},
        {"job_name": "j", "task_name": "E2", "start_time": 2, "end_time": 3, "duration_seconds": 1, "cpu_cores": -1},
        {"job_name": "j", "task_name": "E3", "start_time": 4, "end_time": 3, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "E4", "start_time": 1, "end_time": 5, "duration_seconds": "bad", "cpu_cores": 1},
        {"job_name": "j", "task_name": "F", "start_time": 2, "end_time": 3, "duration_seconds": 1, "cpu_cores": 9},
        {"job_name": "j", "task_name": "A", "start_time": 6, "end_time": 7, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "E5", "start_time": 1, "end_time": 5, "duration_seconds": 1, "cpu_cores": 1},
    ]


def test_chunk_size_independent_ids_and_stable_chronological_ties(tmp_path):
    source = tmp_path / "source.csv"
    pd.DataFrame(validation_rows()).to_csv(source, index=False)
    results = []
    for size in (2, 5):
        out = tmp_path / f"out-{size}"
        summary = validate_workload_file(source, out, ValidationConfig(chunk_size=size))
        ordered = pd.read_csv(out / "chronological_tasks.csv")
        results.append((summary, ordered))
    first, second = results[0][1], results[1][1]
    assert first[["source_row", "task_id"]].equals(second[["source_row", "task_id"]])
    assert first.source_row.tolist() == [2, 3, 1, 10, 0]
    assert first.task_id.tolist() == [f"trace-task-{row:012d}" for row in [2, 3, 1, 10, 0]]
    assert first.start_time.is_monotonic_increasing


def test_validation_counts_invalid_duplicate_and_over_capacity_rows(tmp_path):
    source = tmp_path / "source.csv"
    pd.DataFrame(validation_rows()).to_csv(source, index=False)
    out = tmp_path / "out"
    summary = validate_workload_file(source, out, ValidationConfig(chunk_size=2))
    assert summary["total_source_rows"] == 13
    assert summary["valid_rows"] == 5
    assert summary["invalid_rows"] == 6
    assert summary["duplicate_rows"] == 2
    assert summary["excluded_rows"] == 8
    assert summary["tasks_exceeding_cpu_capacity"] == 1
    assert summary["invalid_start_time_rows"] == 1
    assert summary["invalid_duration_rows"] == 2
    assert summary["nonpositive_duration_rows"] == 1
    assert summary["negative_cpu_rows"] == 1
    assert summary["duration_mismatch_rows"] == 2
    assert summary["missing_values_by_column"]["start_time"] == 1
    assert summary["minimum_start_time_seconds"] == 1
    assert summary["maximum_start_time_seconds"] == 4
    assert summary["maximum_end_time_seconds"] == 5
    assert summary["maximum_duration_seconds"] == 1
    assert summary["maximum_cpu_requirement"] == 9
    duplicates = pd.read_csv(out / "duplicate_rows.csv")
    assert duplicates.source_row.tolist() == [4, 11]
    assert duplicates.duplicate_of_source_row.tolist() == [3, 0]
    invalid = pd.read_csv(out / "invalid_rows.csv")
    assert invalid.source_row.tolist() == [5, 6, 7, 8, 9, 12]
    assert summary["input_sha256"]
    assert summary["completed"] is True
    assert (out / "validation_config.json").is_file()
    assert json.loads((out / "validation_summary.json").read_text())["total_source_rows"] == 13


def test_validation_resume_keeps_original_source_row_ids(tmp_path):
    source = tmp_path / "source.csv"
    pd.DataFrame(validation_rows()).to_csv(source, index=False)
    out = tmp_path / "out"
    config = ValidationConfig(chunk_size=3)
    partial = validate_workload_file(source, out, config, stop_after_chunks=1)
    assert partial["completed"] is False
    assert partial["next_source_row"] == 3
    complete = validate_workload_file(source, out, config, resume=True)
    assert complete["completed"] is True
    ordered = pd.read_csv(out / "chronological_tasks.csv")
    assert ordered.task_id.tolist() == [f"trace-task-{row:012d}" for row in [2, 3, 1, 10, 0]]
    assert complete["total_source_rows"] == 13


def test_simulation_time_alignment_is_reported_without_excluding_rows(tmp_path):
    source = tmp_path / "outside.csv"
    pd.DataFrame([{"job_name": "j", "task_name": "late", "start_time": 3600, "end_time": 7200, "duration_seconds": 3600, "cpu_cores": 1}]).to_csv(source, index=False)
    summary = validate_workload_file(source, tmp_path / "out", ValidationConfig(chunk_size=1, carbon_timeline_hours=1))
    assert summary["valid_rows"] == 1
    assert summary["tasks_outside_carbon_timeline"] == 1
    assert summary["simulation_time_unit"].startswith("seconds relative")
