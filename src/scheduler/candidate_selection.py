"""Generate feasible candidate execution times for TRACE tasks."""

import math
import pandas as pd


def generate_candidate_starts(
    task: pd.Series,
    current_time: float,
    forecast_hours: int = 4,
    max_delay_seconds: float = 3600.0,
    interval_seconds: float = 3600.0,
) -> list[float]:

    required_columns = {
        "start_time",
        "duration_seconds",
    }

    missing = required_columns - set(task.index)

    if missing:
        raise ValueError(
            f"Task is missing columns: {sorted(missing)}"
        )

    if forecast_hours <= 0:
        raise ValueError("forecast_hours must be positive.")

    if max_delay_seconds < 0:
        raise ValueError("max_delay_seconds cannot be negative.")

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive.")

    release_time = float(task["start_time"])
    duration = float(task["duration_seconds"])

    if not math.isfinite(release_time) or release_time < 0:
        raise ValueError("Task start_time must be non-negative.")

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Task duration_seconds must be positive.")

    if not math.isfinite(current_time) or current_time < 0:
        raise ValueError("current_time must be non-negative.")

    horizon_end = current_time + forecast_hours * 3600

    latest_start = release_time + max_delay_seconds

    earliest_start = max(release_time, current_time)

    latest_feasible_start = min(
        latest_start,
        horizon_end,
    )

    # Align the first candidate to the next hourly boundary.
    first_candidate = (
        math.ceil(earliest_start / interval_seconds)
        * interval_seconds
    )

    candidates = []

    candidate = first_candidate

    while candidate <= latest_feasible_start:
        candidates.append(float(candidate))
        candidate += interval_seconds

    return candidates