"""Recompute scheduled energy and observed emissions from raw inputs."""

import csv
import json
from pathlib import Path


def main() -> None:
    run_dir = Path("results/phase6/full_real_20261111_run1")
    report_dir = Path("results/phase6/independent_validation")
    carbon_path = Path("data/raw/carbon/india_west_carbon_intensity.csv")
    with carbon_path.open("r", encoding="utf-8", newline="") as stream:
        carbon_rows = [row for row in csv.DictReader(stream) if row["zone"] == "IN-WE"]
    carbon_rows.sort(key=lambda row: row["datetime"])
    intensity = [float(row["carbonIntensity"]) for row in carbon_rows]
    power = 10.0
    summaries = {}
    for strategy in ("fifo", "earliest_feasible", "trace"):
        tasks = 0
        energy_sum = 0.0
        emissions_sum = 0.0
        covered = 0
        missing = 0
        max_energy_error = 0.0
        max_emissions_error = 0.0
        with (run_dir / f"{strategy}_schedule.csv").open("r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["task_status"] != "executed":
                    continue
                tasks += 1
                duration = float(row["duration_seconds"])
                cores = float(row["cpu_cores"])
                start = float(row["scheduled_start_time"])
                energy = duration * cores * power / 3_600_000.0
                stored_energy = float(row["energy_kwh"] or 0.0)
                max_energy_error = max(max_energy_error, abs(energy - stored_energy))
                energy_sum += energy
                end = start + duration
                first_hour = int(start // 3600)
                last_hour = int((end - 1e-12) // 3600) if duration > 0 else first_hour
                if duration > 0 and (first_hour < 0 or last_hour >= len(intensity)):
                    missing += 1
                    continue
                emissions = 0.0
                for hour in range(first_hour, last_hour + 1):
                    overlap = min(end, (hour + 1) * 3600.0) - max(start, hour * 3600.0)
                    emissions += energy * overlap / duration * intensity[hour] if duration > 0 else 0.0
                stored_emissions = float(row["estimated_emissions_g_co2e"] or 0.0)
                max_emissions_error = max(max_emissions_error, abs(emissions - stored_emissions))
                emissions_sum += emissions
                covered += 1
        summaries[strategy] = {
            "task_population": "all rows with task_status=executed; emissions calculated only when the full scheduled interval is covered by observed IN-WE carbon",
            "executed_tasks": tasks,
            "observed_carbon_covered_tasks": covered,
            "outside_carbon_tasks": missing,
            "power_assumption_watts_per_core": power,
            "recomputed_energy_kwh": energy_sum,
            "maximum_per_task_energy_difference_kwh": max_energy_error,
            "recomputed_observed_emissions_g_co2e": emissions_sum,
            "maximum_per_task_emissions_difference_g": max_emissions_error,
            "passed": tasks == covered and missing == 0 and max_energy_error < 1e-12 and max_emissions_error < 1e-9,
        }
    report = {
        "completed": all(item["passed"] for item in summaries.values()),
        "carbon_input": str(carbon_path.resolve()),
        "carbon_zone": "IN-WE",
        "carbon_rows": len(intensity),
        "formula": "energy_kwh = duration_seconds * cpu_cores * 10 W / 3,600,000; emissions_g = sum(energy_kwh * hourly_overlap_fraction * observed_carbon_intensity_g_per_kwh)",
        "strategies": summaries,
    }
    (report_dir / "emissions_recalculation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
