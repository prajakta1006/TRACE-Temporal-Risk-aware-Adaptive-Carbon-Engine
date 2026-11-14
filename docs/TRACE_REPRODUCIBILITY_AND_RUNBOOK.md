# TRACE Reproducibility and Runbook

## Environment and data availability

The verified environment used Python 3.13.3 on Windows. Requirements are listed in `requirements.txt` (`numpy`, `pandas`, `scikit-learn`, `matplotlib`, `psutil`, `pytest`). Create an isolated environment from CMD:

```cmd
py -3.13 -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

The repository does not version the raw/processed datasets, forecast outputs, full run, checkpoint, or validation outputs. `.gitignore` excludes them. To reproduce the full experiment, provide the same validated chronological workload, carbon input, rolling forecast file, and configuration. Confirm hashes against `phase6_run_configuration.json`; no secrets are needed for offline runs. Carbon provenance and license details are incomplete in the local record.

Expected inputs for the full event engine:

```text
data/raw/carbon/india_west_carbon_intensity.csv
results/forecasting/rolling_seasonal_naive_forecasts.csv
results/validation/chronological_tasks.csv
```

## Safe command tiers

### Tests

The project test suite uses writable temp/cache locations on this machine:

```cmd
py -m pytest -q -o cache_dir=C:\TRACE_pytest_cache --basetemp=C:\TRACE_test_temp
```

Expected verified result: 93 passed, one third-party `dateutil` deprecation warning. Create and write-test those directories first if Windows permissions differ.

### Data validation

This command performs full workload validation, duplicate detection, and external chronological ordering; it does not schedule tasks. It can use substantial temporary disk.

```cmd
py -m src.data.validate_workload_stream --input data/processed/workload/workload_cleaned.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --zone IN-WE --output-dir results/validation/phase8_reproduction
```

Resume only with identical input/configuration after an interrupted validation:

```cmd
py -m src.data.validate_workload_stream --input data/processed/workload/workload_cleaned.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --zone IN-WE --output-dir results/validation/phase8_reproduction --resume
```

Do not rerun over an existing completed validation directory. Preserve its `_validation_work` artifacts until outputs are verified.

### Forecast validation

The command validates the persisted forecasts, evaluates the replay, and scans workload coverage. It does not run the scheduler.

```cmd
py -m src.evaluation.forecast_validation --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --workload results/validation/chronological_tasks.csv --output results/phase8_forecast_validation
```

Forecast generation is `py -m src.forecasting.rolling_forecast`; it uses the configured local carbon input and writes the four-hour historical rolling replay to the fixed `results/forecasting/` location. That command can overwrite the existing replay, so do not run it when preserving Phase 6 inputs; generate into an isolated copy of the project if new forecasts are required.

### Preflight (no scheduling)

Preflight hashes and scans inputs, checks forecast/configuration and disk space, and verifies output writability/checkpoint compatibility. It does not start the scheduler. Keep task bound explicit:

```cmd
py -m src.scheduler.preflight --workload results/validation/chronological_tasks.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --output results/simulation/phase7_preflight_only --max-tasks 1000 --minimum-free-gb 5
```

The preflight output directory is a new disposable target for its report/probe. Do not point it at a prior run's output directory unless checking that exact checkpoint.

### Small event-engine run

This is a real bounded simulation over the first 1,000 chronologically ordered tasks, not the full workload. Use a new output directory:

```cmd
py -m src.scheduler.event_engine --workload results/validation/chronological_tasks.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --output results/simulation/phase7_small_1000 --max-tasks 1000 --checkpoint-interval 100
```

The benchmark fixture mode is synthetic and writes benchmark outputs:

```cmd
py -m src.scheduler.event_engine --benchmark --output results/benchmark_scheduler/phase7_smoke
```

### Staged real-workload evaluation

The `src.evaluation.phase6_execution` default stage suite runs configured prefixes and recovery checks. Keep sizes bounded and use a new output path; this is not the full 13.29-million-task experiment:

```cmd
py -m src.evaluation.phase6_execution --output results/phase7_staged --sizes 10000 100000 --resume-test-size 100000 --checkpoint-interval 10000
```

### Full-scale run — deliberate opt-in only

The full execution processes all 13,288,830 rows and writes three multi-gigabyte ledgers plus a large SQLite checkpoint. It may take hours and requires substantial free disk. Do not run this command as a test or quick-start step. First confirm all input hashes, reserve output space, and use a brand-new output directory. The command below is provided for explicit reproduction only:

```cmd
py -m src.evaluation.phase6_execution --full-run --output results/phase7_full_run --workload results/validation/chronological_tasks.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --checkpoint-interval 10000
```

If interrupted, preserve all ledgers, SQLite state, logs, and preflight reports. Verify the original output path and exact run options, then preflight for resume and use the same output directory/configuration:

```cmd
py -m src.scheduler.preflight --workload results/validation/chronological_tasks.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --output results/phase7_full_run --resume --minimum-free-gb 15
```

```cmd
py -m src.evaluation.phase6_execution --resume-full --output results/phase7_full_run --workload results/validation/chronological_tasks.csv --carbon data/raw/carbon/india_west_carbon_intensity.csv --forecasts results/forecasting/rolling_seasonal_naive_forecasts.csv --checkpoint-interval 10000
```

Do not resume if input hashes/configuration differ. Use another directory for a fresh run.

## Result verification

The Phase 6 independent ledger, cross-check, and emissions reports are already present under `results/phase6/independent_validation/`. The helper scripts `scripts/verify_phase6_ledgers.py`, `cross_check_phase6.py`, and `verify_phase6_emissions.py` use fixed Phase 6 paths; the first also resets its on-disk SQLite ID index, and all rewrite report files. They were used to generate the preserved reports. Do not rerun them in place. To verify another run, make an isolated copy and update all paths/output targets before execution. Compare row counts, exact identities, hashes, offsets, task states, fallback counts, energy, and observed-carbon emissions; retain explicit population definitions.

## Output interpretation and common failures

- `executed` is completed; `deferred` and `infeasible` are distinct rejected outcomes. Pending should be zero only after lifecycle events drain.
- Forecast eligible means historical replay coverage, not that the decision scored or rescheduled the task.
- Forecast fallback counts are decisions and include tasks outside forecast coverage; they are not the count of all eligible tasks.
- Emissions totals are only sums for executed intervals inside observed carbon coverage. The 10 W/core energy value is assumed, not measured.
- Permission denied in pytest's default Windows temp or cache path can create setup errors before test bodies run. Use writable `--basetemp` and `-o cache_dir` paths and do not skip tests.
- A checkpoint mismatch means a path, input, strategy, interval, or simulation parameter changed. Preserve artifacts and diagnose before any retry.
- Disk shortage, file locking, and interrupted output writes require preserving the output directory and checking checkpoint offsets before resume.
- Preflight and run configuration use different carbon hash representations; see `TRACE_CARBON_HASH_RECONCILIATION.md`. Do not silently edit historical records.

## Verified Phase 6 execution

Phase 6 completed on the full validated workload. Its execution record and exact run hashes, independent ledger reconciliation, emissions recalculation, and known provenance caveat are in `TRACE_PHASE6_EXECUTION.md`, `TRACE_FINAL_EVALUATION.md`, and `results/phase6/independent_validation/`. Those large artifacts remain local and ignored by Git; they are not recreated by running the test suite.
