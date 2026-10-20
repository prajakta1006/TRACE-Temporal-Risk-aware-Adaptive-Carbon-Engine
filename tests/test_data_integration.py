
"""Automated tests for TRACE workload and carbon-data integration."""

import pandas as pd
import pytest

from src.data.energy_model import (
    estimate_energy_kwh,
    estimate_co2_grams,
)
from src.data.load_workload import load_workload
from src.data.prepare_carbon import load_carbon
from src.data.integrate_emissions import calculate_emissions


def test_energy_model_calculates_energy():
    # 2 cores * 10 W/core * 1 hour = 0.02 kWh
    assert estimate_energy_kwh(3600, 2) == pytest.approx(0.02)


def test_energy_model_calculates_emissions():
    assert estimate_co2_grams(0.02, 500) == pytest.approx(10.0)


def test_energy_model_rejects_negative_duration():
    with pytest.raises(ValueError):
        estimate_energy_kwh(-1, 2)


def test_workload_loader_adds_energy(tmp_path):
    path = tmp_path / "workload.csv"
    pd.DataFrame(
        {
            "job_name": ["job1"],
            "task_name": ["task1"],
            "start_time": [0],
            "end_time": [3600],
            "duration_seconds": [3600],
            "cpu_cores": [2],
        }
    ).to_csv(path, index=False)

    result = load_workload(path)

    assert len(result) == 1
    assert result.loc[0, "energy_kwh"] == pytest.approx(0.02)


def test_workload_loader_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad_workload.csv"
    pd.DataFrame({"job_name": ["job1"]}).to_csv(path, index=False)

    with pytest.raises(ValueError, match="Missing required columns"):
        load_workload(path)


def test_carbon_loader_filters_zone_and_sorts(tmp_path):
    path = tmp_path / "carbon.csv"
    pd.DataFrame(
        {
            "zone": ["IN-WE", "OTHER", "IN-WE"],
            "datetime": [
                "2026-09-22T01:00:00Z",
                "2026-09-22T00:00:00Z",
                "2026-09-22T00:00:00Z",
            ],
            "carbonIntensity": [600, 999, 500],
        }
    ).to_csv(path, index=False)

    result = load_carbon(path, zone="IN-WE")

    assert len(result) == 2
    assert result["carbon_intensity"].tolist() == [500, 600]
    assert result["timestamp"].is_monotonic_increasing


def test_integration_calculates_emissions():
    workload = pd.DataFrame(
        {
            "job_name": ["job1", "job2"],
            "task_name": ["task1", "task2"],
            "start_time": [0, 3600],
            "end_time": [60, 3660],
            "duration_seconds": [60, 60],
            "cpu_cores": [1, 1],
            "energy_kwh": [10 / 3600 / 1000, 10 / 3600 / 1000],
        }
    )

    carbon = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-09-22T00:00:00Z",
                    "2026-09-22T01:00:00Z",
                ],
                utc=True,
            ),
            "zone": ["IN-WE", "IN-WE"],
            "carbon_intensity": [500, 600],
        }
    )

    result = calculate_emissions(workload, carbon)

    assert result["co2_g"].tolist() == pytest.approx(
        [(10 / 3600 / 1000) * 500, (10 / 3600 / 1000) * 600]
    )
    assert result["carbon_intensity"].notna().all()


def test_integration_rejects_missing_carbon_hour():
    workload = pd.DataFrame(
        {
            "job_name": ["job1"],
            "task_name": ["task1"],
            "start_time": [3600 * 3],
            "end_time": [3600 * 3 + 60],
            "duration_seconds": [60],
            "cpu_cores": [1],
            "energy_kwh": [0.001],
        }
    )

    carbon = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-09-22T00:00:00Z"], utc=True
            ),
            "zone": ["IN-WE"],
            "carbon_intensity": [500],
        }
    )

    with pytest.raises(ValueError, match="No carbon data available"):
        calculate_emissions(workload, carbon)
