
from pathlib import Path

import pandas as pd

from src.data.prepare_carbon import load_carbon
from src.evaluation.metrics import calculate_metrics


def main():
    project_root = Path(__file__).resolve().parents[2]

    input_file = (
        project_root
        / "data"
        / "raw"
        / "carbon"
        / "india_west_carbon_intensity.csv"
    )

    output_dir = project_root / "results" / "forecasting"

    # Load original chronological observations
    data = load_carbon(str(input_file))

    split_index = int(len(data) * 0.8)

    # Actual values for the common test period
    test_actual = data["carbon_intensity"].iloc[split_index:]

    # Persistence predictions: previous hour
    persistence_predictions = (
        data["carbon_intensity"]
        .shift(1)
        .iloc[split_index:]
    )

    # Seasonal naive predictions: previous day, same hour
    seasonal_file = output_dir / "seasonal_naive_predictions.csv"
    seasonal_data = pd.read_csv(seasonal_file)

    seasonal_predictions = seasonal_data[
        "predicted_carbon_intensity"
    ]

    # Calculate metrics
    persistence_metrics = calculate_metrics(
        test_actual,
        persistence_predictions,
    )

    seasonal_metrics = calculate_metrics(
        test_actual,
        seasonal_predictions,
    )

    # Create comparison table
    comparison = pd.DataFrame(
        [
            {"Model": "Persistence", **persistence_metrics},
            {"Model": "Seasonal Naive (24h)", **seasonal_metrics},
        ]
    )

    print("\n--- FORECASTING MODEL COMPARISON ---")
    print(comparison.to_string(index=False))

    # Save comparison
    comparison_file = output_dir / "baseline_comparison.csv"
    comparison.to_csv(comparison_file, index=False)

    print("\nComparison saved to:", comparison_file)


if __name__ == "__main__":
    main()
