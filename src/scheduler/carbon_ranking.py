
"""Risk-adjusted ranking of candidate scheduling hours."""

import pandas as pd


REQUIRED_COLUMNS = {
    "simulation_hour",
    "predicted_carbon_intensity",
    "upper_bound",
}


def rank_carbon_hours(
    forecasts: pd.DataFrame,
    risk_weight: float = 0.5,
) -> pd.DataFrame:
    """Rank forecast hours using predicted carbon and uncertainty.

    A larger risk_weight gives more importance to the upper uncertainty
    bound. The score is:

        predicted + risk_weight * (upper_bound - predicted)

    Lower scores are preferred.
    """
    if not 0.0 <= risk_weight <= 1.0:
        raise ValueError("risk_weight must be between 0 and 1.")

    missing = REQUIRED_COLUMNS - set(forecasts.columns)
    if missing:
        raise ValueError(
            f"Forecast data is missing columns: {sorted(missing)}"
        )

    result = forecasts.copy()

    numeric_columns = [
        "simulation_hour",
        "predicted_carbon_intensity",
        "upper_bound",
    ]

    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="raise")

    if result[numeric_columns].isna().any().any():
        raise ValueError("Forecast values cannot be missing.")

    if (result["predicted_carbon_intensity"] < 0).any():
        raise ValueError("Predicted carbon intensity cannot be negative.")

    if (result["upper_bound"] < result["predicted_carbon_intensity"]).any():
        raise ValueError(
            "upper_bound cannot be below predicted_carbon_intensity."
        )

    if result["simulation_hour"].duplicated().any():
        raise ValueError("simulation_hour values must be unique.")

    result["risk_adjusted_carbon"] = (
        result["predicted_carbon_intensity"]
        + risk_weight
        * (
            result["upper_bound"]
            - result["predicted_carbon_intensity"]
        )
    )

    result = result.sort_values(
        ["risk_adjusted_carbon", "simulation_hour"]
    ).reset_index(drop=True)

    result["carbon_rank"] = range(1, len(result) + 1)

    return result
