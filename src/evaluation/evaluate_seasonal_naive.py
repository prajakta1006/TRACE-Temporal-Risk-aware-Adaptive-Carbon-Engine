
from pathlib import Path

import pandas as pd

from src.evaluation.metrics import calculate_metrics


def main():
    project_root = Path(__file__).resolve().parents[2]

    prediction_file = (
        project_root
        / "results"
        / "forecasting"
        / "seasonal_naive_predictions.csv"
    )

    predictions = pd.read_csv(prediction_file)

    results = calculate_metrics(
        predictions["carbon_intensity"],
        predictions["predicted_carbon_intensity"],
    )

    print("\n--- SEASONAL NAIVE EVALUATION ---")
    print("Test observations:", len(predictions))

    for metric, value in results.items():
        print(f"{metric}: {value:.4f}")

    output_file = (
        project_root
        / "results"
        / "forecasting"
        / "seasonal_naive_metrics.csv"
    )

    pd.DataFrame([results]).to_csv(output_file, index=False)

    print("\nMetrics saved to:", output_file)


if __name__ == "__main__":
    main()
