
"""Generate rolling four-hour Seasonal Naive carbon forecasts.

This module performs a historical rolling replay. At each forecast origin,
it predicts the next four hours using observations from 24 hours earlier.

Uncertainty is calibrated on the earlier calibration period, not on the
rolling forecast evaluation period.
"""

from pathlib import Path
import math

import pandas as pd

from src.data.prepare_carbon import load_carbon


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CARBON_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "carbon"
    / "india_west_carbon_intensity.csv"
)

OUTPUT_DIR = PROJECT_ROOT / "results" / "forecasting"
OUTPUT_FILE = OUTPUT_DIR / "rolling_seasonal_naive_forecasts.csv"

FORECAST_HORIZON = 4
SEASONAL_PERIOD = 24
ALPHA = 0.10


def calibrate_error_threshold(
    df: pd.DataFrame,
    alpha: float = ALPHA,
) -> tuple[float, int]:
    """Calculate the conformal-style error threshold from calibration data."""

    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1.")

    n = len(df)
    train_end = int(n * 0.60)
    calibration_end = int(n * 0.80)

    calibration = df.iloc[train_end:calibration_end].copy()

    calibration["prediction"] = (
        calibration["carbon_intensity"].shift(SEASONAL_PERIOD)
    )

    # The shift above is relative to the calibration subset. Use the
    # corresponding observations from the complete chronological dataset.
    calibration_indices = calibration.index
    prediction_indices = calibration_indices - SEASONAL_PERIOD

    valid = prediction_indices >= 0
    calibration = calibration.loc[valid].copy()
    prediction_indices = prediction_indices[valid]

    calibration_predictions = (
        df.loc[prediction_indices, "carbon_intensity"].to_numpy()
    )

    errors = (
        calibration["carbon_intensity"].to_numpy()
        - calibration_predictions
    )
    errors = pd.Series(errors).abs().sort_values().to_numpy()

    n_cal = len(errors)
    rank = math.ceil((n_cal + 1) * (1 - alpha))

    if n_cal == 0 or rank > n_cal:
        raise ValueError("Not enough calibration observations.")

    return float(errors[rank - 1]), n_cal


def generate_rolling_forecasts(
    df: pd.DataFrame,
    horizon: int = FORECAST_HORIZON,
    alpha: float = ALPHA,
) -> pd.DataFrame:
    """Generate rolling forecasts using only information available at origin."""

    if horizon < 1 or horizon >= SEASONAL_PERIOD:
        raise ValueError("horizon must be between 1 and 23 hours.")

    required = {"timestamp", "carbon_intensity"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df = df.sort_values("timestamp").reset_index(drop=True).copy()

    if df[["timestamp", "carbon_intensity"]].isna().any().any():
        raise ValueError("Carbon data contains missing values.")

    intervals = df["timestamp"].diff().dropna()
    if not (intervals == pd.Timedelta(hours=1)).all():
        raise ValueError("Rolling forecasts require continuous hourly data.")

    if (df["carbon_intensity"] < 0).any():
        raise ValueError("Carbon intensity cannot be negative.")

    error_threshold, calibration_samples = calibrate_error_threshold(
        df, alpha
    )

    n = len(df)
    train_end = int(n * 0.60)
    calibration_end = int(n * 0.80)

    records = []

    # Start after calibration so no calibration errors from the future
    # are used to evaluate earlier forecast origins.
    for origin_index in range(calibration_end, n - horizon):

        origin_time = df.loc[origin_index, "timestamp"]

        for lead in range(1, horizon + 1):
            target_index = origin_index + lead
            seasonal_index = target_index - SEASONAL_PERIOD

            # Seasonal observation must already be available at the origin.
            if seasonal_index > origin_index:
                continue

            predicted = float(
                df.loc[seasonal_index, "carbon_intensity"]
            )
            actual = float(
                df.loc[target_index, "carbon_intensity"]
            )

            lower = max(0.0, predicted - error_threshold)
            upper = predicted + error_threshold

            records.append(
                {
                    "forecast_origin_utc": origin_time,
                    "timestamp_utc": df.loc[target_index, "timestamp"],
                    "simulation_hour": target_index,
                    "horizon_hours": lead,
                    "predicted_carbon_intensity": predicted,
                    "lower_bound": lower,
                    "upper_bound": upper,
                    "actual_carbon_intensity": actual,
                    "covered": lower <= actual <= upper,
                }
            )

    forecasts = pd.DataFrame(records)

    if forecasts.empty:
        raise ValueError(
            "No rolling forecasts generated. More carbon observations "
            "may be required."
        )

    forecasts.attrs["calibration_samples"] = calibration_samples
    forecasts.attrs["error_threshold"] = error_threshold
    forecasts.attrs["train_end"] = train_end
    forecasts.attrs["calibration_end"] = calibration_end

    return forecasts


def main():
    df = load_carbon(CARBON_FILE)

    forecasts = generate_rolling_forecasts(df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(OUTPUT_FILE, index=False)

    print("\nRolling forecast generation completed.")
    print(f"Forecast horizon: {FORECAST_HORIZON} hours")
    print(f"Forecast rows: {len(forecasts)}")
    print(
        "Forecast origins:",
        forecasts["forecast_origin_utc"].nunique(),
    )
    print(
        "Calibration samples:",
        forecasts.attrs["calibration_samples"],
    )
    print(
        "90% error threshold:",
        f"{forecasts.attrs['error_threshold']:.2f}",
    )

    print("\nCoverage by forecast horizon:")
    coverage = forecasts.groupby("horizon_hours")["covered"].mean() * 100
    print(coverage.round(2).to_string())

    print(f"\nSaved forecasts to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
