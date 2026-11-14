import pandas as pd
import pytest

from src.scheduler.event_engine import EventSchedulerConfig, _generate_representative_workload
from src.scheduler.preflight import run_preflight
from tests.test_event_checkpoint import _inputs


def test_preflight_checks_inputs_without_starting_simulation(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    carbon_path = tmp_path / "carbon.csv"
    carbon.assign(
        zone="IN-WE",
        datetime=carbon.timestamp.astype(str),
        carbonIntensity=carbon.carbon_intensity,
    )[["zone", "datetime", "carbonIntensity"]].to_csv(carbon_path, index=False)
    output = tmp_path / "preflight-output"

    report = run_preflight(
        workload, carbon_path, forecast, output,
        EventSchedulerConfig(max_delay_seconds=3600),
        checkpoint_interval=2, minimum_free_gb=0.001,
    )

    assert report["preflight_passed"] is True
    assert report["simulation_started"] is False
    assert report["chronological_rows_checked"] == 8
    assert not (output / "checkpoint.sqlite3").exists()
    assert not list(output.glob("*_schedule.csv"))


def test_representative_benchmark_includes_required_task_mix(tmp_path):
    workload = tmp_path / "representative.csv"
    manifest = _generate_representative_workload(workload, 1_000)

    assert manifest["forecast_window_release_tasks"] > 0
    assert manifest["fallback_release_tasks"] > 0
    assert manifest["simultaneous_release_groups"] > 0
    assert manifest["multihour_tasks"] > 0
    assert manifest["over_capacity_tasks"] > 0
    assert manifest["cpu_contention_tasks"] > 0


def test_preflight_rejects_duplicate_stable_task_ids(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    one = pd.read_csv(workload, nrows=1)
    duplicate_workload = tmp_path / "duplicate.csv"
    pd.concat([one, one]).to_csv(duplicate_workload, index=False)
    carbon_path = tmp_path / "carbon.csv"
    carbon.assign(
        zone="IN-WE",
        datetime=carbon.timestamp.astype(str),
        carbonIntensity=carbon.carbon_intensity,
    )[["zone", "datetime", "carbonIntensity"]].to_csv(carbon_path, index=False)

    with pytest.raises(ValueError, match="duplicate task IDs"):
        run_preflight(
            duplicate_workload, carbon_path, forecast, tmp_path / "duplicate-preflight",
            EventSchedulerConfig(max_delay_seconds=3600),
            checkpoint_interval=2, minimum_free_gb=0.001,
        )
