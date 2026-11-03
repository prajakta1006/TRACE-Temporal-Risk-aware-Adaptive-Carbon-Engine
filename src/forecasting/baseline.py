from pathlib import Path

import pandas as pd


def persistence_forecast(data: pd.DataFrame) -> pd.DataFrame:
    """
    Predict the next hour's carbon intensity
    using the current hour's observed intensity.
    """

    result = data.copy()

    result["predicted_carbon_intensity"] = (
        result["carbon_intensity"].shift(1)
    )

    return result.dropna().reset_index(drop=True)


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

    # Load carbon-intensity observations
    from src.data.prepare_carbon import load_carbon

    data = load_carbon(str(input_file))

    # Generate persistence predictions
    forecasts = persistence_forecast(data)

    # Save predictions
    output_file = output_dir / "persistence_predictions.csv"
    forecasts.to_csv(output_file, index=False)

    print("\n--- PERSISTENCE BASELINE ---")
    print("Observations:", len(data))
    print("Predictions:", len(forecasts))
    print("\nFirst five predictions:")
    print(
        forecasts[
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