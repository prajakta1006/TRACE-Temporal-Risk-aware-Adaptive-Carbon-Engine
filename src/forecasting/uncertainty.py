
from pathlib import Path
import math

import pandas as pd

from src.data.prepare_carbon import load_carbon


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CARBON_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "carbon"
    / "india_west_carbon_intensity.csv"
)

OUTPUT_DIR = PROJECT_ROOT / "results" / "forecasting"


def main():
    # Load and prepare carbon intensity data
    df = load_carbon(CARBON_FILE)

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Chronological split: 60% history, 20% calibration, 20% testing
    n = len(df)
    train_end = int(n * 0.60)
    calibration_end = int(n * 0.80)

    # Seasonal naive prediction: use the previous day's same hour
    df["prediction"] = df["carbon_intensity"].shift(24)

    # Calibration period
    calibration = df.iloc[train_end:calibration_end].copy()
    calibration = calibration.dropna(subset=["prediction"])

    calibration["absolute_error"] = (
        calibration["carbon_intensity"] - calibration["prediction"]
    ).abs()

    # Calculate finite-sample 90% conformal-style error threshold
    alpha = 0.10
    calibration_errors = calibration["absolute_error"].sort_values().to_numpy()

    n_cal = len(calibration_errors)
    rank = math.ceil((n_cal + 1) * (1 - alpha))

    if rank > n_cal:
        raise ValueError("Not enough calibration observations.")

    error_threshold = calibration_errors[rank - 1]

    # Final test period
    test = df.iloc[calibration_end:].copy()
    test = test.dropna(subset=["prediction"])

    test["lower_bound"] = (
        test["prediction"] - error_threshold
    ).clip(lower=0)

    test["upper_bound"] = (
        test["prediction"] + error_threshold
    )

    # Evaluate prediction intervals
    test["covered"] = (
        (test["carbon_intensity"] >= test["lower_bound"])
        & (test["carbon_intensity"] <= test["upper_bound"])
    )

    coverage = test["covered"].mean() * 100

    average_width = (
        test["upper_bound"] - test["lower_bound"]
    ).mean()

    # Save prediction intervals
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    predictions = test[
        [
            "timestamp",
            "carbon_intensity",
            "prediction",
            "lower_bound",
            "upper_bound",
            "covered",
        ]
    ].rename(
        columns={
            "timestamp": "timestamp_utc",
            "carbon_intensity": "actual_carbon_intensity",
            "prediction": "predicted_carbon_intensity",
        }
    )

    predictions.to_csv(
        OUTPUT_DIR / "seasonal_naive_uncertainty_predictions.csv",
        index=False,
    )

    # Save evaluation metrics
    metrics = pd.DataFrame(
        [
            {
                "confidence_level": 90,
                "calibration_samples": n_cal,
                "test_samples": len(test),
                "calibration_error_threshold": error_threshold,
                "interval_coverage_percent": coverage,
                "average_interval_width": average_width,
            }
        ]
    )

    metrics.to_csv(
        OUTPUT_DIR / "uncertainty_metrics.csv",
        index=False,
    )

    print("Uncertainty estimation completed.")
    print(f"Calibration samples: {n_cal}")
    print(f"Test samples: {len(test)}")
    print(f"90% error threshold: {error_threshold:.2f}")
    print(f"Test interval coverage: {coverage:.2f}%")
    print(f"Average interval width: {average_width:.2f}")
    print(f"Saved outputs to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
