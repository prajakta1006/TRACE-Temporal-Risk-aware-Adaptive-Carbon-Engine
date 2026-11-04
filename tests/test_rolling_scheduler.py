
import pandas as pd
import pytest

import src.scheduler.rolling_scheduler as rolling_scheduler


def make_forecasts():
    origin = pd.Timestamp("2026-09-29T04:00:00Z")

    return pd.DataFrame({
        "forecast_origin_utc": [origin] * 4,
        "timestamp_utc": pd.date_range(
            "2026-09-29T05:00:00Z",
            periods=4,
            freq="h",
        ),
        "simulation_hour": [173, 174, 175, 176],
        "horizon_hours": [1, 2, 3, 4],
        "predicted_carbon_intensity": [471, 481, 476, 484],
        "upper_bound": [550, 560, 555, 563],
    })


def test_selects_correct_forecast_origin(monkeypatch):
    captured = {}

    def fake_scheduler(**kwargs):
        captured.update(kwargs)
        return {"start_time": 7200}

    monkeypatch.setattr(
        rolling_scheduler,
        "select_task_candidate",
        fake_scheduler,
    )

    result = rolling_scheduler.select_task_candidate_at_origin(
        task=pd.Series({
            "start_time": 172 * 3600,
            "duration_seconds": 1800,
            "cpu_cores": 2,
            "energy_kwh": 0.01,
        }),
        rolling_forecasts=make_forecasts(),
        forecast_origin_utc="2026-09-29T04:00:00Z",
        simulation_start_utc="2026-09-22T00:00:00Z",
    )

    assert result == {"start_time": 7200}
    assert len(captured["forecasts"]) == 4
    assert captured["forecasts"]["horizon_hours"].tolist() == [1, 2, 3, 4]
    assert captured["current_time"] == 172 * 3600


def test_rejects_origin_with_missing_forecast_hours():
    forecasts = make_forecasts().iloc[:3].copy()

    with pytest.raises(ValueError, match="Expected 4 forecasts"):
        rolling_scheduler.select_task_candidate_at_origin(
            task=pd.Series({
                "start_time": 172 * 3600,
                "duration_seconds": 1800,
                "cpu_cores": 2,
                "energy_kwh": 0.01,
            }),
            rolling_forecasts=forecasts,
            forecast_origin_utc="2026-09-29T04:00:00Z",
            simulation_start_utc="2026-09-22T00:00:00Z",
        )


def test_forwards_scheduler_parameters(monkeypatch):
    captured = {}

    def fake_scheduler(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(
        rolling_scheduler,
        "select_task_candidate",
        fake_scheduler,
    )

    rolling_scheduler.select_task_candidate_at_origin(
        task=pd.Series({
            "start_time": 172 * 3600,
            "duration_seconds": 1800,
            "cpu_cores": 2,
            "energy_kwh": 0.01,
        }),
        rolling_forecasts=make_forecasts(),
        forecast_origin_utc="2026-09-29T04:00:00Z",
        simulation_start_utc="2026-09-22T00:00:00Z",
        cpu_capacity=8,
        max_delay_seconds=3600,
        risk_weight=0.5,
    )

    assert captured["cpu_capacity"] == 8
    assert captured["max_delay_seconds"] == 3600
    assert captured["risk_weight"] == 0.5
