
"""Load and validate cleaned workload traces."""

from pathlib import Path

import pandas as pd

from src.data.energy_model import estimate_energy_kwh


REQUIRED_COLUMNS = {
    "job_name",
    "task_name",
    "start_time",
    "end_time",
    "duration_seconds",
    "cpu_cores",
}


def load_workload(csv_path: str | Path) -> pd.DataFrame:
    """Load a cleaned workload CSV and validate its required fields."""
    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(f"Workload CSV not found: {path}")

    df = pd.read_csv(path)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"Workload CSV is missing required columns: {sorted(missing)}"
        )

    for column in ("start_time", "end_time", "duration_seconds", "cpu_cores"):
        df[column] = pd.to_numeric(df[column], errors="raise")

    if df.empty:
        raise ValueError("Workload CSV contains no tasks.")

    if df[["start_time", "end_time", "duration_seconds", "cpu_cores"]].isna().any().any():
        raise ValueError("Workload contains missing required numeric values.")

    if (df["duration_seconds"] < 0).any():
        raise ValueError("Workload contains negative durations.")

    if (df["cpu_cores"] < 0).any():
        raise ValueError("Workload contains negative CPU allocations.")

    if (df["end_time"] < df["start_time"]).any():
        raise ValueError("Some tasks end before they start.")

    df["energy_kwh"] = [
        estimate_energy_kwh(duration, cores)
        for duration, cores in zip(
            df["duration_seconds"], df["cpu_cores"]
        )
    ]

    return df
