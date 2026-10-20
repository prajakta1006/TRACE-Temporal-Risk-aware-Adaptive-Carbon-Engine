
"""Data-quality checks for TRACE workload and carbon datasets."""

import pandas as pd


def validate_workload_data(df: pd.DataFrame) -> dict:
    """Summarize workload data quality without modifying the input."""
    required = {
        "job_name",
        "task_name",
        "start_time",
        "end_time",
        "duration_seconds",
        "cpu_cores",
    }

    missing_columns = sorted(required - set(df.columns))
    report = {
        "dataset": "workload",
        "rows": len(df),
        "missing_columns": missing_columns,
        "missing_values": {},
        "negative_duration_rows": None,
        "negative_cpu_rows": None,
        "end_before_start_rows": None,
        "duration_mismatch_rows": None,
        "duplicate_job_task_rows": None,
        "warnings": [],
    }

    if missing_columns:
        report["warnings"].append(
            "Cannot run all checks because required columns are missing."
        )
        return report

    columns = [
        "start_time",
        "end_time",
        "duration_seconds",
        "cpu_cores",
    ]

    report["missing_values"] = {
        col: int(df[col].isna().sum()) for col in sorted(required)
    }

    numeric = df[columns].apply(pd.to_numeric, errors="coerce")

    for col in columns:
        invalid = numeric[col].isna() & df[col].notna()
        if invalid.any():
            report["warnings"].append(
                f"{col} contains {int(invalid.sum())} non-numeric values."
            )

    report["negative_duration_rows"] = int(
        (numeric["duration_seconds"] < 0).sum()
    )
    report["negative_cpu_rows"] = int(
        (numeric["cpu_cores"] < 0).sum()
    )
    report["end_before_start_rows"] = int(
        (numeric["end_time"] < numeric["start_time"]).sum()
    )

    calculated_duration = numeric["end_time"] - numeric["start_time"]
    mismatch = (
        (calculated_duration - numeric["duration_seconds"]).abs() > 1
    )
    report["duration_mismatch_rows"] = int(mismatch.sum())

    duplicate_keys = df.duplicated(
        subset=["job_name", "task_name"], keep=False
    )
    report["duplicate_job_task_rows"] = int(duplicate_keys.sum())

    if report["duplicate_job_task_rows"]:
        report["warnings"].append(
            "Repeated job/task pairs found; verify whether these are valid."
        )

    if report["duration_mismatch_rows"]:
        report["warnings"].append(
            "Some durations differ from end_time - start_time by more than "
            "one second. Confirm the source semantics."
        )

    return report


def validate_carbon_data(df: pd.DataFrame) -> dict:
    """Summarize carbon-data quality and hourly coverage."""
    required = {"timestamp", "carbon_intensity"}

    if "timestamp" not in df.columns and "datetime" in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})

    if "carbon_intensity" not in df.columns and "carbonIntensity" in df.columns:
        df = df.rename(
            columns={"carbonIntensity": "carbon_intensity"}
        )

    missing_columns = sorted(required - set(df.columns))

    report = {
        "dataset": "carbon",
        "rows": len(df),
        "missing_columns": missing_columns,
        "missing_values": {},
        "duplicate_timestamps": None,
        "negative_intensity_rows": None,
        "invalid_timestamps": None,
        "non_hourly_intervals": None,
        "missing_hour_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "intensity_min": None,
        "intensity_max": None,
        "warnings": [],
    }

    if missing_columns:
        report["warnings"].append(
            "Cannot run all checks because required columns are missing."
        )
        return report

    timestamps = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    intensity = pd.to_numeric(
        df["carbon_intensity"], errors="coerce"
    )

    report["missing_values"] = {
        "timestamp": int(timestamps.isna().sum()),
        "carbon_intensity": int(intensity.isna().sum()),
    }
    report["invalid_timestamps"] = int(
        (timestamps.isna() & df["timestamp"].notna()).sum()
    )
    report["duplicate_timestamps"] = int(
        timestamps[timestamps.notna()].duplicated().sum()
    )
    report["negative_intensity_rows"] = int(
        (intensity < 0).sum()
    )

    valid = pd.DataFrame({
        "timestamp": timestamps,
        "intensity": intensity,
    }).dropna()

    if not valid.empty:
        valid = valid.sort_values("timestamp")
        report["first_timestamp"] = str(valid["timestamp"].min())
        report["last_timestamp"] = str(valid["timestamp"].max())
        report["intensity_min"] = float(valid["intensity"].min())
        report["intensity_max"] = float(valid["intensity"].max())

        intervals = valid["timestamp"].diff().dropna()
        report["non_hourly_intervals"] = int(
            (intervals != pd.Timedelta(hours=1)).sum()
        )

        expected_hours = pd.date_range(
            start=valid["timestamp"].min(),
            end=valid["timestamp"].max(),
            freq="h",
        )
        actual_hours = pd.DatetimeIndex(valid["timestamp"])
        report["missing_hour_count"] = len(
            expected_hours.difference(actual_hours)
        )

    if report["duplicate_timestamps"]:
        report["warnings"].append("Duplicate carbon timestamps found.")

    if report["negative_intensity_rows"]:
        report["warnings"].append("Negative carbon intensity values found.")

    if report["non_hourly_intervals"]:
        report["warnings"].append(
            "Carbon records are not consistently one hour apart."
        )

    return report
