
"""Main scheduling decision engine for TRACE."""

import pandas as pd

from src.scheduler.carbon_benefit import calculate_carbon_benefit
from src.scheduler.candidate_selection import generate_candidate_starts
from src.scheduler.constraints import validate_schedule_capacity


def select_task_candidate(
    task: pd.Series,
    forecasts: pd.DataFrame,
    current_time: float,
    scheduled_tasks: pd.DataFrame | None = None,
    cpu_capacity: float = 8.0,
    forecast_hours: int = 4,
    max_delay_seconds: float = 3600.0,
    risk_weight: float = 0.5,
) -> dict | None:
    """
    Select the feasible candidate with the highest risk-adjusted savings.

    The task's original start hour provides the baseline carbon intensity.
    Candidate and baseline uncertainty are both included in the
    risk-adjusted savings calculation.

    Returns None when no candidate provides positive risk-adjusted savings.
    """

    required_forecast_columns = {
        "simulation_hour",
        "predicted_carbon_intensity",
        "upper_bound",
    }

    missing = required_forecast_columns - set(forecasts.columns)

    if missing:
        raise ValueError(
            f"Forecast data is missing columns: {sorted(missing)}"
        )

    required_task_columns = {
        "start_time",
        "duration_seconds",
        "cpu_cores",
        "energy_kwh",
    }

    missing = required_task_columns - set(task.index)

    if missing:
        raise ValueError(
            f"Task is missing columns: {sorted(missing)}"
        )

    if not 0.0 <= risk_weight <= 1.0:
        raise ValueError("risk_weight must be between 0 and 1.")

    forecast_data = forecasts.copy()

    numeric_columns = [
        "simulation_hour",
        "predicted_carbon_intensity",
        "upper_bound",
    ]

    for column in numeric_columns:
        forecast_data[column] = pd.to_numeric(
            forecast_data[column], errors="raise"
        )

    if forecast_data[numeric_columns].isna().any().any():
        raise ValueError("Forecast values cannot be missing.")

    if not forecast_data[numeric_columns].map(
        lambda value: value >= 0
    ).all().all():
        raise ValueError("Forecast values must be non-negative.")

    if (
        forecast_data["upper_bound"]
        < forecast_data["predicted_carbon_intensity"]
    ).any():
        raise ValueError("Forecast upper bounds cannot be below predictions.")

    if forecast_data["simulation_hour"].duplicated().any():
        raise ValueError("Forecast simulation hours must be unique.")

    if scheduled_tasks is None:
        scheduled_tasks = pd.DataFrame(
            columns=[
                "start_time",
                "duration_seconds",
                "cpu_cores",
            ]
        )

    baseline_hour = int(float(task["start_time"]) // 3600)

    baseline_rows = forecast_data[
        forecast_data["simulation_hour"] == baseline_hour
    ]

    if baseline_rows.empty:
        raise ValueError(
            "No forecast is available for the task's original execution hour."
        )

    baseline = baseline_rows.iloc[0]

    candidates = generate_candidate_starts(
        task=task,
        current_time=current_time,
        forecast_hours=forecast_hours,
        max_delay_seconds=max_delay_seconds,
    )

    best_candidate = None

    for candidate_start in candidates:

        candidate_end = candidate_start + float(
            task["duration_seconds"]
        )

        # Check that the candidate is within the forecast horizon.
        first_hour = int(candidate_start // 3600)
        last_hour = int(
            (candidate_end - 1e-9) // 3600
        )

        occupied_hours = range(first_hour, last_hour + 1)

        candidate_forecasts = forecast_data[
            forecast_data["simulation_hour"].isin(occupied_hours)
        ]

        if set(candidate_forecasts["simulation_hour"]) != set(
            occupied_hours
        ):
            continue

        # For tasks crossing hours, use an energy-weighted
        # average of the hourly forecast values.
        hourly_weights = []

        for hour in occupied_hours:
            overlap_start = max(candidate_start, hour * 3600)
            overlap_end = min(candidate_end, (hour + 1) * 3600)
            hourly_weights.append(overlap_end - overlap_start)

        weights = pd.Series(
            hourly_weights,
            index=list(occupied_hours),
            dtype=float,
        )

        candidate_forecasts = candidate_forecasts.set_index(
            "simulation_hour"
        ).loc[list(occupied_hours)]

        total_duration = sum(hourly_weights)

        candidate_predicted = (
            candidate_forecasts["predicted_carbon_intensity"]
            .mul(weights).sum() / total_duration
        )

        candidate_upper = (
            candidate_forecasts["upper_bound"]
            .mul(weights).sum() / total_duration
        )

        # Calculate risk-adjusted carbon savings.
        benefit = calculate_carbon_benefit(
            energy_kwh=float(task["energy_kwh"]),
            baseline_predicted=float(
                baseline["predicted_carbon_intensity"]
            ),
            candidate_predicted=float(candidate_predicted),
            baseline_upper=float(baseline["upper_bound"]),
            candidate_upper=float(candidate_upper),
            risk_weight=risk_weight,
        )

        # Ignore candidates without positive risk-adjusted savings.
        if benefit["risk_adjusted_savings_g"] <= 0:
            continue

        # Check the proposed schedule against existing assignments.
        proposed_task = pd.DataFrame([{
            "start_time": candidate_start,
            "duration_seconds": float(task["duration_seconds"]),
            "cpu_cores": float(task["cpu_cores"]),
        }])

        existing = scheduled_tasks[
            ["start_time", "duration_seconds", "cpu_cores"]
        ]

        if existing.empty:
            proposed_schedule = proposed_task.copy()
        else:
            proposed_schedule = pd.concat(
                [existing, proposed_task],
                ignore_index=True,
            )

        try:
            validate_schedule_capacity(
                proposed_schedule,
                cpu_capacity=cpu_capacity,
            )
        except ValueError:
            continue

        result = {
            "start_time": candidate_start,
            "end_time": candidate_end,
            "risk_adjusted_savings_g": benefit[
                "risk_adjusted_savings_g"
            ],
            "expected_savings_g": benefit["expected_savings_g"],
            "uncertainty_penalty_g": benefit["uncertainty_penalty_g"],
            "candidate_predicted_carbon": float(candidate_predicted),
            "candidate_upper_bound": float(candidate_upper),
        }

        if (
            best_candidate is None
            or result["risk_adjusted_savings_g"]
            > best_candidate["risk_adjusted_savings_g"]
        ):
            best_candidate = result

    return best_candidate
