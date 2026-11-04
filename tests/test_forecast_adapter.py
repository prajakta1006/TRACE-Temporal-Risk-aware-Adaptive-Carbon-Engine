
import pandas as pd
import pytest

from src.scheduler.forecast_adapter import load_scheduler_forecasts


def test_timestamp_to_simulation_hour(tmp_path):
    forecast_file = tmp_path / "forecasts.csv"

    pd.DataFrame({
        "timestamp_utc": [
            "2026-09-22 01:00:00+00:00",
            "2026-09-22 02:00:00+00:00",
        ],
        "predicted_carbon_intensity": [500, 480],
        "upper_bound": [550, 530],
    }).to_csv(forecast_file, index=False)

    result = load_scheduler_forecasts(
        forecast_file,
        simulation_start_utc="2026-09-22 00:00:00+00:00",
    )

    assert result["simulation_hour"].tolist() == [1, 2]


def test_forecasts_are_sorted_chronologically(tmp_path):
    forecast_file = tmp_path / "forecasts.csv"

    pd.DataFrame({
        "timestamp_utc": [
            "2026-09-22 02:00:00+00:00",
            "2026-09-22 01:00:00+00:00",
        ],
        "predicted_carbon_intensity": [480, 500],
        "upper_bound": [530, 550],
    }).to_csv(forecast_file, index=False)

    result = load_scheduler_forecasts(
        forecast_file,
        simulation_start_utc="2026-09-22 00:00:00+00:00",
    )

    assert result["simulation_hour"].tolist() == [1, 2]


def test_missing_required_column(tmp_path):
    forecast_file = tmp_path / "forecasts.csv"

    pd.DataFrame({
        "timestamp_utc": ["2026-09-22 01:00:00+00:00"],
        "predicted_carbon_intensity": [500],
    }).to_csv(forecast_file, index=False)

    with pytest.raises(ValueError, match="missing"):
        load_scheduler_forecasts(
            forecast_file,
            simulation_start_utc="2026-09-22 00:00:00+00:00",
        )


def test_upper_bound_below_prediction(tmp_path):
    forecast_file = tmp_path / "forecasts.csv"

    pd.DataFrame({
        "timestamp_utc": ["2026-09-22 01:00:00+00:00"],
        "predicted_carbon_intensity": [500],
        "upper_bound": [450],
    }).to_csv(forecast_file, index=False)

    with pytest.raises(ValueError, match="Upper bounds"):
        load_scheduler_forecasts(
            forecast_file,
            simulation_start_utc="2026-09-22 00:00:00+00:00",
        )


def test_non_hourly_timestamp_rejected(tmp_path):
    forecast_file = tmp_path / "forecasts.csv"

    pd.DataFrame({
        "timestamp_utc": ["2026-09-22 01:30:00+00:00"],
        "predicted_carbon_intensity": [500],
        "upper_bound": [550],
    }).to_csv(forecast_file, index=False)

    with pytest.raises(ValueError, match="align with simulation hours"):
        load_scheduler_forecasts(
            forecast_file,
            simulation_start_utc="2026-09-22 00:00:00+00:00",
        )
