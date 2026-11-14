# TRACE Scientific Methodology and Results

## Research question and motivation

Electricity-grid carbon intensity changes over time. A deferrable, non-preemptive compute task can sometimes move within a deadline to a lower-carbon interval while respecting shared CPU capacity. TRACE tests a forecast-guided placement policy against two non-forecast baselines. This is a simulation study of one workload and one short carbon trace; it is not a production deployment or a measurement of actual server electricity.

The central question is whether a local risk-aware carbon forecast can select feasible task start times that reduce observed-carbon emissions without confusing fewer completed tasks with lower emissions. Therefore the evaluation reports both each strategy's own completed population and a strict common completed-ID population.

## Data and preprocessing

The workload is a cleaned set of 13,288,830 records. Streaming validation found zero structurally invalid rows, zero duplicate `(job_name, task_name)` identities, and zero missing values in the validated input. It externally sorts by release time and deterministic task ID. Seventy-two tasks request more than the configured eight cores; they remain represented and are marked infeasible rather than dropped.

The principal carbon series has 216 hourly UTC observations in zone IN-WE. The carbon values are consumed as gCO2e/kWh per project documentation and source field, although units and retrieval details are not embedded in the CSV. The two separate January 2025 datasets have half-hour records and lack verified zone/unit provenance; neither was merged with the main series.

The simulator maps carbon row 0 to simulation hour 0 and interprets workload start times as seconds from that relative origin. This index mapping is a modeling convention, not a claim that workload calendar time coincides with September 2026. The persisted forecast replay has 40 origins and four leads per origin, all within the observed-data tail.

## Forecast methodology and validation

The persisted model is a 24-hour Seasonal Naive predictor: for target index `t`, `ŷ_t = y_(t-24)`. Forecasts are produced at historical rolling origins for leads 1–4. The time series is partitioned chronologically: indices 0–128 are initial history, indices 129–171 form a 43-observation calibration segment, and the rolling replay begins at index 172. A fixed absolute-error threshold is selected at rank `ceil((43+1)×0.9)=40`; bounds are prediction ± threshold, with the lower bound clipped at zero.

The rolling evaluation contains 160 predictions (40 origins × 4 leads). Reported per-horizon MAEs are 6.275, 6.000, 6.075, and 6.150 gCO2e/kWh for horizons 1–4; all-lead MAE is 6.125 and RMSE 6.946. The corresponding persistence MAEs are 19.075, 36.975, 54.375, and 71.125; the all-lead mean is 45.388. The replay reports 100% interval coverage and mean width 158 over these 160 temporally correlated predictions. The calibration sample is small and serially dependent; the result does not demonstrate formally calibrated future intervals or nominal 90% coverage. The replay file has no operational issue-time log, so eligibility means historical replay coverage only.

TRACE eligibility requires a forecast origin with complete forecast coverage of every baseline task-occupied hour. In the complete workload, 1,699,114 tasks meet that replay-coverage definition; 11,589,436 have no origin and 280 have incomplete origin coverage. These counts do not mean every eligible task was scored: release/deadline, CPU contention, and feasibility influence whether a decision can use candidates.

## Scheduling algorithms

All strategies consume the same chronological input stream and use non-preemptive interval reservations on an eight-core event calendar. A task cannot start before its release. Its start may be delayed up to 3,600 seconds. A request above eight cores is infeasible. If no slot fits before its deadline, the task is deferred.

- **FIFO:** choose the earliest capacity-feasible placement while preserving a nondecreasing committed-start floor in input order.
- **Earliest-feasible:** choose the earliest capacity-feasible placement at or after release; this policy may backfill around future reservations when capacity allows.
- **TRACE:** identify the historical origin preceding the task release hour, score feasible hourly starts within the forecast horizon/deadline, and accept only a candidate with positive risk-adjusted savings. If no usable candidate is selected, use earliest-feasible placement and record the fallback cause.

The forecast scoring implemented in `src/scheduler/carbon_benefit.py` is a local ranking heuristic. Given estimated task energy `E`, baseline/candidate forecasts `p_b,p_c`, forecast upper bounds `u_b,u_c`, and configured `λ`,

`R(b,c) = E(p_b-p_c) - λE[(u_b-p_b)+(u_c-p_c)]`.

TRACE selects the highest-ranked positive score among candidate starts that fit the current CPU reservations and deadline. This is not a global schedule optimizer, and `λ` is not a probability calibration parameter. If the candidate fails feasibility or no score is positive, the scheduler falls back. Predicted intensity is never substituted for observed intensity in final evaluation.

## Energy and observed emissions

For duration `d` seconds, allocated CPU `c` cores, and assumed power `P=10 W/core`, estimated energy is

`E_kWh = d × c × P / 3,600,000`.

This is an assumption, not telemetry. For a task scheduled from `s` to `s+d`, task energy is allocated proportionally to each occupied hour `h`. With observed hourly intensity `I_h`,

`CO2e_g = Σ_h E_kWh × overlap_h/d × I_h`.

The independent emissions checker recomputed energy and hourly emissions for every executed ledger row from task duration, CPU, scheduled interval, and the raw IN-WE carbon CSV. Its exact populations were all executed tasks for each strategy: 297,143 FIFO rows and 313,268 rows for each other strategy. Every one of those intervals was observed-carbon-covered. Recomputed totals match stored values to floating-point precision. No emissions are imputed outside observed coverage.

## Experimental protocol and results

The completed run used all 13,288,830 validated tasks, 8-core capacity, 3,600-second maximum delay, horizon 4 hours, risk weight 0.5, and 10 W/core. All policies processed the same identity sequence. The checkpoint records completion; three ledgers independently pass exact count, uniqueness, identity sequence, source-row mapping, offset, and capacity/task-constraint checks.

| Strategy | Processed | Completed | Pending | Deferred | Infeasible | Completion | Mean delay of completed | Mean CPU utilization | Energy (kWh) | Observed emissions (g CO2e) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FIFO | 13,288,830 | 297,143 | 0 | 12,991,615 | 72 | 2.2360% | 3,598.11 s | 88.93% | 15.078390 | 9,176.9781 |
| Earliest-feasible | 13,288,830 | 313,268 | 0 | 12,975,490 | 72 | 2.3574% | 3,586.87 s | 89.40% | 15.159375 | 9,226.8921 |
| TRACE | 13,288,830 | 313,268 | 0 | 12,975,490 | 72 | 2.3574% | 3,586.89 s | 15.159375 | 9,226.7090 |

Deferred and infeasible are disjoint ledger states. Rejected counts are their sum; no task is double-counted. Duplicate-prevented and other states are zero. End-of-run pending is zero because lifecycle events are drained before completion.

TRACE records 1,699,114 forecast-eligible and 11,589,716 forecast-ineligible rows, 11,649,044 fallbacks (253,870 missing-origin, 59,392 no-positive-risk-savings, 3 incomplete-origin), and three forecast-rescheduled decisions. It spent 135.67 seconds in forecast scoring. Eligibility is a dataset coverage count, fallback is a decision count, and forecast reschedules are a separate decision subset; these metrics have different denominators and must not be conflated.

### Unequal and common populations

Each strategy's full-outcome emissions sum its own completed tasks, so FIFO's population (297,143) is smaller than the other policies' (313,268). Earliest-feasible's total is 49.9140 g (0.5439%) above FIFO's total; TRACE's is 49.7309 g (0.5419%) above. These are not like-for-like task comparisons and do not show that either policy worsens emissions on identical work.

The common completed population is the 165,474 IDs executed by all three strategies and fully covered by observed carbon under all three schedules. Emissions are 4,553.7721 g for FIFO, 4,553.7716 g for earliest-feasible, and 4,553.5885 g for TRACE. TRACE is 0.1836 g (0.00403%) below FIFO on this common set. Earliest-feasible is 0.00049 g below FIFO. The TRACE difference is tiny and does not establish material superiority. Completion rate is identical between TRACE and earliest-feasible; their observed emissions differ because their scheduled timing differs slightly.

## Runtime, memory, and storage

Recorded accumulated scheduler runtime is 10,127.16 seconds; the resumed invocation reports 6,867.74 seconds and recovery-session runtime is 5,714.21 seconds. The interrupted wall-clock gap is not captured by those scheduler-runtime values. Peak recorded RSS is 111,738,880 bytes (106.5 MiB). The three output ledgers occupy 7,958,428,511 bytes in total. The engine checkpoint database is 920,371,200 bytes. The separate disk-backed validation ID index is 1,721,425,920 bytes. Retain input, outputs, checkpoint, progress log, and independent reports together for auditability.

## Threats to validity and limitations

1. **Energy model:** fixed 10 W/core excludes measured system and facility power.
2. **Forecast realism:** replay does not prove live availability, and observed intervals do not establish future calibration.
3. **Short time series:** nine days of carbon data and 43 calibration residuals limit external validity.
4. **Timeline alignment:** workload seconds are mapped to carbon indices rather than verified real dates.
5. **Objective scope:** the metric is operational emissions under an assumed energy model; embodied hardware, cooling, and other resources are out of scope.
6. **Baseline/policy scope:** conclusions apply to these policy implementations, parameters, data, and task mix only.
7. **Provenance:** preflight hashes the normalized carbon timeline while the run configuration hashes raw CSV bytes. Current inputs match both respective hashes; original retrieval and license records remain incomplete.
8. **External validity:** simulation does not establish production throughput, service-level behavior, or measured real-world emissions reductions.

## Conclusion

The full run and independent ledgers establish that TRACE completed the same 13.29-million-row input as earliest-feasible, with no audited capacity or task-constraint violations. Its common-population emissions are marginally lower in this run, by 0.00403% versus FIFO, while whole-run emissions totals cover different populations. Sparse forecast rescheduling, replay limitations, and the assumed energy model prevent a general superiority or deployment claim.

## References

1. Green Software Foundation, [Software Carbon Intensity specification](https://sci.greensoftware.foundation/), version 1.1.0. Background framing only; this project does not claim an SCI score.
2. Electricity Maps, [Carbon intensity API documentation](https://app.electricitymaps.com/docs/reference/carbon-intensity), defining carbon-intensity units and data concepts. The local CSV's original retrieval metadata remains incomplete.
3. Angelopoulos, A. N. and Bates, S. (2023), [Conformal Prediction: A Gentle Introduction](https://arxiv.org/abs/2107.07511), Foundations and Trends in Machine Learning. The exchangeability conditions behind conformal coverage are not established for this short dependent time series.
4. Gibbs, I. and Candès, E. (2021), [Adaptive Conformal Inference Under Distribution Shift](https://arxiv.org/abs/2106.00170), Advances in Neural Information Processing Systems. Included as background for why nonstationarity requires explicit treatment; not implemented by TRACE.
5. Henderson, P. et al. (2020), [Towards the Systematic Reporting of the Energy and Carbon Footprints of Machine Learning](https://arxiv.org/abs/2002.05651), Journal of Machine Learning Research 21(248). Measurement and reporting context; TRACE's energy is modeled rather than measured.

## Reproducibility

See `docs/TRACE_REPRODUCIBILITY_AND_RUNBOOK.md`. The full workload, raw carbon file, forecasts, ledgers, checkpoint, and reports are not tracked by Git. Reproduction requires the corresponding local files, matching hashes, software environment, and substantial output disk. Never launch the full run merely by following a quick-start command.
