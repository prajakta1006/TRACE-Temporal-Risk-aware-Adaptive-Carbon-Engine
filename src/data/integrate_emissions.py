
"""Combine workload energy estimates with hourly carbon intensity."""

import pandas as pd


def calculate_emissions(
    workload: pd.DataFrame,
    carbon: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate estimated emissions using simulation-hour mapping.

    Workload start_time values are treated as relative simulation seconds.
    Carbon records are assigned to simulation hours in chronological order.
    This is a simulation assumption, not a real-world timestamp match.
    """
    required_workload = {
        "job_name",
        "task_name",
        "start_time",
        "duration_seconds",
        "cpu_cores",
        "energy_kwh",
    }
    required_carbon = {"timestamp", "carbon_intensity"}

    missing_workload = required_workload - set(workload.columns)
    missing_carbon = required_carbon - set(carbon.columns)

    if missing_workload:
        raise ValueError(
            f"Workload is missing columns: {sorted(missing_workload)}"
        )

    if missing_carbon:
        raise ValueError(
            f"Carbon data is missing columns: {sorted(missing_carbon)}"
        )

    if workload.empty or carbon.empty:
        raise ValueError("Workload and carbon data must not be empty")

    tasks = workload.copy()
    carbon_hours = carbon.copy()

    tasks["start_time"] = pd.to_numeric(
        tasks["start_time"], errors="raise"
    )
    tasks["energy_kwh"] = pd.to_numeric(
        tasks["energy_kwh"], errors="raise"
    )
    carbon_hours["timestamp"] = pd.to_datetime(
        carbon_hours["timestamp"], utc=True, errors="raise"
    )
    carbon_hours["carbon_intensity"] = pd.to_numeric(
        carbon_hours["carbon_intensity"], errors="raise"
    )

    if tasks[["start_time", "energy_kwh"]].isna().any().any():
        raise ValueError("Workload contains missing start times or energy")

    if carbon_hours[
        ["timestamp", "carbon_intensity"]
    ].isna().any().any():
        raise ValueError(
            "Carbon data contains missing timestamps or intensities"
        )

    if (tasks["energy_kwh"] < 0).any():
        raise ValueError("Energy values cannot be negative")

    if (carbon_hours["carbon_intensity"] < 0).any():
        raise ValueError("Carbon intensity cannot be negative")

    carbon_hours = carbon_hours.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    if carbon_hours["timestamp"].duplicated().any():
        raise ValueError("Carbon data contains duplicate timestamps")

    # Map relative workload start seconds to simulation hours.
    tasks["simulation_hour"] = (
        tasks["start_time"] // 3600
    ).astype("int64")

    # Assign carbon records to simulation hours in chronological order.
    carbon_hours["simulation_hour"] = range(len(carbon_hours))

    result = tasks.merge(
        carbon_hours[
            ["simulation_hour", "timestamp", "carbon_intensity"]
        ],
        on="simulation_hour",
        how="left",
        validate="many_to_one",
    )

    # Do not silently calculate emissions when carbon data is missing.
    if result["carbon_intensity"].isna().any():
        missing_hours = sorted(
            result.loc[
                result["carbon_intensity"].isna(),
                "simulation_hour",
            ].unique()
        )
        raise ValueError(
            "No carbon data available for simulation hours: "
            f"{missing_hours[:10]}"
        )

    result["co2_g"] = (
        result["energy_kwh"] * result["carbon_intensity"]
    )

    return result
