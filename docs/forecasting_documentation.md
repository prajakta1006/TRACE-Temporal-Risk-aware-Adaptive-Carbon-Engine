
# TRACE – Carbon Forecasting Documentation

## 1. Overview

This module is part of Person 2's contribution to the TRACE (Temporal Risk-aware Adaptive Carbon Engine) project.

Its purpose is to forecast carbon intensity and estimate prediction uncertainty so that the scheduling module can make informed carbon-aware decisions.

The forecasting module includes:
- Exploratory data analysis
- Statistical forecasting baselines
- Machine learning forecasting models
- Model evaluation and comparison
- Prediction interval estimation
- Forecast output preparation for scheduler integration

## 2. Dataset Description

**Dataset:** `india_west_carbon_intensity.csv`

| Property | Value |
|---|---|
| Carbon zone | IN-WE |
| Geographic region | India West |
| Number of observations | 216 |
| First timestamp | 2026-09-22 00:00 UTC |
| Last timestamp | 2026-09-30 23:00 UTC |
| Sampling frequency | Hourly |
| Missing values | 0 |
| Duplicate timestamps | 0 |
| Non-hourly intervals | 0 |
| Minimum intensity | 469 |
| Maximum intensity | 731 |
| Mean intensity | 611.77 |

**Carbon-intensity unit:** gCO2eq/kWh.

The dataset contains nine days of hourly carbon-intensity observations. All timestamps are timezone-aware UTC timestamps.

The limited dataset duration is an important limitation when interpreting forecasting performance.

## 3. Exploratory Data Analysis

Exploratory analysis was performed to understand temporal patterns and the distribution of carbon intensity.

The analysis generated:
- Carbon intensity over time
- Average carbon intensity by hour of day
- Daily average carbon intensity
- Carbon intensity distribution
- Summary statistics

### Observations

1. Carbon intensity exhibits recurring hourly fluctuations.
2. Lower hourly averages were observed around 05:00–07:00 UTC.
3. Higher hourly averages occurred during several afternoon and evening hours.
4. Daily averages varied across the nine-day observation period.
5. The short observation window does not establish a reliable long-term seasonal pattern.

EDA outputs are stored locally in `results/carbon_eda/`.

## 4. Forecasting Models

Four forecasting approaches were evaluated.

### 4.1 Persistence Baseline

Uses the previous hour's observed carbon intensity as the next-hour prediction.

### 4.2 Seasonal Naive Baseline

Uses the carbon intensity observed 24 hours earlier as the prediction for the current hour.

This baseline captures recurring daily patterns and achieved the best evaluation results.

### 4.3 Random Forest Regressor

A machine learning model using:
- Hour of day
- Previous-hour carbon intensity
- Two-hour lag
- 24-hour lag
- Three-hour rolling mean

Model configuration:
- Number of estimators: 200
- Maximum depth: 5
- Minimum samples per leaf: 2
- Random state: 42

### 4.4 HistGradientBoosting Regressor

A gradient boosting model using the same engineered features.

Model configuration:
- Maximum iterations: 100
- Learning rate: 0.05
- Maximum leaf nodes: 7
- L2 regularization: 1
- Random state: 42

## 5. Evaluation Methodology

A chronological 80:20 train-test split was used for initial model comparison.

- Total observations: 216
- Training observations: 172
- Test observations: 44

The machine learning models had 148 usable training observations after accounting for lag features.

The evaluation metrics were:

- MAE: Mean Absolute Error
- RMSE: Root Mean Squared Error
- sMAPE: Symmetric Mean Absolute Percentage Error

The final 44 test timestamps were shared across the four model comparisons.

## 6. Model Comparison Results

| Model | MAE | RMSE | sMAPE |
|---|---:|---:|---:|
| Persistence | 18.7955 | 29.1099 | 3.2287% |
| Seasonal Naive (24h) | 6.5682 | 7.6767 | 1.0741% |
| Random Forest | 8.5610 | 12.4124 | 1.3860% |
| HistGradientBoosting | 9.9204 | 13.4447 | 1.6007% |

### Selected Model

Seasonal Naive (24h) achieved the lowest MAE, RMSE, and sMAPE among the evaluated models.

It was therefore selected for the preliminary uncertainty estimation and forecast sample.

The results are preliminary because they are based on a short dataset and a single chronological test window.

## 7. Prediction Uncertainty Estimation

Prediction uncertainty was estimated using a chronological calibration approach with the Seasonal Naive model.

The dataset was divided into:

| Section | Observations |
|---|---:|
| Initial history | 129 |
| Calibration | 43 |
| Final test | 44 |

Absolute prediction errors from the calibration period were sorted.

A finite-sample 90% conformal-style error threshold was calculated using the calibration errors.

### Prediction Interval

The prediction interval was constructed using the calibrated error threshold:

- Lower bound = prediction minus error threshold
- Upper bound = prediction plus error threshold

The lower bound was clipped at zero because negative carbon intensity is not meaningful for this dataset.

### Uncertainty Evaluation Results

| Metric | Result |
|---|---:|
| Confidence level | 90% |
| Calibration observations | 43 |
| Test observations | 44 |
| Error threshold | 79 gCO2eq/kWh |
| Empirical test coverage | 100% |
| Average interval width | 158 gCO2eq/kWh |

All 44 test observations fell within their prediction intervals.

The intervals are relatively wide. The observed coverage does not guarantee 90% coverage on future data. The short time series and temporal dependence limit the strength of statistical conclusions.

## 8. Final Forecast Output

The final evaluation forecast sample is stored locally at:

`results/forecasting/final_forecast_sample.csv`

It contains 44 forecast records and the following columns:

| Column | Description |
|---|---|
| timestamp_utc | Target hourly interval in ISO 8601 UTC format |
| simulation_hour | Provisional zero-based index for this sample |
| predicted_carbon_intensity | Predicted carbon intensity |
| lower_bound | Lower 90% prediction bound |
| upper_bound | Upper 90% prediction bound |
| forecast_origin_utc | Provisional one-hour-prior forecast origin |
| forecast_horizon | Forecast horizon in hours; currently 1 |
| model_name | Forecasting model identifier |

### Important Integration Notes

1. `simulation_hour` currently starts at zero for the 44-row evaluation sample. It is not yet confirmed against the workload scheduler's global simulation timeline.
2. The forecast origin is currently represented as one hour before the target interval. It is a provisional convention, not a recorded execution timestamp.
3. The forecast horizon is one hour because these are rolling one-step-ahead predictions.
4. Person 3 must validate the simulation-hour mapping before production scheduler integration.
5. The scheduler must use the same carbon-intensity unit, gCO2eq/kWh, when calculating emissions.

## 9. Reproducibility

Run the following commands from the project root.

### Exploratory Data Analysis

```powershell
python -m scripts.explore_carbon_data
```

### Baseline and ML Forecasting

```powershell
python -m src.forecasting.baseline
python -m src.forecasting.seasonal_naive
python -m src.forecasting.random_forest
python -m src.forecasting.hist_gradient_boosting
```

### Model Evaluation

```powershell
python -m src.evaluation.evaluate_baseline
python -m src.evaluation.evaluate_seasonal_naive
python -m src.evaluation.evaluate_random_forest
python -m src.evaluation.evaluate_hist_gradient_boosting
python -m src.evaluation.compare_baselines
```

### Uncertainty Estimation

```powershell
python -m src.forecasting.uncertainty
```

### Final Forecast Output

```powershell
python scripts/prepare_forecast_output.py
```

Generated datasets and result files are excluded from Git through `.gitignore`.

## 10. Limitations and Future Improvements

- Only nine days of hourly carbon-intensity data are currently available.
- The evaluation uses one chronological train-test split.
- Temporal dependence may affect prediction interval calibration.
- The prediction intervals are relatively wide.
- The current forecasts are rolling one-step-ahead predictions, not long-horizon forecasts generated entirely in advance.
- The simulation-hour origin must be aligned with the workload scheduler before integration.
- Further evaluation should use a longer dataset and rolling-origin backtesting.
- Future work may investigate adaptive or time-dependent prediction intervals.

## 11. Person 2 Deliverables

Completed:
- Carbon dataset validation
- Exploratory data analysis
- Persistence and Seasonal Naive baselines
- Random Forest and HistGradientBoosting models
- Chronological model evaluation
- Model comparison
- 90% prediction interval estimation
- Final evaluation forecast sample generation
- Forecast CSV validation

Pending:
- Final scheduler timeline alignment with Person 3
- Integration validation
- Final documentation and code submission
