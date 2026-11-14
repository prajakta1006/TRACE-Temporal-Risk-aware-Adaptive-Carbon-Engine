# Person 4 — Final Integration and End-to-End Simulation

> Historical integration-phase record. Its bounded samples and “full-scale not established” statements describe that phase only. Phase 6 later completed the full run; use `TRACE_PHASE6_EXECUTION.md` and `TRACE_FINAL_EVALUATION.md` for final results.

## Architecture and data flow

`src.main` loads the carbon timeline and rolling forecast file, streams workload CSV chunks for the bounded sample, normalizes workload identifiers and units, computes CPU energy with the configured W/core assumption, and calls `src.simulation.run_simulation`. The simulator runs three policies over exactly the same rows:

1. **FIFO** processes input row order.
2. **Earliest feasible** processes tasks by release time and stable input order.
3. **TRACE** uses the existing rolling-origin scheduler when a task's complete baseline duration and forecast origin are covered; otherwise it retains the earliest capacity-feasible placement.

All assignments are non-preemptive and immutable. Each task gets one planning decision at the hourly forecast origin immediately preceding its release hour. Previously assigned tasks remain reservations, including running tasks and future committed tasks. Capacity is validated before each placement. An individual CPU request above configured capacity is recorded as infeasible. A task that cannot fit by release plus maximum delay, or whose completion extends beyond observed carbon coverage, is deferred.

The ledger has one row per task and policy, with task ID, original fields, planned interval, execution state, decision reason, delay, and forecast status. The same task IDs are carried through all strategy runs. The reported common-population carbon comparison uses IDs executed by all three strategies, so a policy cannot claim lower emissions just by omitting tasks. Per-strategy completion metrics still account for every input row.

## Energy and carbon evaluation

Energy is estimated as `duration_seconds × cpu_cores × power_per_core_watts / 3,600,000`. The default is 10 W per allocated CPU core, an experiment assumption. It excludes idle server, memory, network, storage, cooling, and power-delivery overhead.

Task energy is split proportionally across each hourly interval occupied by its scheduled execution. Emissions are energy multiplied by **observed** carbon intensity in g CO2e/kWh. Predictions are used only to choose a TRACE assignment; evaluation never substitutes predicted intensity for observed intensity.

Metrics include energy, observed emissions, savings and reduction versus FIFO on the common executed population; scheduled, executed, deferred and infeasible counts; average and maximum delay; capacity violations; forecast-eligible and out-of-coverage task counts; and successful reschedules. A reschedule is counted only when an alternative assignment is recorded and executes inside the observed carbon timeline.

## Forecast coverage and timeline assumptions

The rolling forecast file contains historical replay forecasts: 40 origins and four target hours per origin (160 rows). These predictions were generated from the same short carbon record using the existing 24-hour seasonal-naive method. They are not future live forecasts. TRACE selects predictions only from the matching recorded origin and never fills missing origins by carrying values forward.

Carbon is mapped to simulation seconds by chronological row: hour 0 is the first timestamp in the selected zone. Workload start and duration values are seconds on this relative timeline. No claim is made that workload source time corresponds to the carbon dataset's actual calendar time. The additional carbon files cover January 2025, use 30-minute records, have no zone field in their schema, and overlap one another. The primary IN-WE timeline is September 2026. They are not combined because their zone/provenance and relation to the primary series are unverified. Extending the evaluation requires deduplication, interval aggregation, source/unit validation, and a defensible workload timeline mapping first.

The bounded default sample scans workload chunks and selects up to 500 tasks that overlap available forecast target hours, avoiding an unrepresentative early-only sample. It is a development/reproducibility run, not a full-workload performance claim. `--mode full` explicitly loads the full chosen population and can use substantial memory and runtime; `--max-tasks` bounds it. Full trace throughput has not been established for 13.29 million rows.

## Experimental assumptions and baselines

Defaults are zone IN-WE, 8 CPU cores, 10 W/core, four-hour forecast horizon, one-hour maximum scheduling delay, and risk weight 0.5. Each is configurable. Sensitivity analysis evaluates risk weights 0.0, 0.1, 0.2, 0.3, 0.5, 1.0; CPU capacities 4, 8, 12; delays 0, 1800, 3600 seconds; horizons 1–4 hours; and power assumptions 5, 10, 20, 30 W/core. Power affects recomputed task energy in every policy.

Risk weight scales the scheduler's existing uncertainty penalty. Higher weights require stronger predicted carbon benefit after accounting for the forecast upper-bound interval and can therefore reduce accepted reschedules. This is the scheduler's heuristic, not a calibrated probability-of-loss guarantee. Sensitivity outputs are generated from the actual simulation run and are not pre-filled with expected results.

## Results generated during integration

The bounded default run selected 500 tasks from the first 100,000 workload rows scanned, balanced between 250 tasks overlapping forecast target hours and 250 outside that target coverage. All 500 executed in each policy, no capacity violation was reported, and all 250 forecast-window tasks had usable origins and baseline hours. With the default risk weight 0.5, TRACE accepted no reschedules; the three strategies therefore had the same common-population energy (0.035535 kWh) and observed emissions (21.662508 g CO2e). This is a small sample and is not evidence of full-workload savings.

A separate sensitivity run used 100 sampled tasks, balanced between forecast-covered and uncovered rows. At risk weight 0.0, TRACE executed 5 reschedules and reported 0.001081 g CO2e savings (0.03046%) against FIFO on the common executed population; average delay was 108.21 seconds and maximum delay was 2,564 seconds. At weights 0.1, 0.2, 0.3, 0.5, and 1.0, no reschedule passed the risk-adjusted benefit threshold in that sample. In the power sweep, estimated energy and emissions scaled linearly with the assumed W/core setting: at 5 W/core the sample used 0.002707 kWh and emitted 1.773840 g CO2e; at 30 W/core it used 0.016242 kWh and emitted 10.643041 g CO2e. These are actual outputs from the configured historical replay, not measured system energy.

`results/evaluation/strategy_comparison.csv`, the risk, CPU, delay, horizon, and power sensitivity CSVs, and the PNGs contain run outputs. Re-run the commands for a different sample or parameter configuration; the generated files are local and ignored by Git.

FIFO preserves workload row order. Earliest-feasible uses stable release-time order. Both use the same capacity and delay constraints as TRACE. Infeasible CPU requests are excluded from executed emissions but remain in task accounting. For carbon comparisons, all policies are evaluated on their common executed task IDs; completion metrics disclose any non-common rows.

## Outputs and reproduction

From the repository root:

```powershell
py -m pip install -r requirements.txt
py -m src.main
py -m src.main --mode small --max-tasks 250
py -m src.main --mode full
py -m src.main --mode sensitivity --max-tasks 100
py -m src.main --mode report
py -m pytest -q
```

CSV outputs are written under `results/simulation/`, `results/evaluation/`, and `results/experiments/`. PNG figures are under `results/figures/`. `simulation_report.md` is generated from the evaluation CSV; no result values should be copied into a paper or report before running the command on the intended workload and configuration.

## Known limitations

- The default run is a bounded sample, and full-scale runtime and memory use have not been benchmarked.
- Historical forecast replay has narrow coverage and cannot support carbon-aware decisions over most of the 216-hour carbon record. Tasks outside that coverage use the non-carbon-aware feasible placement and are counted.
- Calendar alignment between the workload and carbon data is a relative simulation assumption.
- The 10 W/core model is intentionally simple; reported energy and emissions are estimates.
- Tasks are not preempted. Assignments are committed once and are not moved by later replanning.
- The four-hour prediction data supports horizons 1–4 only.
- Extra carbon datasets are not combined due overlapping half-hour timestamps and different provenance.
- Risk uncertainty uses the existing upper-bound penalty heuristic; empirical interval coverage from a short historical record does not guarantee future calibration.
- The simulator's full-population mode is an explicit resource-intensive run; the default is bounded and chunked.
