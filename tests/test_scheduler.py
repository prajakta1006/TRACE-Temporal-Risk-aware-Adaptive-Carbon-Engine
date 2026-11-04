
import pandas as pd
import pytest

from src.scheduler.scheduler import select_task_candidate


def create_task():
    return pd.Series({
        "start_time": 3600,
        "duration_seconds": 1800,
        "cpu_cores": 2,
        "energy_kwh": 0.01,
    })


def create_forecasts():
    return pd.DataFrame({
        "simulation_hour": [1, 2, 3, 4, 5],
        "predicted_carbon_intensity": [600, 450, 400, 500, 550],
        "upper_bound": [650, 500, 450, 550, 600],
    })


def test_select_best_candidate():
    result = select_task_candidate(
        task=create_task(),
        forecasts=create_forecasts(),
        current_time=3600,
        risk_weight=0.5,
    )

    assert result is not None
    assert result["start_time"] == 7200.0
    assert result["risk_adjusted_savings_g"] > 0


def test_no_positive_carbon_savings():
    forecasts = create_forecasts()
    forecasts["predicted_carbon_intensity"] = [400, 600, 650, 700, 750]
    forecasts["upper_bound"] = [450, 650, 700, 750, 800]

    result = select_task_candidate(
        task=create_task(),
        forecasts=forecasts,
        current_time=3600,
    )

    assert result is None


def test_candidate_rejected_when_cpu_capacity_exceeded():
    scheduled_tasks = pd.DataFrame({
        "start_time": [7200],
        "duration_seconds": [3600],
        "cpu_cores": [7],
    })

    result = select_task_candidate(
        task=create_task(),
        forecasts=create_forecasts(),
        current_time=3600,
        scheduled_tasks=scheduled_tasks,
        cpu_capacity=8,
    )

    assert result is None


def test_invalid_risk_weight():
    with pytest.raises(ValueError):
        select_task_candidate(
            task=create_task(),
            forecasts=create_forecasts(),
            current_time=3600,
            risk_weight=1.5,
        )
def test_long_running_task_can_be_selected_with_full_forecast_coverage():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 5 * 3600,
        "cpu_cores": 2,
        "energy_kwh": 0.1,
    })

    forecasts = pd.DataFrame({
        "simulation_hour": list(range(1, 9)),
        "predicted_carbon_intensity": [
            600, 450, 400, 350, 300, 250, 200, 150
        ],
        "upper_bound": [
            650, 500, 450, 400, 350, 300, 250, 200
        ],
    })

    result = select_task_candidate(
        task=task,
        forecasts=forecasts,
        current_time=3600,
        forecast_hours=4,
        max_delay_seconds=3600,
        risk_weight=0.5,
    )

    assert result is not None
    assert result["end_time"] > 4 * 3600
    
def test_baseline_carbon_uses_full_task_duration():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 7200,
        "cpu_cores": 2,
        "energy_kwh": 0.1,
    })

    forecasts = pd.DataFrame({
        "simulation_hour": [1, 2, 3],
        "predicted_carbon_intensity": [600, 400, 400],
        "upper_bound": [600, 400, 400],
    })

    result = select_task_candidate(
        task=task,
        forecasts=forecasts,
        current_time=3600,
        risk_weight=0,
    )

    assert result is not None
    assert result["start_time"] == 7200.0
    assert result["expected_savings_g"] == pytest.approx(10.0)

def test_missing_baseline_forecast_raises_error():
    task = create_task()

    forecasts = pd.DataFrame({
        "simulation_hour": [2, 3, 4, 5],
        "predicted_carbon_intensity": [450, 400, 500, 550],
        "upper_bound": [500, 450, 550, 600],
    })

    with pytest.raises(
        ValueError,
        match="complete baseline execution period"
    ):
        select_task_candidate(
            task=task,
            forecasts=forecasts,
            current_time=3600,
        )
        
def test_negative_forecast_values_are_rejected():
    forecasts = create_forecasts()
    forecasts.loc[0, "predicted_carbon_intensity"] = -10

    with pytest.raises(
        ValueError,
        match="non-negative"
    ):
        select_task_candidate(
            task=create_task(),
            forecasts=forecasts,
            current_time=3600,
        )