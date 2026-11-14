"""Stable identities derived solely from source CSV data-row positions."""

from __future__ import annotations


DEFAULT_TASK_ID_PREFIX = "trace-task-"


def task_id_for_source_row(source_row: int, prefix: str = DEFAULT_TASK_ID_PREFIX) -> str:
    """Format a zero-based, header-excluding source row as a stable task ID."""
    row = int(source_row)
    if row < 0 or row != source_row:
        raise ValueError("source_row must be a non-negative integer")
    if not prefix:
        raise ValueError("prefix cannot be empty")
    return f"{prefix}{row:012d}"
