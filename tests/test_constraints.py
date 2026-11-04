
import pandas as pd
import pytest

from src.scheduler.constraints import (
    validate_cpu_capacity,
    validate_schedule_capacity,
    calculate_latest_start,
)


def test_overlapping_tasks_within_capacity():
    tasks = pd.DataFrame({
        "start_time": [0, 20],
        "duration_seconds": [60, 60],
        "cpu_cores": [3, 4],
    })

    validate_schedule_capacity(tasks, cpu_capacity=8)


def test_overlapping_tasks_exceed_capacity():
    tasks = pd.DataFrame({
        "start_time": [0, 20],
        "duration_seconds": [60, 60],
        "cpu_cores": [5, 4],
    })

    with pytest.raises(ValueError, match="Overlapping tasks"):
        validate_schedule_capacity(tasks, cpu_capacity=8)


def test_non_overlapping_tasks():
    tasks = pd.DataFrame({
        "start_time": [0, 60, 120],
        "duration_seconds": [60, 60, 30],
        "cpu_cores": [8, 8, 8],
    })

    validate_schedule_capacity(tasks, cpu_capacity=8)


def test_individual_task_exceeds_capacity():
    tasks = pd.DataFrame({
        "start_time": [0],
        "duration_seconds": [60],
        "cpu_cores": [9],
    })

    with pytest.raises(ValueError):
        validate_cpu_capacity(tasks, cpu_capacity=8)


def test_calculate_latest_start():
    tasks = pd.DataFrame({
        "start_time": [1000, 2000, 3000],
    })

    result = calculate_latest_start(
        tasks,
        max_delay_seconds=3600,
    )

    assert result.tolist() == [4600, 5600, 6600]
