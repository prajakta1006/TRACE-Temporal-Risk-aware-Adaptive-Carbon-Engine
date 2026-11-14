from src.evaluation.phase6_execution import evaluate_completed_run
from src.evaluation.phase6_execution import _run_stage_suite, verify_recovery_equivalence
from src.scheduler.event_engine import EventSchedulerConfig, run_event_simulation
from tests.test_event_checkpoint import _inputs, _run


def test_streaming_evaluator_reports_common_and_whole_run_populations(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    output = tmp_path / "all-strategies"
    _run(workload, carbon, forecast, output)

    result = evaluate_completed_run(output)

    assert result["tasks_processed"] == 8
    assert set(result["strategy_results"]) == {"fifo", "earliest_feasible", "trace"}
    assert result["common_population"]["common_executed_tasks"] >= 0
    assert all(metrics["capacity_violations"] == 0 for metrics in result["strategy_results"].values())
    assert (output / "final_evaluation_by_strategy.csv").is_file()


def test_stage_runner_records_prefix_and_resume_recovery(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path, [i * 100 for i in range(20)])
    carbon_path = tmp_path / "carbon.csv"
    carbon.assign(
        zone="IN-WE",
        datetime=carbon.timestamp.astype(str),
        carbonIntensity=carbon.carbon_intensity,
    )[["zone", "datetime", "carbonIntensity"]].to_csv(carbon_path, index=False)

    result = _run_stage_suite(
        workload, carbon_path, forecast, tmp_path / "stage-run",
        EventSchedulerConfig(max_delay_seconds=3600), sizes=(20,),
        checkpoint_interval=2, resume_test_size=20,
    )

    trace = result["stages"]["prefix_20"]["strategy_results"]["trace"]
    assert trace["tasks_processed"] == 20
    assert trace["interrupted"] is True
    assert trace["interruption_checkpointed_tasks"] == 10
    assert trace["recovery_wall_seconds"] >= 0
    assert (tmp_path / "stage-run" / "run_log.jsonl").is_file()


def test_recovery_equivalence_compares_resumed_ledger_to_fresh_run(tmp_path):
    workload, carbon, forecast = _inputs(tmp_path)
    carbon_path = tmp_path / "carbon.csv"
    carbon.assign(
        zone="IN-WE",
        datetime=carbon.timestamp.astype(str),
        carbonIntensity=carbon.carbon_intensity,
    )[["zone", "datetime", "carbonIntensity"]].to_csv(carbon_path, index=False)
    config = EventSchedulerConfig(max_delay_seconds=3600)
    resumed = tmp_path / "resumed"
    run_event_simulation(
        workload, carbon, forecast, resumed, config, max_tasks=8,
        strategies=("trace",), checkpoint_interval=2,
        interrupt_after_tasks=5,
    )
    run_event_simulation(
        workload, carbon, forecast, resumed, config, max_tasks=8,
        strategies=("trace",), checkpoint_interval=2, resume=True,
    )

    equivalence = verify_recovery_equivalence(
        workload, carbon_path, forecast, resumed, tmp_path / "reference",
        config, max_tasks=8, checkpoint_interval=2,
    )

    assert equivalence["equivalent"] is True
    assert equivalence["task_decision_ledger_identical"] is True
