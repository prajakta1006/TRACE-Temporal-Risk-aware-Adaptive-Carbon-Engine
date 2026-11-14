# TRACE: Temporal Risk-aware Adaptive Carbon Engine

## 1. Title

**TRACE: Temporal Risk-aware Adaptive Carbon Engine**
Final academic project report
Team: [TEAM MEMBER 1 — FULL NAME]; [TEAM MEMBER 2 — FULL NAME]
Institution/department: [INSTITUTION / DEPARTMENT]
Supervisor: [SUPERVISOR NAME, IF REQUIRED]

## 2. Abstract

TRACE is a Python simulation system for deadline-bounded, non-preemptive workload scheduling against changing electricity carbon intensity. It combines a rolling Seasonal Naive forecast replay, a local uncertainty-penalized candidate ranking, CPU capacity checks, disk-backed checkpoints, and observed-carbon evaluation. A full-scale run processed 13,288,830 validated tasks under FIFO, earliest-feasible, and TRACE policies. Independent disk-backed reconciliation verified all three output ledgers: each contained 13,288,830 unique expected IDs in the correct sequence, matched checkpoint byte offsets, and passed CPU/task constraint audits. A separate row-wise calculation reproduced energy and observed-carbon emissions from the 10 W/core assumption and raw IN-WE carbon data.

FIFO completed 297,143 tasks; earliest-feasible and TRACE completed 313,268 each. On the 165,474 IDs completed by all three policies, TRACE emissions were 0.1836 g CO2e (0.00403%) below FIFO. This difference is small and specific to this workload and configuration. The energy model is assumed rather than measured, forecasts are historical replay rather than operational forecasts, and the workload-to-carbon calendar mapping is relative. The evidence demonstrates an auditable full-scale simulation, not production savings or general TRACE superiority.

## 3. Introduction

Electricity carbon intensity varies over time and location. If a task has a valid deadline and execution flexibility, choosing a different start time can alter the carbon intensity associated with its estimated energy. This project implements and evaluates a scheduling policy that uses carbon forecasts while respecting resource and delay constraints.

TRACE is a research prototype. It is intentionally compared with non-carbon-aware baseline policies on identical stable task identities. The experiment distinguishes completion outcomes from emissions and uses a common completed-task population to avoid attributing apparent savings to work that one policy did not execute.

## 4. Background and Motivation

Carbon-aware computing schedules flexible demand in response to grid carbon conditions. A scheduler must balance potential carbon benefit against deadlines and shared resources. Forecast uncertainty matters because a forecast-guided delay can be harmful when the candidate hour is not actually cleaner.

TRACE operationalizes these concepts with a limited four-hour forecast replay, CPU interval reservations, and a configurable penalty based on forecast upper bounds. It does not model regional migration, renewable certificates, facility power, grid response, or embodied emissions. The Green Software Foundation's Software Carbon Intensity specification provides broader software-impact context; TRACE does not report an SCI score.

## 5. Problem Statement

Given a chronologically ordered set of tasks `i`, each task has release time `r_i`, duration `d_i`, and CPU demand `c_i`. A selected start `s_i` must satisfy release, deadline, CPU capacity, and non-overlap constraints. The experiment estimates task energy from CPU-seconds and associates that energy with observed hourly carbon intensity. TRACE uses forecast values for its decisions; actual outcome evaluation uses observed values.

The study asks whether the implemented TRACE policy changes feasible schedules and observed-carbon outcomes compared with FIFO and earliest-feasible placement on this workload. The study does not claim the selected policy is globally optimal.

## 6. Research Objectives

1. Implement event-based, non-preemptive scheduling for three policies.
2. Apply a historical rolling forecast replay and risk-aware local candidate score.
3. Preserve every valid task's stable identity through scheduling and recovery.
4. Compare task outcomes, delays, utilization, assumed energy, and observed emissions.
5. Verify output ledgers independently against workload identity and checkpoint state.

## 7. Research Questions

- Can a forecast-guided scheduler complete the validated workload while respecting CPU and delay constraints?
- How do TRACE's completion and observed-emissions outcomes compare with FIFO and earliest-feasible?
- Do conclusions change when emissions are evaluated on the strict common completed-task population?
- Can a full-scale run resume and produce ledgers whose identity sequence agrees with the validated input?

## 8. System Requirements

The implemented system requires Python 3.10 or newer and the dependencies in `requirements.txt`: NumPy, pandas, scikit-learn, Matplotlib, psutil, and pytest. The verified machine used Python 3.13.3 on Windows. Full-scale reproduction additionally requires the ignored local workload, carbon, and forecast files plus enough disk for three ledgers and SQLite state. No external credential is needed for offline execution. The repository does not contain the full datasets or run artifacts.

## 9. Dataset Description

The validated chronological workload contains 13,288,830 records with source row, stable ID, job/task identity, relative start/end, duration, and CPU demand. The input was externally sorted by `(start_time, task_id)`. Validation recorded zero invalid rows, duplicate identities, or missing required values. Seventy-two tasks request more than the 8-core capacity.

The primary carbon input contains 216 hourly UTC IN-WE observations from 2026-09-22 00:00 through 2026-09-30 23:00. The repository attributes the data to Electricity Maps, but the original retrieval URL/date/API version/license are not recorded. The unit gCO2e/kWh is documented but not encoded in the CSV itself. Two separate January 2025 half-hour datasets have unverified provenance, zone, and units; they were excluded.

The persisted forecast replay contains 160 rows: four leads at each of 40 historical origins. The input and output hashes are recorded in `phase6_run_configuration.json` and the independent ledger reports.

## 10. Data Cleaning and Validation

`src.data.validate_workload_stream` checks required fields, finite numeric values, nonnegative times and CPU, positive duration, duration consistency, and duplicate `(job_name, task_name)` identity. It preserves source rows and assigns `trace-task-{source_row:012d}` before ordering. Chunk sorting and k-way external merge avoid loading the full workload into a DataFrame. The run retains 72 over-capacity tasks so the scheduler can classify them as infeasible.

Independent Phase 6 verification streams each ledger beside the ordered workload. A disk-backed SQLite primary key checks ID uniqueness; exact rowwise comparison checks expected identity sequence and source-row mapping. SHA-256 and file byte sizes are recorded and byte sizes match checkpoint output offsets.

## 11. Carbon Forecasting Methodology

The persisted forecast uses Seasonal Naive: `ŷ_t = y_(t-24)`. It generates four hourly leads at each available rolling origin. A chronological partition uses 129 initial-history points, 43 calibration points, and a rolling replay from index 172 through 215. The absolute-error threshold uses rank `ceil((43+1)×0.9)=40`; symmetric bounds use prediction ± threshold with lower bound clipped to zero.

The model is a historical replay. Forecast records do not include a service log that proves the forecast was available at the simulated decision time. TRACE's decision reader deliberately ignores the actual-carbon forecast column; observed values are only used in final evaluation.

## 12. Forecast Validation

For the 160 persisted predictions, horizon 1–4 MAEs are 6.275, 6.000, 6.075, and 6.150 gCO2e/kWh; all-lead MAE is 6.125 and RMSE 6.946. Persistence MAEs by lead are 19.075, 36.975, 54.375, and 71.125; all-lead mean is 45.388. Interval coverage was 100% on these correlated replay rows with mean width 158. Only 43 calibration residuals inform the interval. The replay therefore does not demonstrate formal 90% calibration or future coverage.

At task level, 1,699,114 rows have full forecast replay coverage; 11,589,436 lack a forecast origin and 280 have incomplete origin coverage. These values are eligibility counts, not scores or reschedules.

## 13. TRACE Scheduling Architecture

The event engine reads each chronological task once and updates independent policy states. Each policy keeps an event heap, capacity calendar, running/committed assignments, counters, and strategy-specific state. For the full run, decisions stream to three CSV ledgers. A shared SQLite database stores task IDs and checkpoint state. Tasks are non-preemptive; once committed, a future assignment is not moved.

## 14. Mathematical Formulation

Let `s_i` be task start, `r_i` release, `d_i` duration, `c_i` CPU demand, `C=8` total CPU capacity, and `D=3600` maximum delay. Implemented per-task constraints are:

- Release: `s_i ≥ r_i`.
- Maximum delay: `s_i − r_i ≤ D`.
- Individual capacity: `c_i ≤ C`.
- Aggregate capacity: for each time `t`, `Σ_i c_i 1[s_i ≤ t < s_i+d_i] ≤ C`.
- Non-preemption: each executed task occupies one contiguous interval `[s_i,s_i+d_i)`.

For assumed power `P=10 W/core`, estimated energy is `E_i = d_i c_i P / 3,600,000` kWh. If `q_ih` is the fraction of task `i`'s duration overlapping hour `h`, observed emissions are `G_i = E_i Σ_h q_ih I_h`, where `I_h` is the observed carbon intensity in gCO2e/kWh. Only fully covered intervals contribute to reported observed emissions; no missing value is imputed.

For forecasted baseline/candidate intensities `p_b,p_c` and upper bounds `u_b,u_c`, TRACE ranks a candidate using `R_i = E_i(p_b-p_c) − λE_i[(u_b-p_b)+(u_c-p_c)]`. A positive value is required. Feasibility filtering also requires the candidate slot to fit capacity and the deadline. This is a per-task heuristic under current reservations, not a global objective minimization. Interval widths are treated as a penalty; no calibrated risk probability is implied.

## 15. Baseline Scheduling Algorithms

FIFO uses release-ordered input and a nondecreasing committed-start floor, then finds the earliest capacity-feasible slot. Earliest-feasible uses the same chronological stream and chooses the earliest fit at or after release, permitting backfill around future reservations. Neither baseline scores forecasts. Both use the same capacity, release, delay, duration, and infeasibility rules as TRACE.

## 16. Energy and Carbon Emissions Model

The 10 W/core value is an explicit assumption, not measured server power. This model omits idle power, memory, storage, network, cooling, power-delivery losses, and embodied emissions. Energy is split over occupied hourly intervals by duration overlap, then multiplied by observed IN-WE intensity. Predictions guide TRACE choices but are never used as actual emissions.

The independent recalculation uses the raw carbon file and every executed task row: 297,143 tasks for FIFO and 313,268 for each other policy. All evaluated execution intervals fall within the 216 observed hours. Maximum per-task energy discrepancy is below `5.6e-17` kWh and emissions discrepancy below `5.7e-14` g.

## 17. Experimental Setup

The full run uses 13,288,830 ordered task rows, three policies, CPU capacity 8, maximum delay 3,600 seconds, forecast horizon four hours, risk weight 0.5, assumed power 10 W/core, and checkpoint interval 10,000 tasks. All policies process the same source-row/task-ID sequence. A durable interruption occurred after 5.3 million tasks; a compatible resume completed the workload.

## 18. Full-Scale Execution

The completed checkpoint and event summary each record 13,288,830 processed tasks. Accumulated scheduler runtime is 10,127.16 seconds; resumed invocation reports 6,867.74 seconds; recovery-session runtime is 5,714.21 seconds. These do not include the complete wall-clock interruption gap. Peak RSS is 111,738,880 bytes (106.5 MiB). Schedule ledgers total 7,958,428,511 bytes and checkpoint DB is 920,371,200 bytes. Independent validation's SQLite index is an additional 1,721,425,920 bytes.

Independent ledger checks report 13,288,830 rows and unique IDs for each strategy; zero duplicate, missing, unexpected, sequence, or source-row identity errors; exact output-offset agreement; and zero CPU/task-constraint violations. Checkpoint, event summary, evaluation, and independent report comparisons all pass. Full-scale source/output artifacts are local and ignored by Git.

## 19. Results and Comparative Analysis

| Strategy | Processed | Completed | Completion rate | Deferred | Infeasible | Pending | Mean delay | CPU utilization | Energy kWh | Observed emissions g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FIFO | 13,288,830 | 297,143 | 2.2360% | 12,991,615 | 72 | 0 | 3,598.11 s | 88.93% | 15.078390 | 9,176.9781 |
| Earliest-feasible | 13,288,830 | 313,268 | 2.3574% | 12,975,490 | 72 | 0 | 3,586.87 s | 89.40% | 15.159375 | 9,226.8921 |
| TRACE | 13,288,830 | 313,268 | 2.3574% | 12,975,490 | 72 | 0 | 3,586.89 s | 89.40% | 15.159375 | 9,226.7090 |

There are zero duplicate-prevented or other states. Rejected is deferred plus infeasible, not an additional disjoint state. TRACE fallback decisions total 11,649,044: 253,870 missing forecast origin, 59,392 no positive risk savings, and 3 incomplete origin coverage. Three forecast-rescheduled decisions were recorded; scoring time was 135.67 seconds. FIFO and earliest-feasible have no forecast-scored/fallback decisions.

Whole-outcome totals are not like-for-like: FIFO completes fewer tasks. The common set includes 165,474 IDs completed by all strategies and observed-carbon-covered under every schedule. Common emissions: FIFO 4,553.7721 g; earliest-feasible 4,553.7716 g; TRACE 4,553.5885 g. TRACE is lower than FIFO by 0.1836 g or 0.00403% on that set. This result is too small and narrow to support a broad superiority claim.

## 20. Discussion

TRACE and earliest-feasible complete the same number of tasks, with virtually identical average delay and utilization. TRACE's whole completed-population emissions are lower than earliest-feasible by about 0.1831 g, but they schedule the same number, not necessarily identical task sets. On the strict common set, TRACE is 0.1836 g below FIFO and 0.1831 g below earliest-feasible. Forecast rescheduling is sparse: only three recorded forecast-rescheduled decisions in the full run. Most decisions use fallback or capacity/deadline behavior. These results demonstrate implementation behavior for a constrained scenario, not robust operational benefit.

## 21. Limitations

- Assumed CPU power is not measured power.
- Forecast replay is historical and has no issue-time availability evidence.
- Short carbon history and serial dependence limit forecast conclusions.
- Workload relative seconds are indexed to carbon hours without real calendar alignment.
- Carbon data provenance and license metadata are incomplete.
- Most workload tasks lack forecast origin coverage; forecast use was sparse.
- Carbon outside the observed window is not imputed.
- CPU is a fungible scalar; memory, I/O, and host heterogeneity are not modeled.
- The strategy score is heuristic and locally greedy, not globally optimal.

## 22. Threats to Validity

**Construct validity:** model-based energy and average carbon intensity approximate emissions; system boundaries omit facility and hardware effects. **Internal validity:** outputs are strongly audited, but one fixed workload/configuration cannot isolate broad causal effects of the heuristic. **External validity:** nine days of one grid trace and one workload do not represent diverse regions or production queues. **Forecast validity:** correlated samples undermine naive interpretation of empirical interval coverage. **Provenance validity:** preflight hashes the normalized carbon timeline while the run configuration hashes raw CSV bytes. Both match the current data in their respective representations, although the preflight JSON does not record the carbon path. Source retrieval and license provenance remain incomplete.

## 23. Future Work

Use longer, provenance-complete grid histories and verified workload timestamps; capture forecast issue-time logs; compare calibrated rolling uncertainty methods under temporal shift; measure CPU/system energy with telemetry; model memory/I/O and heterogeneous resources; quantify deadline trade-offs; test multiple workloads and grid zones; and conduct repeated/sequential evaluation with confidence intervals. Consider global or rolling-horizon optimization only as a new, separately validated algorithm.

## 24. Conclusion

TRACE implements and completes a full-scale, event-based carbon-aware scheduling experiment. All three strategies process the same 13.29-million-task sequence, and independent ledger, checkpoint, constraint, and emissions recalculations pass. On the common completed population, TRACE has a 0.00403% lower observed-carbon total than FIFO. Given the tiny difference, sparse rescheduling, assumed energy, and historical replay limitations, the defensible conclusion is that TRACE demonstrates an auditable policy prototype; the experiment does not establish general or material emissions superiority.

## 25. References

1. Green Software Foundation. *Software Carbon Intensity Specification*, v1.1.0. <https://sci.greensoftware.foundation/>. Background standard; TRACE does not claim an SCI score.
2. Electricity Maps. *Carbon Intensity API Documentation*. <https://app.electricitymaps.com/docs/reference/carbon-intensity>. Data concepts and gCO2eq/kWh unit; local retrieval provenance remains incomplete.
3. Angelopoulos, A. N., and Bates, S. (2023). *Conformal Prediction: A Gentle Introduction*. Foundations and Trends in Machine Learning. <https://arxiv.org/abs/2107.07511>.
4. Gibbs, I., and Candès, E. (2021). *Adaptive Conformal Inference Under Distribution Shift*. NeurIPS. <https://arxiv.org/abs/2106.00170>.
5. Henderson, P. et al. (2020). *Towards the Systematic Reporting of the Energy and Carbon Footprints of Machine Learning*. Journal of Machine Learning Research, 21(248). <https://arxiv.org/abs/2002.05651>.

## 26. Reproducibility Instructions

Start with `docs/TRACE_REPRODUCIBILITY_AND_RUNBOOK.md`. Install dependencies, supply the separately stored input data, validate and externally sort the workload, validate the rolling forecasts, and run tests. Use preflight before a bounded run. Full-scale execution is a deliberate opt-in requiring exact matching inputs and substantial disk. Do not run a full command to reproduce the test suite. Preserve output ledgers, checkpoint, progress events, and independent reports. The Phase 6 full-scale results are local ignored artifacts; a clean clone alone is insufficient to reproduce the reported numbers.
