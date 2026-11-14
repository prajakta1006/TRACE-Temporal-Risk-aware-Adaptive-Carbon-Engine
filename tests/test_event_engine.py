import csv
import json

import pandas as pd

from src.scheduler.event_engine import (
    CapacityCalendar,
    EventScheduler,
    EventSchedulerConfig,
    run_event_simulation,
)


BASE = pd.Timestamp("2026-01-01T00:00:00Z")


def _carbon(hours=16):
    return pd.DataFrame({
        "timestamp": pd.date_range(BASE, periods=hours, freq="h"),
        "carbon_intensity": [700.0] * hours,
    })


def _forecasts(carbon, origin_hour=2, overrides=None, leads=range(1, 5)):
    overrides = overrides or {}
    rows = []
    for lead in leads:
        target_hour = origin_hour + lead
        if target_hour >= len(carbon):
            continue
        pred = float(overrides.get(target_hour, 400))
        rows.append({
            "forecast_origin_utc": BASE + pd.Timedelta(hours=origin_hour),
            "timestamp_utc": BASE + pd.Timedelta(hours=target_hour),
            "horizon_hours": lead,
            "simulation_hour": target_hour,
            "predicted_carbon_intensity": pred,
            "lower_bound": pred - 20,
            "upper_bound": pred + 20,
            # This deliberately differs from the prediction. The engine must
            # never read future actuals during scheduling.
            "actual_carbon_intensity": 1.0,
        })
    return pd.DataFrame(rows)


def _task(source_row, start, duration, cores, name=None):
    return {
        "source_row": source_row,
        "task_id": f"trace-task-{source_row:012d}",
        "job_name": "job",
        "task_name": name or f"task-{source_row}",
        "start_time": float(start),
        "duration_seconds": float(duration),
        "cpu_cores": float(cores),
    }


def _write_ordered(path, tasks):
    fields = ["source_row", "task_id", "job_name", "task_name", "start_time", "duration_seconds", "cpu_cores"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(tasks, key=lambda x: (x["start_time"], x["task_id"])))


def test_capacity_calendar_reserves_running_and_committed_intervals():
    calendar = CapacityCalendar(8)
    calendar.advance(0)
    assert calendar.fits(0, 3600, 6)
    calendar.add(0, 3600, 6)
    calendar.advance(100)
    assert not calendar.fits(100, 200, 3)
    assert calendar.earliest_slot(100, 1000, 100, 3) is None
    assert calendar.earliest_slot(100, 4000, 100, 3) == 3600
    assert calendar.fits(3600, 4000, 8)
    calendar.add(3600, 4000, 8)
    assert calendar.earliest_slot(100, 4500, 200, 8) == 4000
    calendar.advance(200)
    assert not calendar.fits(3600, 3700, 1)


def test_equal_release_tasks_use_stable_task_id_order_and_prevent_duplicates():
    carbon = _carbon()
    forecasts = _forecasts(carbon)
    engine = EventScheduler("earliest_feasible", carbon, forecasts, EventSchedulerConfig())
    first = engine.schedule_task(_task(4, 100, 60, 4))
    second = engine.schedule_task(_task(5, 100, 60, 4))
    duplicate = engine.schedule_task(_task(5, 200, 60, 1))
    assert first["task_id"] < second["task_id"]
    assert first["scheduled_start_time"] == second["scheduled_start_time"] == 100
    assert duplicate["task_status"] == "duplicate_prevented"
    assert engine.counters["duplicate_prevented_tasks"] == 1


def test_fifo_protects_committed_work_and_respects_task_lifecycle():
    carbon = _carbon()
    engine = EventScheduler("fifo", carbon, _forecasts(carbon), EventSchedulerConfig())
    a = engine.schedule_task(_task(0, 0, 3600, 8))
    b = engine.schedule_task(_task(1, 100, 100, 2))
    c = engine.schedule_task(_task(2, 200, 100, 8))
    assert a["commitment_state_at_decision"] == "running_at_release"
    assert b["scheduled_start_time"] == 3600
    assert b["commitment_state_at_decision"] == "committed"
    assert c["scheduled_start_time"] == 3700
    assert engine.committed
    engine.finish()
    assert not engine.running and not engine.committed


def test_infeasible_capacity_max_delay_and_multihour_reservation():
    carbon = _carbon()
    engine = EventScheduler("earliest_feasible", carbon, _forecasts(carbon), EventSchedulerConfig(max_delay_seconds=0))
    too_wide = engine.schedule_task(_task(0, 0, 10, 9))
    long_task = engine.schedule_task(_task(1, 0, 7200, 8))
    blocked = engine.schedule_task(_task(2, 0, 30, 1))
    assert too_wide["task_status"] == "infeasible"
    assert long_task["scheduled_end_time"] == 7200
    assert blocked["task_status"] == "deferred"
    assert blocked["decision"] == "no_capacity_slot_within_max_delay"


def test_trace_selects_forecast_candidate_and_ignores_actual_values():
    carbon = _carbon()
    forecasts = _forecasts(carbon, overrides={3: 700, 4: 100, 5: 200, 6: 300})
    engine = EventScheduler("trace", carbon, forecasts, EventSchedulerConfig(risk_weight=0))
    row = engine.schedule_task(_task(0, 3 * 3600, 1800, 1))
    assert row["forecast_status"] == "eligible"
    assert row["scheduled_start_time"] == 4 * 3600
    assert row["decision"] == "forecast_rescheduled"
    assert row["estimated_emissions_g_co2e"] > 0


def test_forecast_gap_uses_explicit_fallback_without_fabrication():
    carbon = _carbon()
    forecasts = _forecasts(carbon, leads=(2, 3, 4))
    engine = EventScheduler("trace", carbon, forecasts, EventSchedulerConfig())
    row = engine.schedule_task(_task(0, 3 * 3600, 120, 1))
    assert row["task_status"] == "executed"
    assert row["forecast_status"] == "ineligible"
    assert row["forecast_reason"] == "incomplete_origin_coverage"
    assert row["decision"] == "fallback_incomplete_origin_coverage"
    assert row["scheduled_start_time"] == 3 * 3600


def test_forecast_origin_and_horizon_mismatch_is_rejected():
    import pytest
    carbon = _carbon()
    forecasts = _forecasts(carbon)
    forecasts.loc[0, "timestamp_utc"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="origin plus horizon"):
        EventScheduler("trace", carbon, forecasts, EventSchedulerConfig())


def test_missing_origin_fallback_and_delay_limit():
    carbon = _carbon()
    engine = EventScheduler("trace", carbon, _forecasts(carbon), EventSchedulerConfig(max_delay_seconds=0))
    first = engine.schedule_task(_task(0, 100, 3600, 8))
    second = engine.schedule_task(_task(1, 100, 10, 1))
    assert first["forecast_reason"] == "missing_forecast_origin"
    assert second["task_status"] == "deferred"
    assert second["delay_seconds"] is None


def test_streamed_strategies_share_ids_and_repeat_deterministically(tmp_path):
    carbon = _carbon()
    forecast = tmp_path / "forecast.csv"
    _forecasts(carbon).to_csv(forecast, index=False)
    workload = tmp_path / "ordered.csv"
    tasks = [_task(i, 100 * i, 20, 1) for i in range(20)]
    _write_ordered(workload, tasks)
    first = run_event_simulation(workload, carbon, forecast, tmp_path / "run1")
    second = run_event_simulation(workload, carbon, forecast, tmp_path / "run2")
    assert first["tasks_processed"] == second["tasks_processed"] == 20
    assert first["common_executed_population"] == 20
    for strategy in ("fifo", "earliest_feasible", "trace"):
        a = pd.read_csv(tmp_path / "run1" / f"{strategy}_schedule.csv")
        b = pd.read_csv(tmp_path / "run2" / f"{strategy}_schedule.csv")
        assert a.task_id.tolist() == b.task_id.tolist()
        assert a.scheduled_start_time.tolist() == b.scheduled_start_time.tolist()
        assert a.task_status.eq("executed").all()
    summary = pd.read_csv(tmp_path / "run1" / "execution_summary.csv")
    assert summary.cpu_capacity_violations.eq(0).all()
    assert summary.common_executed_population.eq(20).all()
    assert json.loads((tmp_path / "run1" / "event_run_summary.json").read_text())["capacity_violations"] == 0


def test_chronological_reader_rejects_wrong_stable_identity(tmp_path):
    carbon = _carbon()
    forecast = tmp_path / "forecast.csv"
    _forecasts(carbon).to_csv(forecast, index=False)
    workload = tmp_path / "bad.csv"
    _write_ordered(workload, [_task(2, 0, 1, 1)])
    text = workload.read_text().replace("trace-task-000000000002", "trace-task-000000000003")
    workload.write_text(text)
    import pytest
    with pytest.raises(ValueError, match="identity mismatch"):
        run_event_simulation(workload, carbon, forecast, tmp_path / "out", max_tasks=1)
