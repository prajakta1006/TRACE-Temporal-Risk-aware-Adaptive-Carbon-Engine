
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from src.data.prepare_carbon import load_carbon


def create_features(data):
    """Create features using historical observations only."""

    result = data.copy()

    result["hour"] = result["timestamp"].dt.hour
    result["lag_1"] = result["carbon_intensity"].shift(1)
    result["lag_2"] = result["carbon_intensity"].shift(2)
    result["lag_24"] = result["carbon_intensity"].shift(24)

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

    data = load_carbon(str(input_file))
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)

    featured_data = create_features(data)

    features = [
        "hour",
        "lag_1",
        "lag_2",
        "lag_24",
        "rolling_mean_3",
    ]

    # Preserve the original chronological 80:20 split
    split_timestamp = data["timestamp"].iloc[int(len(data) * 0.8)]

    train = featured_data[
        featured_data["timestamp"] < split_timestamp
    ].copy()

    test = featured_data[
        featured_data["timestamp"] >= split_timestamp
    ].copy()

    X_train = train[features]
    y_train = train["carbon_intensity"]
    X_test = test[features]

    model = HistGradientBoostingRegressor(
        max_iter=100,
        learning_rate=0.05,
        max_leaf_nodes=7,
        l2_regularization=1.0,
        random_state=42,
    )

    model.fit(X_train, y_train)

    test["predicted_carbon_intensity"] = model.predict(X_test)

    output_file = output_dir / "hist_gradient_boosting_predictions.csv"

    test[
        [
            "timestamp",
            "carbon_intensity",
            "predicted_carbon_intensity",
        ]
    ].to_csv(output_file, index=False)

    print("\n--- HIST GRADIENT BOOSTING FORECAST ---")
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
