"""Compare independent Phase 6 results with engine and checkpoint records."""

import json
from pathlib import Path
import sqlite3


def main() -> None:
    run_dir = Path("results/phase6/full_real_20261111_run1")
    validation_dir = Path("results/phase6/independent_validation")
    independent = json.loads((validation_dir / "independent_validation.json").read_text(encoding="utf-8"))
    evaluation = json.loads((run_dir / "final_evaluation.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "event_run_summary.json").read_text(encoding="utf-8"))
    checkpoint = sqlite3.connect(f"file:{(run_dir / 'checkpoint.sqlite3').resolve().as_posix()}?mode=ro", uri=True)
    checkpoint.row_factory = sqlite3.Row
    state = dict(checkpoint.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone())
    offsets = json.loads(state["output_offsets_json"])
    checks = {}
    comparisons = {}
    for strategy, report in independent["strategies"].items():
        evaluated = evaluation["strategy_results"][strategy]
        engine = summary["strategy_metrics"][strategy]
        values = {
            "processed_rows_match": report["row_count"] == evaluated["tasks_processed"] == engine["tasks_total"] == state["processed_tasks"],
            "task_states_match": report["task_status_counts"].get("executed", 0) == evaluated["completed_tasks"] == engine["executed_tasks"],
            "deferred_match": report["task_status_counts"].get("deferred", 0) == evaluated["deferred_tasks"] == engine["deferred_tasks"],
            "infeasible_match": report["task_status_counts"].get("infeasible", 0) == evaluated["infeasible_tasks"] == engine["infeasible_tasks"],
            "emissions_covered_population_match": report["emissions_covered_tasks"] == evaluated["emissions_covered_tasks"] == engine["actual_emissions_tasks"],
            "emissions_missing_population_match": report["emissions_coverage_missing_tasks"] == evaluated["emissions_coverage_missing_tasks"] == engine["emissions_coverage_missing_tasks"],
            "energy_match": abs(report["scheduled_energy_kwh"] - evaluated["scheduled_energy_kwh"]) < 1e-10 and abs(report["scheduled_energy_kwh"] - engine["scheduled_energy_kwh"]) < 1e-10,
            "observed_emissions_match": abs(report["scheduled_observed_emissions_g_co2e"] - evaluated["scheduled_observed_emissions_g_co2e"]) < 1e-8 and abs(report["scheduled_observed_emissions_g_co2e"] - engine["scheduled_observed_emissions_g_co2e"]) < 1e-8,
            "checkpoint_offset_match": report["byte_size"] == offsets[strategy] == report["checkpoint_offset"],
            "ledger_integrity_passed": report["passed"],
        }
        comparisons[strategy] = values
        checks[strategy] = all(values.values())
    report = {
        "completed": all(checks.values()),
        "checkpoint_processed_tasks": state["processed_tasks"],
        "checkpoint_completed": bool(state["completed"]),
        "checkpoint_last_task_id": state["last_task_id"],
        "comparison_source": str((run_dir / "final_evaluation.json").resolve()),
        "strategies": comparisons,
        "common_executed_population": evaluation["common_population"]["common_executed_tasks"],
        "common_observed_emissions_population": evaluation["common_population"]["common_observed_emissions_tasks"],
        "common_population_emissions_g_co2e": evaluation["common_population"]["common_population_observed_emissions_g_co2e"],
    }
    (validation_dir / "cross_check_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    checkpoint.close()
    print(json.dumps(report, indent=2))
    if not report["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
