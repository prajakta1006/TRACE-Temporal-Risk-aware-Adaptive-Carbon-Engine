
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

    # Load the original chronological observations
    data = load_carbon(str(input_file))

    # Use the first 80% for training/history and final 20% for testing
    split_index = int(len(data) * 0.8)

    # One-step-ahead persistence:
    # predict each hour using the immediately preceding observed hour
    test_actual = data["carbon_intensity"].iloc[split_index:]

    test_predicted = (
        data["carbon_intensity"]
        .shift(1)
        .iloc[split_index:]
    )

    results = calculate_metrics(test_actual, test_predicted)

    # Display evaluation results
    print("\n--- PERSISTENCE BASELINE: CHRONOLOGICAL TEST ---")
    print("Total observations:", len(data))
    print("Training/history observations:", split_index)
    print("Test observations:", len(test_actual))
    print("\nEvaluation metrics:")

    for metric, value in results.items():
        print(f"{metric}: {value:.4f}")

    # Save evaluation metrics
    output_dir = project_root / "results" / "forecasting"
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_file = output_dir / "persistence_metrics.csv"

    pd.DataFrame([results]).to_csv(metrics_file, index=False)

    print("\nMetrics saved to:", metrics_file)


if __name__ == "__main__":
    main()
