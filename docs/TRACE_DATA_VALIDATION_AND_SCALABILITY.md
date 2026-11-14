# TRACE data validation and scalability

## Scope and reproduction

This phase validates and chronologically orders the complete cleaned workload without building a full-workload pandas DataFrame. It does **not** run the 13.29-million-task simulation or change forecasting/scheduling algorithms.

From the repository root (the command loads the current hourly IN-WE carbon series to establish the relative simulation timeline):

```powershell
py -m src.data.validate_workload_stream
```

The default workload is `data/processed/workload/workload_cleaned.csv`, and the default carbon file is `data/raw/carbon/india_west_carbon_intensity.csv` in zone `IN-WE`. Configuration can be changed with `--input`, `--carbon`, `--zone`, `--output-dir`, `--chunk-size`, `--cpu-capacity`, and `--duration-tolerance-seconds`. Carbon records must be continuous and exactly hourly. Workload times are interpreted as seconds from the first carbon timestamp, and task end times are checked against the observed timeline. Use `--resume` after an interrupted run, with the same input and validation rules. The input SHA-256 and validation configuration are checked before resuming. A different chunk size is currently considered a different run configuration; task IDs remain identical because they depend only on source-row position.

Generated files are under `results/validation/` and ignored by Git:

- `validation_summary.json` and `validation_summary.csv`: counts, audit metrics, input hash, timestamps, config, runtime, memory, and temporary disk use.
- `validation_config.json`: the explicit rule configuration.
- `missing_values_by_column.csv`: missing-value counts for each source column.
- `invalid_rows.csv`: each structurally invalid row, its `task_id`, and semicolon-separated error codes.
- `duplicate_rows.csv`: each repeated valid `(job_name, task_name)` pair, its ID, and the first retained source row.
- `chronological_tasks.csv`: all structurally valid, unique tasks ordered by `start_time`, then stable task ID.
- `_validation_work/`: SQLite checkpoint/identity index and sorted chunk runs used for resume and external merge.

The chronological output is a disk-backed CSV representation that can feed a later streaming simulation. The full CSV is intentionally not loaded into RAM to verify or sort it.

## Validation rules

The source data-row number is zero-based; the header is not counted. Required identity columns are `job_name` and `task_name`. Required numeric columns are `start_time`, `end_time`, `duration_seconds`, and `cpu_cores`.

A row is structurally invalid if either identity is missing, a required number is missing/non-numeric/non-finite, start or end time is negative, duration is nonpositive, CPU is negative, end precedes start, or `abs(end_time - start_time - duration_seconds)` exceeds the configured tolerance (default 1 second). A row with several defects is counted once in `invalid_rows`; individual error-code counts can overlap.

Duplicate identity means a repeated `(job_name, task_name)` pair among structurally valid rows. The earliest valid source row is retained; later valid occurrences are written to `duplicate_rows.csv` and counted as duplicates. Structurally invalid rows do not claim an identity. `excluded_rows` is exactly `invalid_rows + duplicate_rows`.

Rows with valid structure and unique identity remain in `chronological_tasks.csv`, including CPU requests above the configured capacity and tasks extending beyond the observed carbon timeline. Over-capacity tasks are counted in `tasks_exceeding_cpu_capacity`; out-of-timeline tasks are counted in `tasks_outside_carbon_timeline`. Neither category is silently excluded. Extrema in the summary are calculated over valid unique tasks.

## Deterministic identity and external ordering

For source row `r`, the deterministic ID is `trace-task-{r:012d}`. For example, source row zero is `trace-task-000000000000`. The source row and ID are created before chunk-local processing and never depend on sorting. The source row is retained in all validation detail files and chronological output, making IDs invariant to chunk boundaries and sort order.

Each chunk is checked and sorted in memory by `(start_time, source_row)`, then written as a sorted run. SQLite holds a disk-backed unique index of valid task identities across chunks and the committed checkpoint. A k-way heap merge combines sorted runs. Since the ID is a fixed-width encoding of the source row, source-row order is the same deterministic tie-break as task-ID order.

Resume state is committed after each chunk's sorted/detail runs are safely written. On resume, the input hash and rule configuration must match; uncommitted run files are removed and that source interval is processed again. Tests simulate stopping after a committed chunk and verify that resumed IDs and order are unchanged. This is an application-level checkpoint, not a guarantee against hardware/filesystem loss.

### Temporary disk requirements

The run keeps the original input, the SQLite identity/checkpoint index, sorted chunk runs, and the in-progress merged chronological output at the same time. Temporary usage therefore grows with valid workload size; allow several times the input CSV size. The measured peak for this workload was 2.75 GiB, including the disk-backed identity index and sort artifacts. Keep `_validation_work/` until the completed output and summary have been checked. It is currently retained so the checkpoint and deduplication audit remain available.

## Full-data audit results

The run used Python 3.13.3 and pandas 2.3.3, chunk size 100,000, CPU capacity 8 cores, and duration tolerance 1 second. The source file SHA-256 was:

`6bbc0b8005b32e16872069a646e8c2a37b85b54282593d0a52a266d369e37277`

| Metric | Result |
|---|---:|
| Total source rows | 13,288,830 |
| Valid unique rows | 13,288,830 |
| Invalid rows | 0 |
| Duplicate rows | 0 |
| Excluded rows | 0 |
| Missing values across source columns | 0 |
| Invalid start/end times | 0 / 0 |
| Invalid or nonpositive durations | 0 / 0 |
| Negative CPU requirements | 0 |
| Duration mismatches above tolerance | 0 |
| Valid tasks requesting more than 8 cores | 72 |
| Tasks ending outside the observed 216-hour carbon timeline | 0 |
| Minimum / maximum start time (seconds) | 3,297 / 765,880 |
| Minimum / maximum end time (seconds) | 3,301 / 772,823 |
| Maximum duration (seconds) | 461,302 |
| Maximum CPU request (cores) | 10 |

No source rows were silently discarded. The 72 over-capacity rows are present in the ordered output and flagged separately. The maximum task end (772,823 seconds) is within 216 hours (777,600 seconds) from the carbon timeline origin.

An independent streaming verification read the ordered output and confirmed 13,288,830 rows, zero sort-key breaks, zero ID mismatches, and no missing/duplicate source-row IDs.

## Performance measurements

The complete validation, duplicate scan, external ordering, and output writing took **250.48 seconds** (4 minutes 10 seconds), at **53,054 source rows/second** including sorting and finalization. Sampled peak resident memory was **267,902,976 bytes (255.5 MiB)** using a 100 ms RSS monitor. Peak temporary disk use was **2,954,857,031 bytes (2.75 GiB)**. The SQLite state database ended at about 385 MiB, and the chronological task CSV is about 1.24 GB.

Measurements are from one local Windows run and depend on storage, CPU, and antivirus/filesystem behavior. The memory result is sampled RSS; very short peaks between samples may not be captured. A separate verification read of the ordered CSV is not included in the 314-second validation runtime.

The source CSV has 2,891,755 decreases in `start_time` in original row order. The external sort removes dependence on source ordering and makes ties deterministic.

## Remaining risks and next phase

- Duplicate detection assumes `(job_name, task_name)` is the task identity. If the source permits legitimate reuse of that pair, the key rule must be revised before simulation.
- A repeated validation with a changed CPU capacity or tolerance needs a new output directory; completed outputs are not overwritten.
- Checkpoints require the SQLite state and prior chunk runs. Do not remove `_validation_work/` before final results are backed up or consumed.
- The chronological CSV has not yet been connected to a full event-based scheduler. No claim is made that all tasks have been simulated or executed.
- The 72 requests above 8 cores must be classified as scheduler-infeasible (or evaluated under a higher-capacity scenario), not dropped.
- Carbon forecasts cover only a small tail of the 216-hour observed timeline. Full-period forecast-based scheduling still needs an explicitly bounded evaluation window or additional verified carbon history.

Next, the full simulation should consume the ordered representation incrementally, preserve `source_row`/`task_id`, checkpoint scheduler state, and benchmark capacity/forecast behavior before attempting the complete workload.
