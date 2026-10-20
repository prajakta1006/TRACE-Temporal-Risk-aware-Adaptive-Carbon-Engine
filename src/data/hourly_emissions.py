
"""Vectorized allocation of task energy across occupied hours."""

import numpy as np
import pandas as pd


def allocate_hourly_emissions(
    workload: pd.DataFrame,
    carbon: pd.DataFrame,
) -> pd.DataFrame:
    """Allocate task energy proportionally across occupied simulation hours."""
    workload_required = {
        "job_name", "task_name", "start_time",
        "duration_seconds", "energy_kwh",
    }
    carbon_required = {"timestamp", "carbon_intensity"}

    missing_workload = workload_required - set(workload.columns)
    missing_carbon = carbon_required - set(carbon.columns)

    if missing_workload:
        raise ValueError(f"Missing workload columns: {sorted(missing_workload)}")
    if missing_carbon:
        raise ValueError(f"Missing carbon columns: {sorted(missing_carbon)}")

    tasks = workload.copy()
    factors = carbon.copy()

    numeric_cols = ["start_time", "duration_seconds", "energy_kwh"]
    for col in numeric_cols:
        tasks[col] = pd.to_numeric(tasks[col], errors="raise")

    factors["timestamp"] = pd.to_datetime(
        factors["timestamp"], utc=True, errors="raise"
    )
    factors["carbon_intensity"] = pd.to_numeric(
        factors["carbon_intensity"], errors="raise"
    )

    if tasks[numeric_cols].isna().any().any():
        raise ValueError("Workload timing and energy values cannot be missing.")
    if factors[["timestamp", "carbon_intensity"]].isna().any().any():
        raise ValueError("Carbon timestamps and intensities cannot be missing.")
    if (tasks["start_time"] < 0).any():
        raise ValueError("start_time cannot be negative.")
    if (tasks["duration_seconds"] <= 0).any():
        raise ValueError("duration_seconds must be positive.")
    if (tasks["energy_kwh"] < 0).any():
        raise ValueError("energy_kwh cannot be negative.")
    if (factors["carbon_intensity"] < 0).any():
        raise ValueError("carbon_intensity cannot be negative.")
    if factors["timestamp"].duplicated().any():
        raise ValueError("Carbon timestamps must be unique.")

    factors = factors.sort_values("timestamp").reset_index(drop=True)

    if factors.empty:
        if tasks.empty:
            return pd.DataFrame(columns=[
                "job_name", "task_name", "simulation_hour",
                "energy_kwh", "carbon_intensity", "co2_g",
                "overlap_seconds",
            ])
        raise ValueError("No carbon data is available.")

    if len(factors) > 1:
        intervals = factors["timestamp"].diff().dropna()
        if (intervals != pd.Timedelta(hours=1)).any():
            raise ValueError("Carbon timestamps must be exactly one hour apart.")

    starts = tasks["start_time"].to_numpy(dtype=float)
    durations = tasks["duration_seconds"].to_numpy(dtype=float)
    energies = tasks["energy_kwh"].to_numpy(dtype=float)
    ends = starts + durations

    first_hours = np.floor(starts / 3600).astype(np.int64)
    last_hours = np.floor(np.nextafter(ends, -np.inf) / 3600).astype(np.int64)

    if ((first_hours < 0) | (last_hours >= len(factors))).any():
        raise ValueError(
            "At least one task extends outside the available carbon-data window."
        )

    # Expand tasks into one row per occupied hour.
    task_indices = np.repeat(np.arange(len(tasks)), last_hours - first_hours + 1)

    if len(task_indices) == 0:
        return pd.DataFrame(columns=[
            "job_name", "task_name", "simulation_hour",
            "energy_kwh", "carbon_intensity", "co2_g",
            "overlap_seconds",
        ])

    repeats = last_hours - first_hours + 1
    segment_starts = np.repeat(first_hours, repeats)
    offsets = np.arange(len(task_indices)) - np.repeat(
        np.cumsum(repeats) - repeats, repeats
    )
    hours = segment_starts + offsets

    overlap_starts = np.maximum(starts[task_indices], hours * 3600)
    overlap_ends = np.minimum(ends[task_indices], (hours + 1) * 3600)
    overlap = overlap_ends - overlap_starts

    allocated_energy = energies[task_indices] * overlap / durations[task_indices]
    intensity = factors["carbon_intensity"].to_numpy()[hours]

    result = pd.DataFrame({
        "job_name": tasks["job_name"].to_numpy()[task_indices],
        "task_name": tasks["task_name"].to_numpy()[task_indices],
        "simulation_hour": hours,
        "energy_kwh": allocated_energy,
        "carbon_intensity": intensity,
        "co2_g": allocated_energy * intensity,
        "overlap_seconds": overlap,
    })

    return result
