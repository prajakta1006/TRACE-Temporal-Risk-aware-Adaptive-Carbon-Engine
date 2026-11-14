# TRACE Forecasting Validation and Coverage

> Historical Phase 3 forecast-validation report. Its statement that the full scheduler simulation was not run describes that phase only. Phase 6 later completed the full simulation; see `TRACE_PHASE6_EXECUTION.md` and `TRACE_FINAL_EVALUATION.md`. The preserved machine-readable Phase 3 summary also retains this historical limitation string.

## Scope and evaluation label

This phase evaluates the persisted `results/forecasting/rolling_seasonal_naive_forecasts.csv` as a **historical rolling-origin backtest**. It is not evidence of forecasts having been issued by a live service at the recorded historical times. The file stores forecast origins, targets, lead times, point predictions, intervals, and actuals, but no operational issue-time log. The origin precedes each target and the scheduler can replay the decision rule at that origin; operational availability has not been independently verified.

The assessment command is:

```powershell
py -m src.evaluation.forecast_validation
```

It validates saved forecasts against the source observations, evaluates all available predictions without filling gaps, then streams the workload to count forecast and observed-carbon coverage. It writes results under `results/forecasting/` (ignored by Git).

## Carbon dataset audit

| File | Contents and coverage | Provenance, zone, unit | Timestamp quality |
|---|---|---|---|
| `data/raw/carbon/india_west_carbon_intensity.csv` | 216 hourly observations, 2026-09-22 00:00 through 2026-09-30 23:00 UTC | CSV zone is IN-WE; `emissionFactorType=lifecycle`, `flowTraced=True`, and `isEstimated=False` for all 216 records. `docs/data_provenance.md` attributes the source to Electricity Maps but says to confirm retrieval source; no original download URL, retrieval date, API version, or license record is present. Unit is documented as gCO2eq/kWh in project docs, but the CSV does not encode it. | Explicit UTC (`Z`); no duplicate or missing timestamps; all 215 deltas are one hour. Values range 469–731. |
| `data/raw/carbon/additional/carbon_intensity_2025-01-01_to_2025-01-07.csv` | 336 interval records from 2025-01-01 00:00 through 2025-01-08 00:00 UTC | No provider, zone, unit, emission-factor type, estimation flags, or retrieval record in the file or repository docs. | UTC offsets; 30-minute `[from,to)` intervals; no duplicate starts or missing half-hour intervals. |
| `data/raw/carbon/additional/carbon_intensity_2025-01-01_to_2025-01-09.csv` | 432 interval records from 2025-01-01 00:00 through 2025-01-10 00:00 UTC | Same unverified provenance and metadata as the shorter interval file. | UTC offsets; 30-minute `[from,to)` intervals; no duplicate starts or missing half-hour intervals. |

The two January files overlap for all 336 timestamps in the shorter file, and all overlapping values match. They are still not merged: their unit, zone, provider, measurement definition, and compatibility with the IN-WE hourly lifecycle series are unverified. Their half-hour interval averages are also a different timestamp support from the main hourly point observations. The separate main dataset is from a different date and has stronger schema metadata, but it cannot be joined to January as one homogeneous time series without evidence that provenance and definitions match. No carbon files were combined for this evaluation.

## Existing method audit

### Rolling Seasonal Naive replay

`src/forecasting/rolling_forecast.py` sorts and requires continuous hourly source data. It uses target value at `target_index - 24` for each 1–4 hour lead. Since target index is origin plus lead, that seasonal input is strictly at or before the origin. The 216 observations are split chronologically at indices 129 (60%) and 172 (80%): 129 initial-history observations, 43 calibration observations, then rolling evaluation origins at indices 172–211. There are 40 origins and 160 predictions. Every origin contains leads 1–4; targets span indices 173–215.

The 90% conformal-style absolute residual threshold is estimated from the 43 calibration targets using the 24-hour seasonal baseline. It is fixed for the evaluation window. The empirical calibration residual quantile rank is `ceil((43+1)*0.9)=40`. Bounds are prediction ± threshold, with the lower bound clipped at zero. The calibration interval ends before the first evaluation origin. This avoids temporal leakage in the recorded backtest, but 43 serially dependent calibration residuals do not establish nominal future coverage. It is safer to describe the intervals as a calibration heuristic than to claim a distribution-free guarantee.

The persisted rolling file matches the expected 40 × 4 grid. The evaluation independently checks that target = origin + horizon, origin < target, target actuals match the main carbon CSV, `simulation_hour` matches the zero-based main-carbon index, bounds enclose the point forecast, and the persisted coverage flag matches the interval and actual.

### Other models and forecast artifacts

- `src/forecasting/seasonal_naive.py`, `baseline.py`, and the persistence evaluation use lagged observations. Those one-step predictions are chronologically valid when interpreted as rolling one-step updates, not as a single forecast made at the split for the whole test window.
- Random Forest and HistGradientBoosting fit rows strictly before the 80% split. Their lag/rolling features are shifted so each target feature uses observations strictly before that target. Test features use later observed test values as each successive one-step forecast origin advances. This is rolling one-step backtesting, not a fixed-origin multi-hour forecast.
- The initial model comparison in `docs/forecasting_documentation.md` reports a common 44-row chronological test and Seasonal Naive had lower recorded MAE/RMSE than the tested persistence and ML models. This is descriptive evidence from one short test window, not general superiority.
- `seasonal_naive_uncertainty_predictions.csv` has no recorded origin. `scripts/prepare_forecast_output.py` later assigns `target - 1 hour` as a provisional convention and resets `simulation_hour` to zero for its 44-row slice. This synthetic origin/timeline is unsuitable as proof of live availability and is not used here.
- `src/scheduler/forecast_adapter.py` maps UTC targets onto the carbon timeline. The validation pipeline adds the stricter origin/lead, interval, source-actual, and timeline checks before reporting eligibility.

## Evaluation results

Generated files:

- `results/forecasting/forecast_accuracy_by_horizon.csv`: prediction count, MAE, RMSE, signed mean error/bias, interval coverage, and mean interval width for the rolling model and both baselines, by lead and all leads.
- `results/forecasting/forecast_coverage_by_origin.csv`: prediction count, empirical interval coverage, and mean width for each origin.
- `results/forecasting/forecast_coverage.csv`: exact target window and workload coverage counts.
- `results/forecasting/forecast_evaluation_summary.json`: dataset audit, split/calibration description, workload counts, runtime, and limitations.
- `results/forecasting/forecast_accuracy_by_horizon.png` and `forecast_interval_coverage.png`.

Observed rolling backtest metrics (gCO2eq/kWh):

| Horizon | N | Seasonal Naive MAE | RMSE | Bias (prediction − actual) | Persistence MAE | 90% interval coverage | Mean interval width |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 h | 40 | 6.275 | 7.299 | +2.025 | 19.075 | 100% | 158 |
| 2 h | 40 | 6.000 | 6.771 | +2.700 | 36.975 | 100% | 158 |
| 3 h | 40 | 6.075 | 6.832 | +2.975 | 54.375 | 100% | 158 |
| 4 h | 40 | 6.150 | 6.870 | +3.150 | 71.125 | 100% | 158 |
| All leads | 160 | 6.125 | 6.946 | +2.713 | 45.388 | 100% | 158 |

The Seasonal Naive result is the persisted rolling model and is equal to the corresponding Seasonal Naive baseline. Persistence at each lead uses the observation available at the origin (the origin-time value); it does not recursively consume unknown future actuals. The observed 100% interval coverage on 160 correlated predictions is not evidence that future coverage will be 90% or better.

## Forecast eligibility and workload mapping

The workload uses relative `start_time` seconds. Per the existing simulator mapping, carbon row 0 is 2026-09-22 00:00 UTC, and each carbon observation is assigned a zero-based simulation-hour index. For a task released at second `s`, the baseline occupied hours are `floor(s/3600)` through `floor((s+duration−epsilon)/3600)`. The scheduler's historical forecast origin is the preceding whole-hour boundary (`floor(s/3600)−1` relative to carbon index 0). A task is **backtest forecast replay eligible** only if the persisted predictions for that exact origin cover every baseline occupied hour. This is coverage eligibility, not task feasibility.

In this dataset the persisted evaluation covers target hours 173–215, or 2026-09-29 05:00 through 2026-09-30 23:00 UTC, from 40 origins (2026-09-29 04:00 through 2026-09-30 19:00 UTC), four leads per origin, 160 prediction rows, and 43 distinct target hours. Under the simulator's prior-hour origin rule, the corresponding task release-hour buckets are 2026-09-29 05:00 through 2026-09-30 20:00 UTC inclusive; full task duration must fit in that origin's available lead rows. Every target has an observed carbon value, and every forecast origin precedes its target. The historical issue-time is not operationally logged, so these counts are for replay eligibility only; they must not be represented as verified live deployment coverage.

The streamed full workload coverage report records:

- 13,288,830 total tasks; 1,699,114 backtest forecast replay eligible and 11,589,716 outside/incomplete forecast replay coverage.
- All 13,288,830 task baseline intervals fit within the observed 216-hour carbon timeline. Therefore all can be included in actual-emissions evaluation **if they execute and their final scheduled interval remains inside the carbon timeline**.
- 13,288,758 tasks request at most the configured 8 CPU cores; 72 exceed capacity and are infeasible under that capacity configuration. Capacity-feasible tasks outside forecast coverage are not inherently infeasible: the existing simulator attempts its non-forecast earliest-feasible fallback, subject to contention and the one-hour delay limit.
- 11,589,716 forecast-ineligible tasks have a baseline interval inside the observed-carbon window and therefore remain possible fallback/actual-emissions candidates. Whether they actually execute after contention and rescheduling requires simulation; no full simulation was run in this phase.

No missing forecast hours or uncertainty values were filled. An absent origin/lead remains absent and contributes no prediction to forecast accuracy.

## Reproducibility and limitations

Run the evaluation with the command above. It reads the full workload in configurable CSV chunks (default 100,000); the complete Phase 3 audit, coverage scan, and plot generation took 43.0 seconds in this environment. Outputs include metric values, source paths, and SHA-256 hashes in JSON. The assessment is specific to the checked-in working data.

Remaining scientific limitations:

1. Main carbon source attribution is incomplete; original retrieval URL/date/API version/license are missing. January data have no verified zone or units and must remain separate.
2. Only nine days of hourly IN-WE carbon data are available. The 60/20/20 chronological split is one short sample; errors and interval misses are temporally dependent.
3. The forecast replay records modeled origins, not service logs proving the model output was available at that historical wall-clock time. It is a backtest, never live deployment evidence.
4. Forecast eligibility covers at most four hours from the available origins and only the final 43 observed target hours. Most workload tasks are outside that forecast window, though the existing fallback can still execute them.
5. Workload seconds are mapped onto carbon rows by index; workload timestamps do not identify real calendar times. Emissions additionally depend on the assumed 10 W/core energy model.
6. This phase did not run the full scheduler simulation. Aggregate capacity contention, final schedule carbon coverage, and realized fallback execution counts remain unmeasured.
