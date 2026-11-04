
import pandas as pd
import pytest

from src.evaluation.scheduler_metrics import (
    calculate_schedule_emissions,
    compare_schedules,
)


def create_observed_carbon():
    return pd.DataFrame({
        "simulation_hour": [0, 1, 2, 3],
        "carbon_intensity": [500, 400, 300, 200],
    })


def test_calculate_schedule_emissions():
    tasks = pd.DataFrame({
        "start_time": [0],
        "duration_seconds": [3600],
        "energy_kwh": [0.1],
    })

    result = calculate_schedule_emissions(
        tasks,
        create_observed_carbon(),
    )

    assert result == pytest.approx(50.0)


def test_compare_schedules():
    baseline = pd.DataFrame({
        "start_time": [0],
        "duration_seconds": [3600],
        "energy_kwh": [0.1],
    })

    trace = pd.DataFrame({
        "start_time": [7200],
        "duration_seconds": [3600],
        "energy_kwh": [0.1],
    })

    result = compare_schedules(
        baseline,
        trace,
        create_observed_carbon(),
    )

    assert result["baseline_emissions_g"] == pytest.approx(50.0)
    assert result["trace_emissions_g"] == pytest.approx(30.0)
    assert result["carbon_savings_g"] == pytest.approx(20.0)
    assert result["carbon_reduction_percentage"] == pytest.approx(40.0)


def test_missing_observed_carbon_coverage():
    tasks = pd.DataFrame({
        "start_time": [14400],
        "duration_seconds": [3600],
        "energy_kwh": [0.1],
    })

    with pytest.raises(
        ValueError,
        match="complete task execution"
    ):
        calculate_schedule_emissions(
            tasks,
            create_observed_carbon(),
        )
