
from pathlib import Path

import pandas as pd

from src.data.prepare_carbon import load_carbon


def seasonal_naive_forecast(data: pd.DataFrame) -> pd.DataFrame:
    """
    Predict carbon intensity using the value
    from 24 hours earlier.
    """

    result = data.copy()

    result["predicted_carbon_intensity"] = (
        result["carbon_intensity"].shift(24)
    )

    return result


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
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_carbon(str(input_file))

    forecasts = seasonal_naive_forecast(data)

    # Evaluate on exactly the same chronological test period
    split_index = int(len(data) * 0.8)
    test = forecasts.iloc[split_index:].copy()

    test = test.dropna(
        subset=["predicted_carbon_intensity"]
    )

    output_file = output_dir / "seasonal_naive_predictions.csv"
    test.to_csv(output_file, index=False)

    print("\n--- SEASONAL NAIVE FORECAST ---")
    print("Total observations:", len(data))
    print("Training/history observations:", split_index)
    print("Test predictions:", len(test))

    print("\nFirst five test predictions:")
    print(
        test[
            [
                "timestamp",
                "carbon_intensity",
                "predicted_carbon_intensity",
            ]
        ].head()
    )

    print("\nPredictions saved to:", output_file)


if __name__ == "__main__":
    main()
