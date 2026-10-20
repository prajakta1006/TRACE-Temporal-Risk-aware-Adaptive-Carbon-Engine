import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
"""Run the TRACE workload-to-hourly-emissions pipeline."""

import argparse
import json
from pathlib import Path

import pandas as pd

from src.data.prepare_carbon import load_carbon
from src.data.validate_data import validate_workload_data
from src.data.hourly_emissions import allocate_hourly_emissions


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_WORKLOAD = Path(
    r"C:\Users\sharv\carbon-flexibility-scheduling"
    r"\data\processed\workload_cleaned.csv"
)
DEFAULT_CARBON = Path(
    r"C:\Users\sharv\carbon-flexibility-scheduling"
    r"\data\raw\carbon\india_west_carbon_intensity.csv"
)

CHUNK_SIZE = 50_000
WATTS_PER_CORE = 10


def main():
    parser = argparse.ArgumentParser(
        description="Calculate TRACE hourly workload emissions."
    )
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--carbon", type=Path, default=DEFAULT_CARBON)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    if not args.workload.is_file():
        raise FileNotFoundError(f"Workload CSV not found: {args.workload}")
    if not args.carbon.is_file():
        raise FileNotFoundError(f"Carbon CSV not found: {args.carbon}")
    if args.max_rows is not None and args.max_rows <= 0:
        parser.error("--max-rows must be a positive integer")

    output_csv = args.output.resolve()
    summary_json = (
        args.summary.resolve()
        if args.summary
        else output_csv.with_name(output_csv.stem + "_summary.json")
    )

    # Avoid accidentally overwriting prior results or source files.
    protected = {
        args.workload.resolve(),
        args.carbon.resolve(),
    }
    if output_csv in protected or summary_json in protected:
        parser.error("Output paths must not overwrite source datasets.")
    if output_csv == summary_json:
        parser.error("Output CSV and summary paths must be different.")
    if output_csv.exists() or summary_json.exists():
        parser.error(
            "Output already exists. Choose a new output filename; "
            "existing files will not be overwritten."
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)

    print("Loading carbon data...")
    carbon = load_carbon(args.carbon, zone="IN-WE")
    if carbon.empty:
        raise ValueError("No carbon records found for zone IN-WE.")

    total_tasks = 0
    total_hourly_rows = 0
    total_energy_kwh = 0.0
    total_co2_g = 0.0
    first_chunk = True

    try:
        reader = pd.read_csv(
            args.workload,
            chunksize=CHUNK_SIZE,
        )

        for chunk_number, workload in enumerate(reader, start=1):
            if args.max_rows is not None:
                remaining = args.max_rows - total_tasks
                if remaining <= 0:
                    break
                workload = workload.iloc[:remaining].copy()

            if workload.empty:
                break

            report = validate_workload_data(workload)
            if report["missing_columns"]:
                raise ValueError(
                    f"Chunk {chunk_number} missing columns: "
                    f"{report['missing_columns']}"
                )
            if report["warnings"]:
                raise ValueError(
                    f"Quality warnings in chunk {chunk_number}: "
                    f"{report['warnings']}"
                )

            workload["start_time"] = pd.to_numeric(
                workload["start_time"], errors="raise"
            )
            workload["duration_seconds"] = pd.to_numeric(
                workload["duration_seconds"], errors="raise"
            )
            workload["cpu_cores"] = pd.to_numeric(
                workload["cpu_cores"], errors="raise"
            )

            if workload[
                ["start_time", "duration_seconds", "cpu_cores"]
            ].isna().any().any():
                raise ValueError("Workload timing and CPU values cannot be missing.")
            if (workload["start_time"] < 0).any():
                raise ValueError("Workload start_time cannot be negative.")
            if (workload["duration_seconds"] < 0).any():
                raise ValueError("Workload duration cannot be negative.")
            if (workload["cpu_cores"] < 0).any():
                raise ValueError("CPU allocations cannot be negative.")

            workload["energy_kwh"] = (
                workload["duration_seconds"]
                * workload["cpu_cores"]
                * WATTS_PER_CORE
                / 3_600_000
            )

            # Zero-duration tasks have no hourly allocation; report them
            # as invalid for this pipeline rather than silently omitting them.
            if (workload["duration_seconds"] == 0).any():
                raise ValueError(
                    "Zero-duration tasks found; clean or handle them explicitly."
                )

            hourly = allocate_hourly_emissions(workload, carbon)

            hourly.to_csv(
                output_csv,
                mode="w" if first_chunk else "a",
                header=first_chunk,
                index=False,
            )
            first_chunk = False

            total_tasks += len(workload)
            total_hourly_rows += len(hourly)
            total_energy_kwh += float(hourly["energy_kwh"].sum())
            total_co2_g += float(hourly["co2_g"].sum())

            print(
                f"Chunk {chunk_number}: {len(workload):,} tasks; "
                f"{total_tasks:,} total tasks processed."
            )

            if args.max_rows is not None and total_tasks >= args.max_rows:
                break

    except Exception:
        if output_csv.exists():
            output_csv.unlink()
        raise

    summary = {
        "workload_file": str(args.workload.resolve()),
        "carbon_file": str(args.carbon.resolve()),
        "output_csv": str(output_csv),
        "carbon_zone": "IN-WE",
        "tasks_processed": total_tasks,
        "hourly_output_rows": total_hourly_rows,
        "estimated_energy_kwh": total_energy_kwh,
        "estimated_emissions_g_co2eq": total_co2_g,
        "assumed_cpu_power_watts_per_core": WATTS_PER_CORE,
        "chunk_size": CHUNK_SIZE,
        "time_mapping": (
            "Workload start_time is relative simulation seconds; "
            "carbon records map sequentially to simulation hours."
        ),
        "max_rows_limit": args.max_rows,
    }

    summary_json.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\nPipeline completed.")
    print(f"Hourly output: {output_csv}")
    print(f"Summary: {summary_json}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
