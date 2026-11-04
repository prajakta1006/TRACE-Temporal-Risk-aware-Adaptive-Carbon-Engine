
"""Resource and deadline constraints for TRACE scheduling."""

import math
import pandas as pd


def validate_cpu_capacity(
    tasks: pd.DataFrame,
    cpu_capacity: float = 8.0,
) -> None:
    """Check whether every individual task fits within CPU capacity."""

    if not math.isfinite(cpu_capacity) or cpu_capacity <= 0:
        raise ValueError("cpu_capacity must be positive and finite.")

    if "cpu_cores" not in tasks.columns:
        raise ValueError("Tasks must contain cpu_cores.")

    cores = pd.to_numeric(tasks["cpu_cores"], errors="raise")

    if cores.isna().any() or not cores.map(math.isfinite).all():
        raise ValueError("CPU requirements must be finite numbers.")

    if (cores < 0).any():
        raise ValueError("CPU requirements must be non-negative.")

    if (cores > cpu_capacity).any():
        raise ValueError(
            "At least one task requires more CPU than total capacity."
        )


def validate_schedule_capacity(
    tasks: pd.DataFrame,
    cpu_capacity: float = 8.0,
) -> None:
    """
    Check that overlapping scheduled tasks never exceed CPU capacity.

    Each task occupies CPU from start_time until
    start_time + duration_seconds.

    Tasks ending at a particular time release their CPU before
    tasks starting at that same time are counted.
    """

    required_columns = {
        "start_time",
        "duration_seconds",
        "cpu_cores",
    }

    missing = required_columns - set(tasks.columns)

    if missing:
        raise ValueError(
            f"Tasks are missing columns: {sorted(missing)}"
        )

    validate_cpu_capacity(tasks, cpu_capacity)

    starts = pd.to_numeric(tasks["start_time"], errors="raise")
    durations = pd.to_numeric(
        tasks["duration_seconds"], errors="raise"
    )
    cores = pd.to_numeric(tasks["cpu_cores"], errors="raise")

    for column, values in {
        "start_time": starts,
        "duration_seconds": durations,
    }.items():
        if values.isna().any() or not values.map(math.isfinite).all():
            raise ValueError(f"{column} must contain finite numbers.")

        if (values < 0).any():
            raise ValueError(f"{column} cannot contain negative values.")

    if (durations <= 0).any():
        raise ValueError("Task durations must be positive.")

    events = []

    for start, duration, cpu in zip(starts, durations, cores):
        end = start + duration

        if not math.isfinite(end):
            raise ValueError("Task end times must be finite.")

        # Negative event releases CPU; positive event allocates CPU.
        events.append((end, -cpu))
        events.append((start, cpu))

    # At equal timestamps, negative events come before positive events.
    events.sort(key=lambda event: (event[0], event[1]))

    allocated_cpu = 0.0

    for _, change in events:
        allocated_cpu += change

        if allocated_cpu > cpu_capacity + 1e-9:
            raise ValueError(
                "Overlapping tasks exceed the available CPU capacity."
            )


def calculate_latest_start(
    tasks: pd.DataFrame,
    max_delay_seconds: float = 3600.0,
) -> pd.Series:
    """Calculate each task's latest permitted start time."""

    if (
        not math.isfinite(max_delay_seconds)
        or max_delay_seconds < 0
    ):
        raise ValueError(
            "max_delay_seconds must be non-negative and finite."
        )

    if "start_time" not in tasks.columns:
        raise ValueError("Tasks must contain start_time.")

    start_times = pd.to_numeric(tasks["start_time"], errors="raise")

    if start_times.isna().any() or not start_times.map(math.isfinite).all():
        raise ValueError("Original start times must be finite numbers.")

    if (start_times < 0).any():
        raise ValueError("Original start times must be non-negative.")

    return start_times + max_delay_seconds
