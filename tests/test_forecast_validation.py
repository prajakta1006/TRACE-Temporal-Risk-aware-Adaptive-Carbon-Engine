import pandas as pd
import pytest

from src.evaluation.forecast_validation import (
    evaluate_forecasts,
    task_coverage,
    validate_rolling_forecasts,
)


def _carbon(n=32):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
        "carbon_intensity": [100 + i for i in range(n)],
    })


def _forecast(carbon, origin_index=26, horizons=(1, 2, 3, 4)):
    rows = []
    for h in horizons:
        target_index = origin_index + h
        if target_index >= len(carbon):
            continue
        target = carbon.loc[target_index, "timestamp"]
        pred = carbon.loc[target_index - 24, "carbon_intensity"]
        actual = carbon.loc[target_index, "carbon_intensity"]
        rows.append({
            "forecast_origin_utc": carbon.loc[origin_index, "timestamp"],
            "timestamp_utc": target,
            "simulation_hour": target_index,
            "horizon_hours": h,
            "predicted_carbon_intensity": pred,
            "lower_bound": max(0, pred - 50),
            "upper_bound": pred + 50,
            "actual_carbon_intensity": actual,
            "covered": max(0, pred - 50) <= actual <= pred + 50,
        })
    return pd.DataFrame(rows)


def test_origin_precedes_target_and_horizon_is_exact():
    carbon = _carbon()
    frame = _forecast(carbon)
    clean = validate_rolling_forecasts(frame, carbon)
    assert ((clean.timestamp_utc - clean.forecast_origin_utc).dt.total_seconds() == clean.horizon_hours * 3600).all()
    assert (clean.forecast_origin_utc < clean.timestamp_utc).all()


def test_incorrect_horizon_or_future_origin_is_rejected():
    carbon = _carbon()
    frame = _forecast(carbon)
    frame.loc[0, "horizon_hours"] = 2
    with pytest.raises(ValueError, match="target timestamps"):
        validate_rolling_forecasts(frame, carbon)


def test_forecast_target_must_exist_in_observed_carbon():
    carbon = _carbon()
    frame = _forecast(carbon)
    frame.loc[0, "timestamp_utc"] += pd.Timedelta(days=2)
    with pytest.raises(ValueError, match="origin plus horizon"):
        validate_rolling_forecasts(frame, carbon)


def test_missing_observed_timestamp_is_not_filled():
    carbon = _carbon()
    frame = _forecast(carbon)
    missing_time = carbon.loc[27, "timestamp"]
    frame.loc[frame.timestamp_utc == missing_time, "actual_carbon_intensity"] = 127
    carbon = carbon.loc[carbon.timestamp != missing_time].reset_index(drop=True)
    with pytest.raises(ValueError, match="no observed carbon intensity"):
        validate_rolling_forecasts(frame, carbon)


def test_interval_must_be_valid_and_enclose_prediction():
    carbon = _carbon()
    frame = _forecast(carbon)
    frame.loc[0, "lower_bound"] = frame.loc[0, "predicted_carbon_intensity"] + 1
    with pytest.raises(ValueError, match="enclose"):
        validate_rolling_forecasts(frame, carbon)


def test_incomplete_forecast_coverage_is_counted_without_gap_filling():
    carbon = _carbon()
    frame = _forecast(carbon, horizons=(1, 3))
    clean = validate_rolling_forecasts(frame, carbon)
    metrics, _ = evaluate_forecasts(clean)
    assert metrics.loc[metrics.horizon_hours == 1, "prediction_count"].eq(1).all()
    assert metrics.loc[metrics.horizon_hours == 2, "prediction_count"].eq(0).all()
    assert metrics.loc[metrics.horizon_hours == 3, "prediction_count"].eq(1).all()


def test_baseline_predictions_use_only_origin_available_observations():
    carbon = _carbon()
    clean = validate_rolling_forecasts(_forecast(carbon), carbon)
    assert clean.baseline_persistence.eq(carbon.loc[26, "carbon_intensity"]).all()
    assert clean.baseline_seasonal_naive_24h.tolist() == [carbon.loc[2 + h, "carbon_intensity"] for h in range(1, 5)]


def test_persisted_model_prediction_must_not_use_future_target():
    carbon = _carbon()
    frame = _forecast(carbon)
    frame.loc[0, "predicted_carbon_intensity"] = carbon.loc[27, "carbon_intensity"]
    frame.loc[0, "lower_bound"] = frame.loc[0, "predicted_carbon_intensity"] - 50
    frame.loc[0, "upper_bound"] = frame.loc[0, "predicted_carbon_intensity"] + 50
    with pytest.raises(ValueError, match="do not reproduce"):
        validate_rolling_forecasts(frame, carbon)


def test_forecast_eligibility_uses_origin_complete_coverage(tmp_path):
    carbon = _carbon(8)
    base = carbon.timestamp.iloc[0]
    rows = []
    for h in (1, 2):
        target_index = 2 + h
        rows.append({
            "forecast_origin_utc": base + pd.Timedelta(hours=2),
            "timestamp_utc": base + pd.Timedelta(hours=target_index),
            "simulation_hour": target_index,
            "horizon_hours": h,
            "predicted_carbon_intensity": 100,
            "lower_bound": 50,
            "upper_bound": 150,
            "actual_carbon_intensity": 100,
            "covered": True,
        })
    forecasts = pd.DataFrame(rows)
    workload = tmp_path / "workload.csv"
    pd.DataFrame({
        "start_time": [3 * 3600, 3 * 3600, 0],
        "duration_seconds": [60, 3601, 60],
        "cpu_cores": [1, 1, 1],
    }).to_csv(workload, index=False)
    result = task_coverage(workload, forecasts, carbon_rows=8, chunk_size=2)
    assert result["total"] == 3
    assert result["forecast_replay_eligible"] == 2
    assert result["forecast_replay_ineligible"] == 1
    assert result["actual_carbon_baseline_covered"] == 3
    assert result["forecast_ineligible_actual_covered"] == 1
