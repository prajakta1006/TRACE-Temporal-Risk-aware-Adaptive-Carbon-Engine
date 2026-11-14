import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.scheduler.event_engine import EventSchedulerConfig, run_event_simulation


BASE = pd.Timestamp("2026-01-01T00:00:00Z")


def _inputs(tmp_path, release_times=None, long=False):
    carbon = pd.DataFrame({
        "timestamp": pd.date_range(BASE, periods=16, freq="h"),
        "carbon_intensity": [700.0 - i for i in range(16)],
    })
    forecast_path = tmp_path / "forecasts.csv"
    rows = []
    # No forecast rows are intentional: the tests exercise safe fallback and
    # ensure checkpointing does not change ineligible-task decisions.
    pd.DataFrame(columns=[
        "timestamp_utc", "forecast_origin_utc", "horizon_hours",
        "simulation_hour", "predicted_carbon_intensity", "lower_bound", "upper_bound",
    ]).to_csv(forecast_path, index=False)
    workload = tmp_path / "chronological.csv"
    if release_times is None:
        release_times = [0, 0, 100, 3600, 3600, 7200, 7200, 8000]
    for source_row, release in enumerate(release_times):
        rows.append({
            "source_row": source_row,
            "task_id": f"trace-task-{source_row:012d}",
            "job_name": "checkpoint-test",
            "task_name": f"task-{source_row}",
            "start_time": release,
            "duration_seconds": 7200 if long and source_row == 0 else 120 + (source_row % 3) * 30,
            "cpu_cores": 8 if source_row in (0, 3) else 2,
        })
    with workload.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return workload, carbon, forecast_path


def _run(workload, carbon, forecast, output, **options):
    return run_event_simulation(
        workload, carbon, forecast, output,
        EventSchedulerConfig(max_delay_seconds=3600),
        checkpoint_interval=options.pop("checkpoint_interval", 2),
        **options,
    )


def _assert_equivalent(reference, resumed, strategies=("fifo", "earliest_feasible", "trace")):
    for strategy in strategies:
        expected = pd.read_csv(reference / f"{strategy}_schedule.csv")
        actual = pd.read_csv(resumed / f"{strategy}_schedule.csv")
        pd.testing.assert_frame_equal(expected, actual, check_dtype=False)
    expected_metrics = pd.read_csv(reference / "execution_summary.csv").set_index("strategy")
    actual_metrics = pd.read_csv(resumed / "execution_summary.csv").set_index("strategy")
    stable_fields = [
        "tasks_total", "executed_tasks", "deferred_tasks", "infeasible_tasks",
        "duplicate_prevented_tasks", "forecast_eligible_tasks", "forecast_ineligible_tasks",
        "rescheduled_tasks", "actual_emissions_tasks", "total_energy_kwh",
        "total_emissions_g_co2e", "common_executed_population",
        "common_population_emissions_tasks", "common_population_emissions_g_co2e",
    ]
    pd.testing.assert_frame_equal(expected_metrics[stable_fields], actual_metrics[stable_fields], check_dtype=False)


@pytest.mark.parametrize(
    "interrupt_point,after,long,release_times",
    [
        ("after_decisions", 5, False, [0, 0, 100, 3600, 3600, 7200, 7200, 8000]),
        ("during_output_write", 5, False, [0, 0, 100, 3600, 3600, 7200, 7200, 8000]),
        ("while_running", 2, True, [0, 0, 100, 3600, 3600, 7200, 7200, 8000]),
        ("hour_boundary", 1, False, [3600, 3600, 3700, 7200]),
    ],
)
def test_resume_matches_uninterrupted_for_recovery_points(tmp_path, interrupt_point, after, long, release_times):
    workload, carbon, forecast = _inputs(tmp_path, release_times, long)
    reference = tmp_path / f"reference-{interrupt_point}"
    interrupted = tmp_path / f"interrupted-{interrupt_point}"
    expected = _run(workload, carbon, forecast, reference)
    partial = _run(
        workload, carbon, forecast, interrupted,
        interrupt_after_tasks=after, interrupt_point=interrupt_point,
    )
    assert partial["completed"] is False
    resumed = _run(workload, carbon, forecast, interrupted, resume=True)
    assert resumed["completed"] is True
    _assert_equivalent(reference, interrupted)
    assert expected["strategy_specific_executed"] == resumed["strategy_specific_executed"]


def test_resume_rejects_changed_input_and_configuration(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    output = tmp_path / "recover"
    partial = _run(workload, carbon, forecast, output, interrupt_after_tasks=3)
    assert partial["completed"] is False
    changed = workload.read_text(encoding="utf-8").replace("start_time", "release_time", 1)
    altered = tmp_path / "altered.csv"
    altered.write_text(changed, encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        run_event_simulation(altered, carbon, forecast, output, EventSchedulerConfig(max_delay_seconds=3600), checkpoint_interval=2, resume=True)
    with pytest.raises(ValueError, match="incompatible"):
        run_event_simulation(workload, carbon, forecast, output, EventSchedulerConfig(cpu_capacity=7, max_delay_seconds=3600), checkpoint_interval=2, resume=True)


def test_checkpoint_contains_cursor_and_recovers_output_tail(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    output = tmp_path / "recover-tail"
    result = _run(workload, carbon, forecast, output, interrupt_after_tasks=5)
    assert result["tasks_checkpointed"] == 4
    fifo = output / "fifo_schedule.csv"
    assert fifo.stat().st_size > result["output_offsets"]["fifo"]
    _run(workload, carbon, forecast, output, resume=True)
    lines = fifo.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 9  # header plus every task exactly once
    assert len(set(line.split(",", 2)[1] for line in lines[1:])) == 8
    summary = json.loads((output / "event_run_summary.json").read_text(encoding="utf-8"))
    assert summary["tasks_processed"] == 8


def test_abrupt_process_exit_after_output_fsync_recovers_without_duplicate_or_skip(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    carbon_path = tmp_path / "carbon.csv"
    pd.DataFrame({
        "timestamp": carbon.timestamp.astype(str),
        "carbon_intensity": carbon.carbon_intensity,
    }).to_csv(carbon_path, index=False)
    reference = tmp_path / "abrupt-reference"
    output = tmp_path / "abrupt-recovery"
    expected = _run(workload, carbon, forecast, reference, checkpoint_interval=2)

    child = r'''
import os, sys
import pandas as pd
from src.scheduler import event_engine as engine
from src.scheduler.event_engine import EventSchedulerConfig
original_save = engine.CheckpointStore.save
def terminate_before_checkpoint_commit(self, state):
    if state["processed_tasks"] == 2:
        os._exit(79)
    return original_save(self, state)
engine.CheckpointStore.save = terminate_before_checkpoint_commit
carbon = pd.read_csv(sys.argv[3])
carbon["timestamp"] = pd.to_datetime(carbon["timestamp"], utc=True)
engine.run_event_simulation(
    sys.argv[1], carbon, sys.argv[2], sys.argv[4],
    EventSchedulerConfig(max_delay_seconds=3600), checkpoint_interval=2,
)
'''
    process = subprocess.run(
        [sys.executable, "-c", child, str(workload), str(forecast), str(carbon_path), str(output)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert process.returncode == 79, process.stderr

    with sqlite3.connect(output / "checkpoint.sqlite3") as connection:
        checkpoint = connection.execute("SELECT processed_tasks, output_offsets_json FROM checkpoint WHERE singleton=1").fetchone()
        seen_count = connection.execute("SELECT count(*) FROM seen").fetchone()[0]
    assert checkpoint[0] == 0
    assert seen_count == 0
    committed_offset = json.loads(checkpoint[1])["fifo"]
    assert (output / "fifo_schedule.csv").stat().st_size > committed_offset

    resumed = _run(workload, carbon, forecast, output, checkpoint_interval=2, resume=True)
    assert resumed["completed"] is True
    _assert_equivalent(reference, output)
    assert expected["tasks_processed"] == resumed["tasks_processed"] == 8


def test_completed_checkpoint_rejects_output_size_drift(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    output = tmp_path / "completed-output-drift"
    _run(workload, carbon, forecast, output)
    with (output / "fifo_schedule.csv").open("a", encoding="utf-8") as stream:
        stream.write("unexpected tail\n")

    with pytest.raises(ValueError, match="committed offset"):
        _run(workload, carbon, forecast, output, resume=True)
