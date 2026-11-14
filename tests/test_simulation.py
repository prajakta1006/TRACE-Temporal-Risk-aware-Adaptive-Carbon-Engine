import pandas as pd
import pytest

from src.experiments import RISK_WEIGHTS, run_sensitivity
from src.simulation import SimulationConfig, iter_workload_chunks, load_forecast_window_sample, normalize_workload, run_simulation, write_simulation_outputs
from src.scheduler.constraints import validate_schedule_capacity


BASE = pd.Timestamp("2026-01-01T00:00:00Z")


def inputs(tmp_path, rows=None, forecast_hours=(2, 3, 4)):
    carbon = pd.DataFrame({
        "timestamp": pd.date_range(BASE, periods=12, freq="h"),
        "carbon_intensity": [700, 650, 600, 700, 250, 200, 250, 300, 350, 400, 450, 500],
    })
    records = []
    for origin in forecast_hours:
        for lead in range(1, 5):
            target = origin + lead
            pred = 700 if target == 3 else 250 if target < 7 else 400
            records.append({
                "forecast_origin_utc": BASE + pd.Timedelta(hours=origin),
                "timestamp_utc": BASE + pd.Timedelta(hours=target),
                "horizon_hours": lead,
                "simulation_hour": target,
                "predicted_carbon_intensity": pred,
                "lower_bound": pred,
                "upper_bound": pred,
            })
    path = tmp_path / "forecast.csv"
    pd.DataFrame(records).to_csv(path, index=False)
    tasks = rows or [{"job_name": "j1", "task_name": "t1", "start_time": 3 * 3600, "duration_seconds": 1800, "cpu_cores": 2}]
    return pd.DataFrame(tasks), carbon, path


def test_trace_executes_reschedule_and_evaluates_observed_carbon(tmp_path):
    tasks, carbon, forecast = inputs(tmp_path)
    ledger, metrics, _ = run_simulation(tasks, carbon, forecast, SimulationConfig(risk_weight=0.0))
    trace = ledger[ledger.policy == "trace"].iloc[0]
    fifo = ledger[ledger.policy == "fifo"].iloc[0]
    assert trace.task_status == "executed"
    assert trace.decision == "rescheduled"
    assert trace.scheduled_start_time == 4 * 3600
    assert trace.source_row == 0
    assert trace.task_id == "trace-task-000000000000"
    assert fifo.scheduled_start_time == 3 * 3600
    stats = metrics.set_index("strategy")
    assert stats.loc["trace", "common_population_emissions_g_co2e"] < stats.loc["fifo", "common_population_emissions_g_co2e"]
    assert stats.loc["trace", "rescheduled_tasks"] == 1
    write_simulation_outputs(ledger, metrics, tmp_path)
    decisions = pd.read_csv(tmp_path / "simulation" / "scheduling_decisions.csv")
    assert decisions.task_id.eq("trace-task-000000000000").all()
    assert decisions.source_row.eq(0).all()


def test_running_and_committed_assignments_are_not_moved_and_capacity_holds(tmp_path):
    rows = [
        {"job_name": "j", "task_name": "committed", "start_time": 3 * 3600, "duration_seconds": 3600, "cpu_cores": 6},
        {"job_name": "j", "task_name": "later", "start_time": 4 * 3600, "duration_seconds": 1800, "cpu_cores": 4},
    ]
    tasks, carbon, forecast = inputs(tmp_path, rows, forecast_hours=(2, 3, 4))
    ledger, _, _ = run_simulation(tasks, carbon, forecast, SimulationConfig(risk_weight=0.0))
    trace = ledger[(ledger.policy == "trace") & (ledger.task_status == "executed")]
    validate_schedule_capacity(trace[["scheduled_start_time", "duration_seconds", "cpu_cores"]].rename(columns={"scheduled_start_time": "start_time"}), 8)
    assert trace.task_uid.is_unique
    assert trace.loc[trace.task_name == "committed", "scheduled_start_time"].iloc[0] == 4 * 3600
    assert trace.loc[trace.task_name == "later", "scheduled_start_time"].iloc[0] != 4 * 3600


def test_outside_forecast_tasks_stay_accounted_and_execute_at_baseline(tmp_path):
    tasks, carbon, forecast = inputs(tmp_path, [{"job_name": "j", "task_name": "early", "start_time": 3600, "duration_seconds": 600, "cpu_cores": 1}])
    ledger, metrics, _ = run_simulation(tasks, carbon, forecast)
    trace = ledger[ledger.policy == "trace"].iloc[0]
    assert trace.forecast_status == "outside_coverage"
    assert trace.task_status == "executed"
    assert trace.scheduled_start_time == 3600
    assert metrics.loc[metrics.strategy == "trace", "forecast_outside_coverage_tasks"].iloc[0] == 1


def test_cpu_infeasible_and_max_delay_deferred_are_distinct(tmp_path):
    rows = [
        {"job_name": "j", "task_name": "too_big", "start_time": 3 * 3600, "duration_seconds": 600, "cpu_cores": 9},
        {"job_name": "j", "task_name": "first", "start_time": 3 * 3600, "duration_seconds": 3600, "cpu_cores": 8},
        {"job_name": "j", "task_name": "second", "start_time": 3 * 3600, "duration_seconds": 3600, "cpu_cores": 8},
    ]
    tasks, carbon, forecast = inputs(tmp_path, rows)
    ledger, _, _ = run_simulation(tasks, carbon, forecast, SimulationConfig(max_delay_seconds=0))
    trace = ledger[ledger.policy == "trace"].set_index("task_name")
    assert trace.loc["too_big", "task_status"] == "infeasible"
    assert trace.loc["second", "task_status"] == "deferred"
    assert trace.loc["first", "task_status"] == "executed"


def test_large_workload_reader_yields_chunks(tmp_path):
    path = tmp_path / "workload.csv"
    pd.DataFrame([{"job_name": "j", "task_name": f"t{i}", "start_time": i, "duration_seconds": 1, "cpu_cores": 1} for i in range(13)]).to_csv(path, index=False)
    chunks = list(iter_workload_chunks(path, chunk_size=5))
    assert [len(chunk) for chunk in chunks] == [5, 5, 3]
    assert sum(map(len, chunks)) == 13


def test_bounded_sample_includes_forecast_covered_and_uncovered_rows(tmp_path):
    tasks, carbon, forecast = inputs(tmp_path)
    workload_path = tmp_path / "large.csv"
    rows = []
    for i in range(10):
        rows.append({"job_name": "j", "task_name": f"t{i}", "start_time": 3600 if i % 2 == 0 else 3 * 3600, "duration_seconds": 600, "cpu_cores": 1})
    pd.DataFrame(rows).to_csv(workload_path, index=False)
    sample, metadata = load_forecast_window_sample(workload_path, forecast, carbon, max_tasks=4, chunk_size=5)
    assert len(sample) == 4
    assert metadata["outside_coverage_sample"] == 2
    assert metadata["forecast_eligible_sample"] == 2
    assert sample.source_row.tolist() == [0, 1, 2, 3]


def test_zero_duration_task_is_accounted_without_carbon_allocation(tmp_path):
    tasks, carbon, forecast = inputs(tmp_path, [{"job_name": "j", "task_name": "instant", "start_time": 3 * 3600, "duration_seconds": 0, "cpu_cores": 1}])
    ledger, metrics, _ = run_simulation(tasks, carbon, forecast)
    assert (ledger.task_status == "executed").all()
    assert (metrics.executed_tasks == 1).all()
    assert (metrics.total_energy_kwh == 0).all()


def test_normalization_preserves_source_identity_after_sorting():
    tasks = pd.DataFrame([
        {"job_name": "j", "task_name": "late", "source_row": 7, "task_id": "trace-task-000000000007", "start_time": 7, "duration_seconds": 1, "cpu_cores": 1},
        {"job_name": "j", "task_name": "early", "source_row": 2, "task_id": "trace-task-000000000002", "start_time": 2, "duration_seconds": 1, "cpu_cores": 1},
    ])
    normalized = normalize_workload(tasks.sort_values("start_time"))
    assert normalized.source_row.tolist() == [2, 7]
    assert normalized.task_id.tolist() == ["trace-task-000000000002", "trace-task-000000000007"]


def test_sensitivity_runs_configured_risk_weights(tmp_path):
    tasks, carbon, forecast = inputs(tmp_path)
    result = run_sensitivity(tasks, carbon, forecast, tmp_path)
    assert tuple(result["risk_weight"].parameter) == RISK_WEIGHTS
    assert (tmp_path / "experiments" / "risk_weight_sensitivity.csv").is_file()
    assert (tmp_path / "experiments" / "power_per_core_watts_sensitivity.csv").is_file()
