# TRACE Final Evaluation

## Scope and assumptions

This is the full-workload execution of 13,288,830 valid tasks in `results/validation/chronological_tasks.csv`. All three strategies used the same 8-core capacity, 3,600-second maximum delay, 10 W/core energy assumption, carbon input, forecast replay, and stable task IDs. Final emissions use observed IN-WE carbon intensity only. Forecast values are used for TRACE decisions, never for actual-emissions calculation. The run's saved hashes and parameters are in `results/phase6/full_real_20261111_run1/phase6_run_configuration.json`.

## Forecast eligibility and use

All three strategies classify 1,699,114 tasks as forecast-eligible and 11,589,716 as ineligible or lacking complete forecast coverage. Of the ineligible tasks, 11,589,436 lack a forecast origin and 280 have incomplete origin coverage. FIFO and earliest-feasible do not score forecasts.

TRACE recorded 11,649,044 fallback decisions: 253,870 decisions used the missing-origin fallback, 59,392 used the no-positive-risk-savings fallback, and 3 used the incomplete-origin-coverage fallback. It recorded 3 forecast-rescheduled decisions and 135.67 seconds of forecast scoring. The 59,395 no-positive-savings or forecast-rescheduled decisions are the covered decisions that reached forecast candidate scoring; other forecast-eligible tasks were not necessarily executed or scored because of release, capacity, and delay constraints. Forecast replay coverage is historical; this result does not establish that these forecasts would have been live and available at the corresponding decisions.

## Outcomes by strategy

| Strategy | Processed | Executed/completed | Deferred | Infeasible | Completion rate | Observed emissions, all scheduled tasks | Mean execution delay | Mean capacity utilization |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FIFO | 13,288,830 | 297,143 | 12,991,615 | 72 | 2.2360% | 9,176.9781 g CO₂e | 3,598.11 s | 88.93% |
| Earliest-feasible | 13,288,830 | 313,268 | 12,975,490 | 72 | 2.3574% | 9,226.8921 g CO₂e | 3,586.87 s | 89.40% |
| TRACE | 13,288,830 | 313,268 | 12,975,490 | 72 | 2.3574% | 9,226.7090 g CO₂e | 3,586.89 s | 89.40% |

All completed task intervals were covered by the observed carbon series in this evaluation. Consequently the scheduled and completed energy/emissions totals are equal for each strategy. Energy was 15.07839 kWh for FIFO and 15.15938 kWh for earliest-feasible and TRACE. There were zero pending tasks after lifecycle events drained. The 12.99 million deferred tasks exceeded available capacity within the permitted delay; the 72 over-capacity requests were infeasible. Maximum observed delay was 3,600 seconds for all strategies. The audit found zero CPU-capacity, release-time, delay, duration, or identity violations; maximum allocated capacity was 8 cores.

## Comparable populations and interpretation

The whole-run emission totals cover each strategy's own completed population, which differs in size from FIFO to the other two. Relative to FIFO's own population, earliest-feasible emissions are 49.9140 g (0.5439%) higher, and TRACE emissions are 49.7309 g (0.5419%) higher. This is not a like-for-like task comparison.

A strict common completed population contains 165,474 task IDs executed by all three strategies and fully covered by observed carbon under all three schedules. On this population, observed emissions are 4,553.7721 g for FIFO, 4,553.7716 g for earliest-feasible, and 4,553.5885 g for TRACE. TRACE is 0.1836 g (0.00403%) below FIFO on that common population. The difference is very small and does not support a broad claim of material superiority. Outcomes also reflect the small carbon timeline relative to the complete workload and the 3,600-second deferral limit.

## Independent reconciliation

An independent disk-backed audit streamed each schedule ledger against the full chronological workload. For every strategy it found 13,288,830 rows and unique IDs, zero duplicates, missing IDs, unexpected IDs, ID sequence errors, or task-ID/source-row identity errors. Ledger byte sizes match the completed checkpoint offsets, and the independent CPU capacity and task constraint audit found zero violations (peak allocated capacity: 8 cores). `independent_validation.json` records ledger hashes and populations; `cross_check_report.json` confirms row counts, task states, emissions coverage populations, energy, observed emissions, and checkpoint offsets agree with `final_evaluation.json`, `event_run_summary.json`, and the checkpoint database.

The state totals are mutually exclusive: completed means `executed`; pending at end is zero; rejected is the sum of `deferred` and `infeasible`. FIFO has 297,143 completed, 12,991,615 deferred, and 72 infeasible tasks. Earliest-feasible and TRACE each have 313,268 completed, 12,975,490 deferred, and 72 infeasible tasks. Duplicate-prevented and other states are zero. These counts sum to the full 13,288,830 task population for each strategy.

Energy and emissions were also recalculated from every executed ledger row using `duration_seconds × cpu_cores × 10 W ÷ 3,600,000` and the raw observed hourly IN-WE carbon series. The exact populations were 297,143 executed tasks for FIFO and 313,268 for each other strategy; every task interval was covered by the 216-row observed carbon series. Recomputed energy was 15.0783901389 kWh for FIFO and 15.1593752778 kWh for earliest-feasible and TRACE. Recomputed observed emissions were 9,176.978087361686 g CO₂e, 9,226.892076389484 g CO₂e, and 9,226.708951389484 g CO₂e, respectively. Maximum per-task differences from stored ledger energy and emissions were below 5.6e-17 kWh and 5.7e-14 g. The recalculation report is `results/phase6/independent_validation/emissions_recalculation.json`.

## Forecast limitations

The forecast data consist of historical rolling-origin replay, not forecasts captured live at run time. Forecast eligibility identifies replay coverage, not operational availability. Forecast uncertainty intervals were used by the risk-aware scoring logic but were not established as statistically calibrated. Forecast use was sparse (3 forecast-rescheduled decisions) and scoring/fallback behavior should not be generalized as evidence of forecast superiority.

## Machine-readable artifacts

- Full metrics and populations: `results/phase6/full_real_20261111_run1/final_evaluation.json`
- Strategy summary table: `results/phase6/full_real_20261111_run1/final_evaluation_by_strategy.csv`
- Engine decision/fallback details: `results/phase6/full_real_20261111_run1/event_run_summary.json`
- Run configuration and hashes: `results/phase6/full_real_20261111_run1/phase6_run_configuration.json`
- Independent ledger reconciliation and hashes: `results/phase6/independent_validation/independent_validation.json`
- Engine, checkpoint, and evaluation comparison: `results/phase6/independent_validation/cross_check_report.json`
- Per-task energy and observed-carbon recalculation: `results/phase6/independent_validation/emissions_recalculation.json`
- Completion and progress logs: `phase6_completion.json`, `phase6_progress.jsonl`

No uncertainty calibration or deployment performance claim is made. The historical forecast replay, workload-to-carbon alignment, carbon coverage, and modeled constant power-per-core are scientific limitations.

## Verification caveat

The preflight reports hash the normalized IN-WE timestamp/intensity table; the run configuration hashes raw CSV bytes. The current normalized table matches the preflight/checkpoint hash, and current raw bytes match the run-configuration hash. This is a representation difference, not evidence that carbon values changed. See `TRACE_CARBON_HASH_RECONCILIATION.md`. Provider retrieval and license details remain incomplete.
