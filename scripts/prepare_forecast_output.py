
from pathlib import Path
import pandas as pd


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Input and output files
INPUT_FILE = (
    PROJECT_ROOT
    / "results"
    / "forecasting"
    / "seasonal_naive_uncertainty_predictions.csv"
)

OUTPUT_DIR = PROJECT_ROOT / "results" / "forecasting"

OUTPUT_FILE = OUTPUT_DIR / "final_forecast_sample.csv"


def main():
    # Load the evaluated forecast predictions
    df = pd.read_csv(INPUT_FILE)

    # Convert timestamps to timezone-aware UTC
    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"], utc=True
    )

    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    # Provisional zero-based index.
    # Person 3 must later confirm the shared simulation timeline origin.
    df["simulation_hour"] = range(len(df))

    # These are rolling one-step-ahead predictions.
    df["forecast_horizon"] = 1

    # The forecast origin is one hour before the target interval.
    df["forecast_origin_utc"] = (
        df["timestamp_utc"] - pd.Timedelta(hours=1)
    )

    df["model_name"] = "seasonal_naive_24h"

    # Keep only the agreed integration columns
    final_df = df[
        [
            "timestamp_utc",
            "simulation_hour",
            "predicted_carbon_intensity",
            "lower_bound",
            "upper_bound",
            "forecast_origin_utc",
            "forecast_horizon",
            "model_name",
        ]
    ].copy()

    # Format timestamps consistently using ISO 8601 UTC
    final_df["timestamp_utc"] = (
        final_df["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    final_df["forecast_origin_utc"] = (
        final_df["forecast_origin_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    # Create output directory and save CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    final_df.to_csv(OUTPUT_FILE, index=False)

    print("Final forecast sample created successfully.")
    print(f"Total forecast rows: {len(final_df)}")
    print(f"Output file: {OUTPUT_FILE}")
    print("\nFirst five rows:")
    print(final_df.head().to_string(index=False))


if __name__ == "__main__":
    main()
