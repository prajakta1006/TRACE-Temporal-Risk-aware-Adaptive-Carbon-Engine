# TRACE Full-Scale Readiness

> Historical Phase 5 readiness snapshot. The full run was later completed and independently reconciled in Phase 6; this document's prospective estimates and “not run” status are not the final execution record. See `TRACE_PHASE6_EXECUTION.md` and `TRACE_FINAL_EVALUATION.md`.

## Current artifacts and checks

The ordered Phase 2 workload is `results/validation/chronological_tasks.csv` (1,235,960,676 bytes). The existing external-sort work directory occupies 1,639,566,683 bytes. Those artifacts already exist and are not recreated by the simulation. The scheduler streams the ordered CSV; it does not materialize the 13,288,830 tasks in memory.

The Phase 5 synthetic benchmark measured 1,000, 10,000, and 100,000 tasks separately for FIFO, earliest-feasible, and TRACE. The 100,000-task runs used about 88.6 MB peak RSS. TRACE took 11.94 seconds (8.38k input tasks/s) at that size, including 3.26 seconds of forecast scoring. This is a small synthetic workload and is not a safe full-run forecast: full-scale SQLite growth, real task contention, forecast scoring, filesystem throughput, checkpoint fsyncs, and emissions coverage can change the rate. The earlier 79-minute estimate is not adopted.

The 100,000-task TRACE benchmark wrote 20.72 MB of schedule CSV plus a 6.80 MB checkpoint/identity database. A full run writes three strategy ledgers but shares one identity/checkpoint database, so linear scaling is about 8.3 GB of ledgers plus 0.9 GB of SQLite state, or 9.2 GB total at 13.29 million tasks. Allow at least 2x for SQLite index/WAL variation, final summaries, filesystem behavior, and recovery headroom: plan for 22–25 GB of free space before a full run, in addition to already-present source and external-sort files. Checkpoint database size depends on task ID length and SQLite page/index overhead; the benchmark's measured output size includes it. Do not assume output compression.

The 100,000-task runs took 8.00 seconds for FIFO, 8.08 seconds for earliest-feasible, and 11.94 seconds for TRACE. Summed as a conservative proxy for all three policies, that is about 3.57k tasks/s and 62 minutes of raw scheduler time for 13.29 million tasks. Applying a 5x slowdown factor gives about 5.2 hours. Since the full engine shares input parsing, this sum may overstate parser cost; larger real-workload contention and SQLite growth may offset that. Reserve 3–8 hours for one full run until a larger representative integrated benchmark is measured. Resume hashing and final ledger comparison add additional sequential I/O.

| Tasks | Strategy | Runtime (s) | Tasks/s | Peak RSS (MB) | Output (MB) | Forecast scoring (s) | Rescheduled | Capacity violations | Completion |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | FIFO | 0.458 | 2,183 | 85.3 | 0.333 | 0 | 0 | 0 | 36.8% |
| 1,000 | Earliest-feasible | 0.413 | 2,424 | 85.6 | 0.333 | 0 | 0 | 0 | 37.6% |
| 1,000 | TRACE | 0.453 | 2,207 | 85.7 | 0.338 | 0.014 | 18 | 0 | 42.3% |
| 10,000 | FIFO | 0.608 | 16,449 | 86.5 | 2.796 | 0 | 0 | 0 | 5.37% |
| 10,000 | Earliest-feasible | 1.301 | 7,684 | 87.0 | 2.796 | 0 | 0 | 0 | 5.44% |
| 10,000 | TRACE | 1.608 | 6,219 | 87.2 | 2.777 | 0.361 | 2 | 0 | 5.44% |
| 100,000 | FIFO | 7.996 | 12,506 | 88.4 | 27.788 | 0 | 0 | 0 | 0.427% |
| 100,000 | Earliest-feasible | 8.081 | 12,375 | 88.4 | 27.788 | 0 | 0 | 0 | 0.457% |
| 100,000 | TRACE | 11.939 | 8,376 | 88.6 | 27.525 | 3.258 | 18 | 0 | 0.566% |

Forecast scoring is measured only for TRACE. Forecast coverage is 47.7% eligible and 52.3% ineligible in these generated workloads. TRACE delayed 321, 508, and 530 tasks at the three sizes; these counts include tasks scheduled after release, while rescheduled counts identify TRACE forecast-based alternatives. Infeasible tasks are those requesting more than eight cores; deferred tasks could not fit before the maximum-delay deadline. The benchmark completion percentages are low because the fixture intentionally creates increasing contention while spreading the tasks over the same short set of hours.

## Preflight

Preflight validates the workload hash and chronological `(start_time, task_id)` ordering, required workload/carbon/forecast files, forecast structure, configuration, writable output directory, available disk, and checkpoint compatibility. It creates and removes a small write probe, but does not create a checkpoint or start a simulation.

```powershell
py -m src.scheduler.preflight --output results/simulation/event_based --minimum-free-gb 20
```

For recovery, add `--resume` and pass the same strategy, configuration, task limit, and checkpoint interval used by the runner. The command scans the full ordered workload and hashes inputs, so preflight itself takes measurable time. Its default free-space requirement is 15 GiB; use 20 GiB for the planning margin above.

The real-data preflight passed on 2026-11-11 with a 5 GiB test threshold: all 13,288,830 rows were checked, 160 forecast rows loaded, and 36,192,944,128 bytes (33.7 GiB) were free when disk space was measured. The ordered workload SHA-256 was `592cfe26479be3a0a4b44f76db3f008af7f8d1915d7c27aee5feab404a3ac29f`. No checkpoint or schedule ledger was created.

## Benchmark interpretation

The Phase 5 benchmark uses a generated, chronologically ordered workload rather than the first 100,000 chronological real rows. It includes releases in verified forecast windows and outside them, simultaneous release groups, CPU contention, short tasks, multi-hour tasks, 9-core infeasible tasks, and max-delay deferrals. TRACE's scoring timer measures time inside forecast candidate scoring; TRACE versus earliest-feasible total runtime difference is separately recorded and includes I/O and scheduler overhead. The workload manifest is saved beside benchmark metrics.

At 100,000 tasks the synthetic trace is intentionally overloaded over its short time window, so completion rates are low and forecast rescheduling can be suppressed by reservations. Smaller benchmark sizes show rescheduling. These results measure implementation throughput under this synthetic mix, not expected service completion for the real workload. Forecast eligibility is copied from the TRACE pass to every strategy row because it is a property of the input coverage, not a FIFO/earliest decision.

## Remaining gates and risks

- The full workload simulation has not been run. Do not infer emissions or completion totals from the synthetic run.
- Forecast replay is historical; this is backtesting, not evidence of live forecast availability.
- Peak RSS at 100k was under 90 MB, but no full-size identity-index growth test was run. SQLite index size and write rate remain the main scaling uncertainties.
- The input is hashed at startup/resume and read again during scheduling. Three strategy output ledgers and checkpoint identity inserts amplify disk I/O.
- The benchmark's apparent 10k tasks/s includes synthetic data characteristics and should be revisited with larger representative segments before reserving production time.
- Preflight verifies current free disk and file integrity; it cannot guarantee disk capacity remains available during execution.
- Phase 2 temporary sort files occupy about 1.64 GB. Preserve the ordered input and its identity fields unchanged for the full run.

No full-scale simulation was started for Phase 5.
