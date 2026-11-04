
"""Connect rolling four-hour forecasts to the TRACE scheduler."""

import pandas as pd

from src.scheduler.forecast_adapter import (
    load_scheduler_forecasts,
    select_forecast_origin,
)
from src.scheduler.scheduler import select_task_candidate


def select_task_candidate_at_origin(
    task: pd.Series,
    rolling_forecasts: pd.DataFrame,
    forecast_origin_utc: str,
    simulation_start_utc: str,
    scheduled_tasks: pd.DataFrame | None = None,
    cpu_capacity: float = 8.0,
    forecast_hours: int = 4,
    max_delay_seconds: float = 3600.0,
    risk_weight: float = 0.5,
) -> dict | None:
    """
    Select a task candidate using only one rolling forecast origin.

    Tasks whose complete baseline or candidate execution periods are not
    covered by the selected forecast are not rescheduled.
    """

    if forecast_hours != 4:
        raise ValueError(
            "This rolling integration currently expects a four-hour horizon."
        )

    # Select the four forecasts generated at this replanning origin.
    origin_forecasts = select_forecast_origin(
        rolling_forecasts,
        forecast_origin_utc,
    )

    if len(origin_forecasts) != forecast_hours:
        raise ValueError(
            f"Expected {forecast_hours} forecasts for this origin, "
            f"but found {len(origin_forecasts)}."
        )

    expected_horizons = list(range(1, forecast_hours + 1))

    if origin_forecasts["horizon_hours"].tolist() != expected_horizons:
        raise ValueError(
            "Forecast origin must contain horizons 1, 2, 3 and 4."
        )

    # Convert the forecast origin into simulation seconds.
    origin = pd.to_datetime(
        forecast_origin_utc, utc=True, errors="raise"
    )
    simulation_start = pd.to_datetime(
        simulation_start_utc, utc=True, errors="raise"
    )

    elapsed_seconds = (origin - simulation_start).total_seconds()

    if elapsed_seconds < 0 or elapsed_seconds % 3600 != 0:
        raise ValueError(
            "Forecast origin must be an hourly timestamp at or after "
            "the simulation start."
        )

    current_time = float(elapsed_seconds)

    # Delegate candidate generation, risk scoring and capacity checks
    # to the existing Person 3 scheduling engine.
    return select_task_candidate(
        task=task,
        forecasts=origin_forecasts,
        current_time=current_time,
        scheduled_tasks=scheduled_tasks,
        cpu_capacity=cpu_capacity,
        forecast_hours=forecast_hours,
        max_delay_seconds=max_delay_seconds,
        risk_weight=risk_weight,
    )


def load_and_select_task_candidate(
    task: pd.Series,
    forecast_csv: str,
    forecast_origin_utc: str,
    simulation_start_utc: str,
    **scheduler_options,
) -> dict | None:
    """Convenience function that loads rolling forecasts and schedules."""

    forecasts = load_scheduler_forecasts(
        forecast_csv,
        simulation_start_utc,
    )

    return select_task_candidate_at_origin(
        task=task,
        rolling_forecasts=forecasts,
        forecast_origin_utc=forecast_origin_utc,
        simulation_start_utc=simulation_start_utc,
        **scheduler_options,
    )
