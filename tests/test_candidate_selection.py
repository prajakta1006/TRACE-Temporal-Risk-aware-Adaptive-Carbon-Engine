import pandas as pd
import pytest

from src.scheduler.candidate_selection import generate_candidate_starts


def test_generate_candidate_starts():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 1800,
    })

    result = generate_candidate_starts(
        task,
        current_time=3600,
        forecast_hours=4,
        max_delay_seconds=3600,
    )

    assert result == [3600.0, 7200.0]


def test_task_already_delayed():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 1800,
    })

    result = generate_candidate_starts(
        task,
        current_time=5400,
    )

    assert result == [7200.0]


def test_no_candidate_after_latest_start():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 1800,
    })

    result = generate_candidate_starts(
        task,
        current_time=9000,
    )

    assert result == []


def test_task_must_finish_within_horizon():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 10800,
    })

    result = generate_candidate_starts(
        task,
        current_time=3600,
        forecast_hours=4,
        max_delay_seconds=3600,
    )

    assert result == [3600.0, 7200.0]


def test_negative_maximum_delay():
    task = pd.Series({
        "start_time": 3600,
        "duration_seconds": 1800,
    })

    with pytest.raises(ValueError):
        generate_candidate_starts(
            task,
            current_time=3600,
            max_delay_seconds=-100,
        )