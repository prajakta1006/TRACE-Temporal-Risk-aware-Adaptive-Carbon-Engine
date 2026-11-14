# TRACE Event-Based Scheduler Architecture

## Status

This architecture document describes the Phase 4 implementation design. The full 13,288,830-task run was subsequently completed in Phase 6 and independently reconciled; see `TRACE_PHASE6_EXECUTION.md` and `TRACE_FINAL_EVALUATION.md` for final evidence. The production entry point is `py -m src.scheduler.event_engine`; `py -m src.main --mode full` dispatches to the same engine and requires the externally sorted file.

## Input and stable ordering

The scheduler reads `results/validation/chronological_tasks.csv` one row at a time. It requires `source_row`, deterministic `task_id`, job/task names, release time, duration, and CPU requirement. Each task ID is re-derived from `source_row`; the input key `(start_time, task_id)` must be nondecreasing. Same-time tasks are consequently processed in stable ID order. Three strategy states consume each row in one shared input pass, and each strategy writes its decision immediately to a separate CSV.

A SQLite primary-key index prevents a repeated task ID from executing twice. A repeated input row remains in all ledgers with `task_status=duplicate_prevented`; it is not silently dropped. The index is disk-backed. It can be removed after a completed run when no audit/recovery need remains.

## Strategy definitions

All strategies use the same capacity, release times, durations, CPU requests, max-delay limit, carbon observations, energy model, and stable IDs.

### FIFO

Process tasks by release time and task ID. For each task, choose the earliest capacity-feasible start no earlier than both its release and the previous task's committed start. Simultaneous tasks may share a start if remaining CPU allows. A task cannot jump ahead of an earlier committed task's start. If no capacity slot exists by its deadline, it is deferred.

### Earliest-feasible

For each task in the common input order, choose the earliest capacity-feasible instant at or after release and no later than `release + max_delay_seconds`. This strategy may backfill a smaller task before an earlier task's future start reservation when CPU permits. It does not use forecast data.

### TRACE

At a task release, identify the historical origin at the preceding whole-hour boundary (`floor(release/3600)-1` relative to carbon index 0). Eligibility requires that this exact origin has prediction rows for every baseline occupied hour of the task. Predictions must have an exact `target = origin + horizon` relation and match the carbon-index hour. Only prediction, upper bound, lower bound, target hour, and horizon are read by the decision logic; the actual-carbon column is ignored.

For eligible tasks, TRACE follows the existing `generate_candidate_starts` hourly candidate rule and calls the existing `calculate_carbon_benefit` function. Candidate times are generated from scalar task fields to avoid constructing a pandas object per task. It ranks hourly starts by risk-adjusted savings, using the configured risk weight and the forecast upper bound as uncertainty. Candidates that conflict with running or committed reservations are skipped. A candidate is committed only if risk-adjusted savings are positive and capacity is available. Otherwise TRACE applies the earliest-feasible fallback.

TRACE records the forecast reason for every task: for example `missing_forecast_origin` or `incomplete_origin_coverage`. Other cases include no positive savings and candidates blocked by protected CPU reservations. Ineligible tasks use `fallback_<forecast_reason>`; forecasts are never synthesized and a missing value is never interpreted as zero carbon intensity.

Forecast eligibility means the historical replay file covers the baseline execution period. It does not establish operational issue-time availability; Phase 3 found no live issuance logs.

## Events, reservations, and task lifecycle

Tasks are non-preemptive. Each commitment inserts start and completion events into a min-heap and inserts CPU deltas into a dynamic interval calendar. Start/completion events at the same instant process completion first. On each release, the scheduler advances all lifecycle events through that timestamp.

The interval calendar is a deterministic treap keyed by start/end times. Each node stores aggregate CPU delta, total sum, and maximum prefix load. It supports logarithmic capacity queries and updates. As simulation time advances, past deltas are folded into the current running CPU load and removed. The remaining calendar represents only active or future committed intervals. Running jobs and future commitments are never moved.

Task states in output:

- `executed`: a start was committed within release/max-delay constraints. It may be running immediately or committed for a future event time.
- `deferred`: no resource-feasible start was available by the task deadline.
- `infeasible`: invalid task constraints or CPU request exceeds configured capacity. In particular, requests above 8 cores are explicitly infeasible under the default 8-core configuration.
- `duplicate_prevented`: task identity was already seen in this run.

Tasks can span multiple hours. CPU reservation uses the exact start/end interval; emissions split task energy proportionally across each occupied observed carbon hour. Execution is not rejected merely because the final placement falls outside the 216-hour carbon window. In that case the task remains executed, but its emissions field is empty with `emissions_status=outside_observed_carbon_timeline`; no carbon value is fabricated.

## Fair comparison and outputs

All strategy ledgers have the same task sequence and stable IDs. A streaming aligned comparison counts each strategy's completions and the common executed population without retaining all IDs in RAM. It also reports emissions for the common population only where the full scheduled interval has observed carbon coverage.

Default outputs under `results/simulation/event_based/`:

- `fifo_schedule.csv`
- `earliest_feasible_schedule.csv`
- `trace_schedule.csv`
- `execution_summary.csv`
- `event_run_summary.json`
- `.seen_tasks.sqlite3` (disk-backed duplicate guard)

Each per-task ledger records scheduling status, decision, forecast eligibility/reason, commitment state, and observed-emissions coverage. `execution_summary.csv` reports strategy-specific completion, infeasible/deferred counts, forecast counts for TRACE, energy/emissions, common population, runtime, throughput, process peak RSS, and capacity violations.

## Complexity and full-scale considerations

For `n` tasks and `a` active or future-reserved interval events, the single task pass is approximately `O(n log a)` for calendar/heap updates plus a disk-backed SQLite uniqueness insert per task. TRACE checks at most four hourly candidate starts per eligible task. The forecast table is small and held in memory. Task decisions are streamed to disk; workload rows and decision ledgers are never collected into population-sized DataFrames.

Memory is proportional to concurrent tasks, live event/calendar endpoints, forecast rows, and CSV buffers, rather than total workload size. Runtime disk use includes three output ledgers plus the SQLite identity index. Workload ordering is a prerequisite: this engine deliberately does not sort all tasks or use raw source order. The benchmark uses the first chronological prefix and is not a full workload run.

### Progressive benchmark

Command: `py -m src.scheduler.event_engine --benchmark --output results/benchmark_scheduler`. These are cumulative prefixes of the Phase 2 chronological file; all three strategies run in one pass. The 100k prefix spans only the earliest part of the workload, before the forecast replay window, so TRACE's forecast scoring branch was not exercised by this throughput measurement.

| Prefix tasks | Runtime (s) | Tasks/s | Process peak RSS (MiB) | Common executed tasks | Capacity violations | Output checks |
|---:|---:|---:|---:|---:|---:|---|
| 1,000 | 0.194 | 5,168 | 81.1 | 70 | 0 | Pass |
| 10,000 | 1.003 | 9,972 | 82.4 | 70 | 0 | Pass |
| 100,000 | 35.666 | 2,804 | 84.4 | 220 | 0 | Pass |

The 100k prefix emitted about 60 MB across three task ledgers and used a 6.8 MB SQLite identity index. A linear disk estimate for the full workload is roughly 8 GB of ledgers plus about 0.9 GB for the identity index; real sizes depend on row text and filesystem. Allow at least 10 GB of free space for a full run, beyond the existing input and validation artifacts. A simple extrapolation from the 100k rate is about 79 minutes for 13.29 million input tasks. This is only a rough planning estimate: the prefix is unusually overloaded, contains no forecast-eligible tasks, and does not capture later workload or forecast-candidate costs. The reported RSS is the process peak for these prefixes, not a guarantee for the full run.

## Known limitations

1. The current forecasts are historical rolling replay records, not verified live forecasts. TRACE is scientifically a backtest policy for this dataset.
2. The observed carbon window is only 216 hours; scheduled tasks outside it can execute but cannot contribute observed-emissions comparisons.
3. The energy model remains the project assumption of 10 W per allocated CPU core.
4. CPU is modeled as a fungible numeric capacity, not host/core affinity, memory, I/O, or other machine resources.
5. FIFO uses a strict nondecreasing committed-start order; earliest-feasible permits backfilling. This policy definition should remain fixed across comparisons.
6. The disk-backed ID index has not been benchmarked at 13.29 million identities in this phase. The full simulation remains unrun pending review.
7. Checkpoint/resume, output rollback, and deterministic recovery are implemented in `src/scheduler/event_engine.py`; see [TRACE checkpoint and recovery](TRACE_CHECKPOINT_AND_RECOVERY.md).

## Commands

Progressive benchmark:

```powershell
py -m src.scheduler.event_engine --benchmark
```

Optional bounded event run:

```powershell
py -m src.scheduler.event_engine --max-tasks 100000
```

Full scheduling is available but intentionally not launched in Phase 4:

```powershell
py -m src.main --mode full
```
