
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from src.data.prepare_carbon import load_carbon


def create_features(data):
    """Create features using only past carbon-intensity observations."""

    result = data.copy()

    result["hour"] = result["timestamp"].dt.hour
    result["lag_1"] = result["carbon_intensity"].shift(1)
    result["lag_2"] = result["carbon_intensity"].shift(2)
    result["lag_24"] = result["carbon_intensity"].shift(24)

    # Shift first, then calculate the rolling mean.
    result["rolling_mean_3"] = (
        result["carbon_intensity"]
        .shift(1)
        .rolling(window=3)
        .mean()
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

    # Load observations
    data = load_carbon(str(input_file))
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)

    # Create historical features
    featured_data = create_features(data)

    features = [
        "hour",
        "lag_1",
        "lag_2",
        "lag_24",
        "rolling_mean_3",
    ]

    target = "carbon_intensity"

    # Chronological split based on original dataset
    split_timestamp = data["timestamp"].iloc[int(len(data) * 0.8)]

    train = featured_data[
        featured_data["timestamp"] < split_timestamp
    ].copy()

    test = featured_data[
        featured_data["timestamp"] >= split_timestamp
    ].copy()

    X_train = train[features]
    y_train = train[target]

    X_test = test[features]

    # Train Random Forest
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=5,
        min_samples_leaf=2,
        random_state=42,
    )

    model.fit(X_train, y_train)

    # Generate test predictions
    test["predicted_carbon_intensity"] = model.predict(X_test)

    # Save predictions
    output_file = output_dir / "random_forest_predictions.csv"

    test[
        [
            "timestamp",
            "carbon_intensity",
            "predicted_carbon_intensity",
        ]
    ].to_csv(output_file, index=False)

    print("\n--- RANDOM FOREST FORECAST ---")
    print("Training rows:", len(train))
    print("Test predictions:", len(test))
    print("Features:", features)

    print("\nFirst five predictions:")
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
