# TRACE Phase 6 Execution Record

## Run identity and recovery

The complete validated chronological workload was executed on `feat/final-integration` with FIFO, earliest-feasible, and TRACE using the same input, resource assumptions, and task population. The run directory is `results/phase6/full_real_20261111_run1/`.

The run was first interrupted after a durable 5,300,000-task checkpoint. The original process was absent, so the saved input hash, configuration, engine fingerprint, output offsets, and checkpoint compatibility were verified before resuming. The resume preflight is preserved as `phase6_resume_preflight_report.json`; a durable interruption and resume event is recorded in `phase6_progress.jsonl`. The run resumed from that checkpoint and ultimately committed 13,288,830 tasks. The checkpoint now marks the run complete. No prior output ledger was deleted or replaced during recovery; only uncommitted ledger tails were recovered to the recorded offsets by the engine.

## Configuration and inputs

- Workload: `results/validation/chronological_tasks.csv`
- Workload SHA-256: `592cfe26479be3a0a4b44f76db3f008af7f8d1915d7c27aee5feab404a3ac29f`
- Observed carbon data: `data/raw/carbon/india_west_carbon_intensity.csv`
- Carbon SHA-256 saved in run config: `d6b4eaf55d2118e5f8e4096971bb4aea75f6f87d8281f0cb9a9d672e5c468108`
- Forecast replay: `results/forecasting/rolling_seasonal_naive_forecasts.csv`
- Forecast SHA-256: `21ee3247a2e253e65718de08bc738ea6f47aaad6b466c66b02607ae53ed411da`
- Zone: IN-WE; capacity: 8 CPU cores; maximum delay: 3,600 seconds; forecast horizon: 4 hours; risk weight: 0.5; power assumption: 10 W/core.
- Checkpoint interval: 10,000 processed tasks.
- Configuration and preflight records: `phase6_run_configuration.json`, `phase6_preflight_report.json`, `phase6_resume_preflight_report.json`.

## Completion and resources

The completed checkpoint and event summary report exactly 13,288,830 processed tasks for each strategy. Accumulated scheduler runtime was 10,127.16 seconds (2 h 48 m 47 s), including the original and resumed sessions; the resumed invocation's wall time was 6,867.74 seconds. Recovery-session runtime was 5,714.21 seconds. Checkpoint work consumed 3,479.63 seconds cumulatively. Peak process RSS recorded in checkpoint and completion metadata was 111,738,880 bytes (106.5 MiB). Runtime and RSS are from the recorded process/checkpoint metrics; full wall-clock elapsed time includes the interruption gap and is not represented by scheduler runtime.

At finalization, schedule ledgers occupied about 7.96 GB total (FIFO 2,651,050,363 bytes; earliest-feasible 2,651,309,891 bytes; TRACE 2,656,068,257 bytes). The checkpoint SQLite database was 920,371,200 bytes; its WAL was checkpointed to zero bytes at final inspection. Remaining free space at finalization was approximately 25.6 GB. These sizes exclude the validated workload, forecasts, and carbon inputs.

## Task states and integrity findings

Each strategy reports the same coverage classification: 1,699,114 forecast-eligible tasks and 11,589,716 forecast-ineligible tasks. Each has 72 tasks requesting more than 8 cores, explicitly classified infeasible. FIFO executed 297,143 tasks and deferred 12,991,615; earliest-feasible and TRACE each executed 313,268 and deferred 12,975,490. End-of-run pending count is zero. There were zero duplicate-prevention events, zero CPU-capacity violations, and zero task-constraint violations in the independent streaming ledger audit. Maximum independently observed allocated CPU was 8 cores.

The ledgers preserve `source_row` and deterministic `task_id`. Independent reconciliation streamed each ledger against the complete chronological workload and used a disk-backed SQLite primary key to test uniqueness. All three ledgers passed with 13,288,830 rows and unique IDs, zero missing or unexpected IDs, zero sequence errors, zero source-row identity errors, and zero constraint violations. Each byte size agrees with its checkpoint committed output offset. SHA-256 hashes are recorded below. The audit report is `results/phase6/independent_validation/independent_validation.json`; the disk-backed uniqueness index is `results/phase6/independent_validation/ledger_ids.sqlite3`. The separate comparison with `final_evaluation.json`, `event_run_summary.json`, and the checkpoint is `results/phase6/independent_validation/cross_check_report.json`.

| Strategy | Rows / unique IDs | Missing / duplicate / unexpected IDs | Sequence / identity errors | Ledger bytes | SHA-256 | Checkpoint offset | Constraint violations |
|---|---:|---:|---:|---:|---|---:|---:|
| FIFO | 13,288,830 / 13,288,830 | 0 / 0 / 0 | 0 / 0 | 2,651,050,363 | `963c71f6ccc17e41afada743b081f230cc7e6344b2a9ee9c27efcc67836a47bc` | 2,651,050,363 | CPU 0; task 0 |
| Earliest-feasible | 13,288,830 / 13,288,830 | 0 / 0 / 0 | 0 / 0 | 2,651,309,891 | `879f5c814c58992bf9d0b46b5a50f2e7199c2dcf53f14d5730ffb14a81794447` | 2,651,309,891 | CPU 0; task 0 |
| TRACE | 13,288,830 / 13,288,830 | 0 / 0 / 0 | 0 / 0 | 2,656,068,257 | `44be2d5b4369d6722a8dba09b3e6ab84ed2bde10407b04c09d430eda6724b78e` | 2,656,068,257 | CPU 0; task 0 |

## Monitoring and logs

- Durable progress and interruption/recovery events: `results/phase6/full_real_20261111_run1/phase6_progress.jsonl`
- Engine task and strategy metrics: `event_run_summary.json`
- Final evaluation: `final_evaluation.json`, `final_evaluation_by_strategy.csv`
- Completion metadata: `phase6_completion.json`
- Independent ledger validation: `results/phase6/independent_validation/independent_validation.json`
- Engine/checkpoint comparison: `results/phase6/independent_validation/cross_check_report.json`
- Independent emissions recalculation: `results/phase6/independent_validation/emissions_recalculation.json`
- Output ledgers: `fifo_schedule.csv`, `earliest_feasible_schedule.csv`, `trace_schedule.csv`

The final progress/checkpoint records show all tasks committed and completed. Forecast and emissions interpretation, including historical replay limitations, is documented in `TRACE_FINAL_EVALUATION.md`.

## Validation caveat and verification

The preflight reports store SHA-256 `789c3264423c92b0c527b19633348ab653e21002cb2f04760070ce1c650b79f3` for the normalized IN-WE timestamp/intensity table. The full-run configuration stores `d6b4eaf55d2118e5f8e4096971bb4aea75f6f87d8281f0cb9a9d672e5c468108` for raw carbon CSV bytes. The checkpoint config contains the normalized hash, matching both preflight reports and the current normalized timeline; the current raw file matches the run configuration hash. The different values reflect distinct hash inputs, not a demonstrated data change. See `TRACE_CARBON_HASH_RECONCILIATION.md`; source retrieval provenance remains incomplete.

The initial `py -m pytest -q` attempt encountered 37 setup errors because the process could not access pytest's default per-user temporary directory; pytest cache writes were also denied. After write/read/delete probes succeeded in `C:\TRACE_test_temp` and `C:\TRACE_pytest_cache`, `py -m pytest -q -o cache_dir=C:\TRACE_pytest_cache --basetemp=C:\TRACE_test_temp` completed with 93 passed and one third-party `dateutil` deprecation warning. `git diff --check` passed; Git reports only the existing README line-ending conversion warning.
