
"""Evaluate scheduler emissions using observed carbon intensity."""

import math

import pandas as pd


def calculate_schedule_emissions(
    tasks: pd.DataFrame,
    observed_carbon: pd.DataFrame,
) -> float:
    """
    Calculate actual schedule emissions in grams of CO2 equivalent.

    Each task's energy is distributed uniformly over its execution
    duration. Carbon intensity is taken from the observed hourly data.
    """

    required_task_columns = {
        "start_time",
        "duration_seconds",
        "energy_kwh",
    }

    required_carbon_columns = {
        "simulation_hour",
        "carbon_intensity",
    }

    missing_tasks = required_task_columns - set(tasks.columns)
    missing_carbon = required_carbon_columns - set(observed_carbon.columns)

    if missing_tasks:
        raise ValueError(
            f"Tasks are missing columns: {sorted(missing_tasks)}"
        )

    if missing_carbon:
        raise ValueError(
            f"Observed carbon is missing columns: {sorted(missing_carbon)}"
        )

    carbon = observed_carbon.copy()

    for column in ["simulation_hour", "carbon_intensity"]:
        carbon[column] = pd.to_numeric(carbon[column], errors="raise")

    if not carbon[["simulation_hour", "carbon_intensity"]].map(
        math.isfinite
    ).all().all():
        raise ValueError("Observed carbon values must be finite.")

    if (carbon["carbon_intensity"] < 0).any():
        raise ValueError("Carbon intensity cannot be negative.")

    if carbon["simulation_hour"].duplicated().any():
        raise ValueError("Observed carbon hours must be unique.")

    total_emissions = 0.0

    for _, task in tasks.iterrows():
        start = float(task["start_time"])
        duration = float(task["duration_seconds"])
        energy = float(task["energy_kwh"])

        if not all(map(math.isfinite, [start, duration, energy])):
            raise ValueError("Task values must be finite.")

        if start < 0 or duration <= 0 or energy < 0:
            raise ValueError("Invalid task start, duration or energy.")

        end = start + duration

        first_hour = int(start // 3600)
        last_hour = int((end - 1e-9) // 3600)

        occupied_hours = list(range(first_hour, last_hour + 1))

        hourly_carbon = carbon[
            carbon["simulation_hour"].isin(occupied_hours)
        ].set_index("simulation_hour")

        if set(hourly_carbon.index) != set(occupied_hours):
            raise ValueError(
                "Observed carbon does not cover the complete task execution."
            )

        task_emissions = 0.0

        for hour in occupied_hours:
            overlap_start = max(start, hour * 3600)
            overlap_end = min(end, (hour + 1) * 3600)

            overlap_seconds = overlap_end - overlap_start

            energy_in_hour = energy * overlap_seconds / duration

            intensity = float(
                hourly_carbon.loc[hour, "carbon_intensity"]
            )

            task_emissions += energy_in_hour * intensity

        total_emissions += task_emissions

    return total_emissions


def compare_schedules(
    baseline_tasks: pd.DataFrame,
    trace_tasks: pd.DataFrame,
    observed_carbon: pd.DataFrame,
) -> dict:
    """Compare baseline and TRACE schedules using observed carbon."""

    baseline_emissions = calculate_schedule_emissions(
        baseline_tasks,
        observed_carbon,
    )

    trace_emissions = calculate_schedule_emissions(
        trace_tasks,
        observed_carbon,
    )

    savings = baseline_emissions - trace_emissions

    savings_percentage = (
        savings / baseline_emissions * 100
        if baseline_emissions > 0
        else 0.0
    )

    return {
        "baseline_emissions_g": baseline_emissions,
        "trace_emissions_g": trace_emissions,
        "carbon_savings_g": savings,
        "carbon_reduction_percentage": savings_percentage,
    }
