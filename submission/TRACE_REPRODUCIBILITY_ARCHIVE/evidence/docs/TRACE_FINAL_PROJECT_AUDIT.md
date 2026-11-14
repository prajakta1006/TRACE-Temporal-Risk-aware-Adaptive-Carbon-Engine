# TRACE Final Project Audit

## Audit scope and evidence

This audit covers the checked-out `feat/final-integration` tree, implementation under `src/`, tests, scripts, data manifests/files available in the workspace, phase documentation, and persisted Phase 6 outputs. The current branch points at commit `6782069` (`Add rolling forecasts and scheduler integration`); that history does not itself contain the complete Phase 6 work in a clean upstream branch, so this report treats the present working tree and local artifacts as the submission state. No full simulation was rerun for this audit.

Primary evidence is `results/phase6/independent_validation/independent_validation.json`, `cross_check_report.json`, and `emissions_recalculation.json`, alongside the completed run checkpoint, three schedule CSVs, `event_run_summary.json`, `final_evaluation.json`, completion/progress logs, the Phase 2 workload validation report, and rolling forecast evaluation outputs. The large datasets and results are local and ignored by Git; a clean clone cannot reproduce the full-scale run without separately supplied inputs/artifacts.

## Completed components

| Component | Implementation | Evidence / status |
|---|---|---|
| Workload ingestion and cleaning | `src/data/load_workload.py`, `validate_data.py` | Data integration and smoke tests; schema validation and unit conversion. |
| Full workload validation and stable identity | `src/data/validate_workload_stream.py`, `task_identity.py` | 13,288,830 valid unique rows; zero invalid/duplicate rows; external chronological ordering; stable source-row IDs. |
| Carbon preparation and energy/emissions | `src/data/prepare_carbon.py`, `energy_model.py`, `integrate_emissions.py` | 216 hourly IN-WE records; assumed 10 W/core model; independent Phase 6 row-wise recalculation passed. |
| Forecast models and replay | `src/forecasting/`, `src/evaluation/forecast_validation.py` | Seasonal-naive rolling replay and model comparison utilities; persisted replay has 160 forecast rows. |
| Scheduling policies | `src/scheduler/event_engine.py` and supporting modules | FIFO, earliest-feasible, and TRACE ran over the entire validated population. |
| Checkpoint, identity guard, and recovery | `event_engine.py`, `preflight.py` | Completed SQLite checkpoint; interruption/resume recorded; test coverage includes rollback and compatibility checks. |
| Evaluation and independent reconciliation | `src/evaluation/phase6_execution.py`, `scripts/verify_phase6_ledgers.py`, `cross_check_phase6.py`, `verify_phase6_emissions.py` | All three ledgers pass row/ID/sequence/constraint checks; report offsets and hashes; cross-check passes. |
| Test suite | `tests/` | `93 passed`; one third-party `dateutil` deprecation warning using the dedicated Windows temp/cache locations. |

## Data sources and schemas

The main workload is `data/processed/workload/workload_cleaned.csv`; the validated, sorted simulation input is `results/validation/chronological_tasks.csv`. The latter contains 13,288,830 rows with `source_row`, `task_id`, job/task identity, `start_time`, `end_time`, `duration_seconds`, `duration_hours`, and `cpu_cores`. Ordering is by `(start_time, task_id)`. Stable IDs are `trace-task-{source_row:012d}`. The original row identity rule deduplicates valid `(job_name, task_name)` pairs, retaining the earliest valid source record.

The principal carbon input is `data/raw/carbon/india_west_carbon_intensity.csv`, zone IN-WE, with `datetime`, `carbonIntensity`, and metadata fields such as `emissionFactorType`, `flowTraced`, and `isEstimated`. It has 216 continuous hourly UTC observations from 2026-09-22 00:00 through 2026-09-30 23:00 UTC. Repository provenance attributes it to Electricity Maps but lacks a recorded original retrieval URL/date/API version/license; the unit is documented as gCO2eq/kWh but is not embedded in the CSV schema. Additional January 2025 carbon files have unverified zone/units/provenance and half-hour intervals; they are excluded from the main series.

`results/forecasting/rolling_seasonal_naive_forecasts.csv` holds origin, target, horizon, prediction, lower/upper bounds, actual, and coverage fields. It contains 40 origins × 4 leads = 160 historical replay rows. It is a local generated artifact, not checked in.

## Algorithms and constraints

FIFO preserves chronological arrival order and prevents later tasks from taking an earlier committed start; it chooses the earliest capacity-feasible slot consistent with that floor. Earliest-feasible chooses the earliest capacity-feasible start at or after release, allowing backfill where capacity permits. TRACE uses the same event-based capacity calendar, but first scores covered hourly candidate starts using forecast carbon and a risk penalty. It is non-preemptive: assignments are not moved after commitment. An individual CPU request above the 8-core capacity is infeasible. A task with no slot by `release + max_delay` is deferred. Task release time, duration, maximum delay, CPU capacity, stable IDs, and final observed-carbon coverage are audited independently.

For energy `E`, baseline prediction `p_b`, candidate prediction `p_c`, upper bounds `u_b,u_c`, and risk weight `λ`, the implementation computes `S = E(p_b-p_c) - λE[(u_b-p_b)+(u_c-p_c)]`. It chooses the highest positive-scoring forecast candidate that also fits capacity and deadline; otherwise it uses earliest feasible placement and records a fallback reason. This is a local heuristic, not a global optimizer or calibrated risk guarantee. Forecast predictions inform placement only. Final emissions use observed carbon intensity.

## Experiment and verified result

The full run processes the same 13,288,830 task identities in all three policies under 8 cores, 3,600-second maximum delay, four-hour horizon, risk weight 0.5, and 10 W/core. All three independent ledger validations passed: 13,288,830 unique IDs, zero duplicates, missing, unexpected, sequence, or source-row identity errors; every file size agrees with the corresponding completed checkpoint offset. Capacity and task-constraint violations are zero.

| Policy | Completed | Deferred | Infeasible | Observed emissions over its completed population |
|---|---:|---:|---:|---:|
| FIFO | 297,143 | 12,991,615 | 72 | 9,176.9781 g CO2e |
| Earliest-feasible | 313,268 | 12,975,490 | 72 | 9,226.8921 g CO2e |
| TRACE | 313,268 | 12,975,490 | 72 | 9,226.7090 g CO2e |

The common population completed by all strategies contains 165,474 task IDs. Its observed emissions are 4,553.7721 g (FIFO), 4,553.7716 g (earliest-feasible), and 4,553.5885 g (TRACE). The TRACE difference from FIFO is 0.1836 g, or about 0.00403%, and is not evidence of broad or material superiority. Whole-run populations differ in size; their total emissions are not a like-for-like comparison.

The emissions verification independently recomputed each executed task's energy from duration, CPU allocation, and 10 W/core, then integrated energy proportionally across the occupied hours using the raw IN-WE observations. It passed for 297,143 FIFO completions and 313,268 completions for each other strategy; all those scheduled intervals are within the observed series.

TRACE classifies 1,699,114 tasks as forecast replay eligible and 11,589,716 as ineligible (11,589,436 missing origin; 280 incomplete origin coverage). It recorded 11,649,044 fallback decisions, including 253,870 missing-origin, 59,392 no-positive-risk-savings, and 3 incomplete-origin fallbacks; three forecast reschedules were recorded. Eligibility is forecast coverage, not scoring or execution. FIFO and earliest-feasible do not use forecasts.

## Resource and recovery evidence

The run reports 10,127.16 accumulated scheduler seconds, 6,867.74 seconds for the resumed invocation, 5,714.21 seconds in the recovery session, and 111,738,880 bytes peak RSS. The wall-clock field reflects the resumed invocation and does not include the full interruption gap. Schedule CSVs total 7,958,428,511 bytes. The completed checkpoint database was 920,371,200 bytes; the separate independent-validation SQLite ID index is 1,721,425,920 bytes. The run was interrupted after a durable 5.3-million-task checkpoint and resumed after compatibility checks; the progress log records the interruption and completion. Do not interpret scheduler runtime as uninterrupted wall-clock elapsed time.

## Limitations and discrepancies

- The power-per-core value is assumed, not measured; server idle power, memory, I/O, cooling, and facility overhead are excluded.
- Forecasts are a historical replay from short, correlated carbon data. There is no operational log proving forecasts were available at those simulated decision times.
- The nominal 90% uncertainty interval is based on 43 calibration residuals and observed 100% coverage over 160 correlated predictions; this does not establish formal future calibration.
- Workload seconds are mapped by index onto a nine-day carbon series; workload calendar timestamps are not aligned to the carbon calendar.
- Preflight and run-configuration carbon hashes use different representations; current normalized values and raw bytes match their respective recorded hashes. The preflight JSON omits its carbon path, so exact historical file selection cannot be proven from that report alone. Original provider retrieval and license provenance remain incomplete.
- The scenario is a constrained simulation, not production execution or measured emissions savings. It does not establish broad TRACE superiority.
- The forecast evaluation JSON from an earlier phase retains a stale limitation string “full simulation not run.” It has not been modified; Phase 6 completion and ledger evidence are authoritative for execution status.

## Reproducibility

Full-scale source datasets and outputs are local, ignored files. Use `docs/TRACE_REPRODUCIBILITY_AND_RUNBOOK.md` for safe commands. Do not invoke an unbounded full-run command unless intentionally reproducing the full experiment with adequate disk space and the exact validated inputs. Independent evidence is stored in `results/phase6/independent_validation/` and should be retained with the run.
