
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
    """
    Load forecast predictions and map UTC timestamps to simulation hours.

    simulation_start_utc must be the UTC timestamp corresponding
    to simulation second zero in the workload timeline.
    """

    forecasts = pd.read_csv(csv_path)

    missing = REQUIRED_COLUMNS - set(forecasts.columns)
    if missing:
        raise ValueError(
            f"Forecast file is missing columns: {sorted(missing)}"
        )

    forecasts["timestamp_utc"] = pd.to_datetime(
        forecasts["timestamp_utc"],
        utc=True,
        errors="raise",
    )

    start_timestamp = pd.to_datetime(
        simulation_start_utc,
        utc=True,
        errors="raise",
    )

    if forecasts["timestamp_utc"].isna().any():
        raise ValueError("Forecast timestamps cannot be missing.")

    for column in [
        "predicted_carbon_intensity",
        "upper_bound",
    ]:
        forecasts[column] = pd.to_numeric(
            forecasts[column],
            errors="raise",
        )

    if forecasts[
        ["predicted_carbon_intensity", "upper_bound"]
    ].isna().any().any():
        raise ValueError("Forecast values cannot be missing.")

    if (
        forecasts["predicted_carbon_intensity"] < 0
    ).any():
        raise ValueError("Predicted carbon intensity cannot be negative.")

    if (
        forecasts["upper_bound"]
        < forecasts["predicted_carbon_intensity"]
    ).any():
        raise ValueError(
            "Upper bounds cannot be below predicted carbon intensity."
        )

    forecasts = forecasts.sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)

    if forecasts["timestamp_utc"].duplicated().any():
        raise ValueError("Forecast timestamps must be unique.")

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

    return forecasts
