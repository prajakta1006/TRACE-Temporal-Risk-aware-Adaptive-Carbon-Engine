
"""Adapt Person 2's forecast output for the TRACE scheduler."""

from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "timestamp_utc",
    "predicted_carbon_intensity",
    "upper_bound",
}


def load_scheduler_forecasts(
    csv_path: str | Path,
    simulation_start_utc: str,
) -> pd.DataFrame:
    """Load forecasts and map UTC timestamps to simulation hours."""

    forecasts = pd.read_csv(csv_path)

    missing = REQUIRED_COLUMNS - set(forecasts.columns)
    if missing:
        raise ValueError(
            f"Forecast file is missing columns: {sorted(missing)}"
        )

    forecasts["timestamp_utc"] = pd.to_datetime(
        forecasts["timestamp_utc"], utc=True, errors="raise"
    )

    start_timestamp = pd.to_datetime(
        simulation_start_utc, utc=True, errors="raise"
    )

    if forecasts["timestamp_utc"].isna().any():
        raise ValueError("Forecast timestamps cannot be missing.")

    # Rolling forecasts contain multiple origins.
    is_rolling = "forecast_origin_utc" in forecasts.columns

    if is_rolling:
        forecasts["forecast_origin_utc"] = pd.to_datetime(
            forecasts["forecast_origin_utc"],
            utc=True,
            errors="raise",
        )

        if forecasts["forecast_origin_utc"].isna().any():
            raise ValueError("Forecast origins cannot be missing.")

        if forecasts.duplicated(
            ["forecast_origin_utc", "timestamp_utc"]
        ).any():
            raise ValueError(
                "Duplicate target timestamps found within a forecast origin."
            )

        if "horizon_hours" not in forecasts.columns:
            raise ValueError(
                "Rolling forecasts must contain horizon_hours."
            )

        forecasts["horizon_hours"] = pd.to_numeric(
            forecasts["horizon_hours"], errors="raise"
        )

        if (forecasts["horizon_hours"] < 1).any():
            raise ValueError("Forecast horizons must be positive.")

    for column in [
        "predicted_carbon_intensity",
        "upper_bound",
    ]:
        forecasts[column] = pd.to_numeric(
            forecasts[column], errors="raise"
        )

    if forecasts[
        ["predicted_carbon_intensity", "upper_bound"]
    ].isna().any().any():
        raise ValueError("Forecast values cannot be missing.")

    if (forecasts["predicted_carbon_intensity"] < 0).any():
        raise ValueError("Predicted carbon intensity cannot be negative.")

    if (forecasts["upper_bound"] < forecasts[
        "predicted_carbon_intensity"
    ]).any():
        raise ValueError(
            "Upper bounds cannot be below predicted carbon intensity."
        )

    elapsed_seconds = (
        forecasts["timestamp_utc"] - start_timestamp
    ).dt.total_seconds()

    if (elapsed_seconds < 0).any():
        raise ValueError(
            "Forecast timestamps cannot precede simulation start."
        )

    if (elapsed_seconds % 3600 != 0).any():
        raise ValueError(
            "Forecast timestamps must align with simulation hours."
        )

    forecasts["simulation_hour"] = (
        elapsed_seconds // 3600
    ).astype(int)

    if not is_rolling and forecasts["timestamp_utc"].duplicated().any():
        raise ValueError("Forecast timestamps must be unique.")

    sort_columns = (
        ["forecast_origin_utc", "horizon_hours"]
        if is_rolling
        else ["timestamp_utc"]
    )

    return forecasts.sort_values(sort_columns).reset_index(drop=True)


def select_forecast_origin(
    forecasts: pd.DataFrame,
    forecast_origin_utc: str,
) -> pd.DataFrame:
    """Return only the predictions belonging to one rolling origin."""

    if "forecast_origin_utc" not in forecasts.columns:
        raise ValueError(
            "This forecast file does not contain rolling forecast origins."
        )

    origin = pd.to_datetime(
        forecast_origin_utc, utc=True, errors="raise"
    )

    selected = forecasts.loc[
        forecasts["forecast_origin_utc"] == origin
    ].copy()

    if selected.empty:
        raise ValueError(
            f"No forecasts found for origin {origin}."
        )

    selected = selected.sort_values("horizon_hours").reset_index(drop=True)

    if selected["horizon_hours"].duplicated().any():
        raise ValueError("Duplicate forecast horizons found for this origin.")

    return selected
