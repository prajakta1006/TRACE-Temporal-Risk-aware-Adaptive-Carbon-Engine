# Person 3 - Scheduler Handover Documentation

## 1. Overview

Person 3 implemented the risk-aware carbon scheduling module for TRACE (Temporal Risk-aware Adaptive Carbon Engine).

The scheduler identifies alternative task execution times that can reduce carbon emissions while respecting CPU capacity and accounting for forecast uncertainty.

The implementation also includes integration with Person 2's four-hour rolling forecast generation and actual-carbon schedule evaluation.

## 2. Implemented modules

| Module | Responsibility |
|---|---|
| `carbon_ranking.py` | Ranks forecast hours using risk-adjusted carbon intensity |
| `carbon_benefit.py` | Calculates expected carbon savings and uncertainty penalties |
| `candidate_selection.py` | Generates feasible candidate execution times |
| `constraints.py` | Validates CPU capacity and scheduling constraints |
| `forecast_adapter.py` | Loads forecast CSV files and maps UTC timestamps to simulation hours |
| `scheduler.py` | Selects the best feasible task candidate |
| `rolling_scheduler.py` | Connects rolling forecast origins to the existing scheduler |
| `rolling_forecast.py` | Generates historical four-hour rolling Seasonal Naive forecasts |
| `scheduler_metrics.py` | Evaluates schedule emissions using observed carbon intensity |

## 3. Main scheduler interface

Function:

`select_task_candidate()`

Location: `src/scheduler/scheduler.py`

Inputs:

- `task`: pandas Series containing task information.
- `forecasts`: pandas DataFrame containing hourly forecasts.
- `current_time`: current simulation time in seconds.
- `scheduled_tasks`: existing scheduled tasks.
- `cpu_capacity`: available CPU cores (default 8).
- `forecast_hours`: planning horizon (default 4).
- `max_delay_seconds`: maximum scheduling delay (default 3600).
- `risk_weight`: uncertainty penalty weight (default 0.5).

Required task columns:

- `start_time`
- `duration_seconds`
- `cpu_cores`
- `energy_kwh`

Required forecast columns:

- `simulation_hour`
- `predicted_carbon_intensity`
- `upper_bound`

Output:

Returns the selected candidate as a dictionary or `None` when no beneficial feasible candidate is found.

Important output fields:

- `start_time`
- `end_time`
- `risk_adjusted_savings_g`
- `expected_savings_g`
- `uncertainty_penalty_g`
- `candidate_predicted_carbon`
- `candidate_upper_bound`

## 4. Risk-adjusted carbon benefit

Expected carbon savings:

`expected_savings = baseline_emissions - candidate_emissions`

Uncertainty penalty:

`uncertainty_penalty = energy * (baseline_uncertainty + candidate_uncertainty)`

Risk-adjusted savings:

`risk_adjusted_savings = expected_savings - risk_weight * uncertainty_penalty`

The initial experiment uses risk weight 0.5.

The uncertainty penalty is a heuristic based on upper prediction bounds. It is not a formal statistical lower confidence bound.

## 5. Initial experiment settings

| Parameter | Initial value |
|---|---:|
| Carbon zone | IN-WE |
| CPU capacity | 8 cores |
| Power assumption | 10 W/core |
| Planning horizon | 4 hours |
| Replanning interval | 1 hour |
| Maximum scheduling delay | 1 hour |
| Risk weight | 0.5 |
| Forecast uncertainty treatment | Upper prediction bound |

These are experiment assumptions and should remain configurable.

## 6. Rolling forecast generation

Location:

`src/forecasting/rolling_forecast.py`

The module generates four hourly Seasonal Naive predictions at each eligible historical forecast origin.

Model:

`prediction(t + h) = observed_carbon(t + h - 24)`

where `h` ranges from 1 to 4.

Uncertainty:

- Uses the existing chronological calibration approach.
- Uses a 90% conformal-style calibration threshold.
- Generates lower and upper prediction bounds.
- Uses the same calibration threshold across the four forecast horizons.

Generated output:

`results/forecasting/rolling_seasonal_naive_forecasts.csv`

Columns:

- `forecast_origin_utc`
- `timestamp_utc`
- `simulation_hour`
- `horizon_hours`
- `predicted_carbon_intensity`
- `lower_bound`
- `upper_bound`
- `actual_carbon_intensity`
- `covered`

Initial generation results:

| Metric | Result |
|---|---:|
| Carbon observations | 216 |
| Forecast horizon | 4 hours |
| Forecast origins | 40 |
| Forecast rows | 160 |
| Calibration samples | 43 |
| 90% error threshold | 79 gCO2eq/kWh |
| Coverage at horizon 1 | 100% |
| Coverage at horizon 2 | 100% |
| Coverage at horizon 3 | 100% |
| Coverage at horizon 4 | 100% |

Important limitations:

- These are historical rolling replay forecasts, not live future forecasts.
- The 100% coverage result is based on only 40 historical origins and does not establish future 90% coverage.
- The original Person 2 uncertainty evaluation module and its outputs are preserved.
- The existing 44-row historical test prediction file must not be treated as a live rolling forecast.

## 7. Forecast adapter and rolling scheduler integration

Forecast adapter:

`src/scheduler/forecast_adapter.py`

Function:

`load_scheduler_forecasts()`

The adapter:

- Loads forecast CSV data.
- Converts timestamps to UTC.
- Maps timestamps to simulation-hour indices.
- Validates forecast values and upper bounds.
- Supports both the original unique-timestamp forecast format and the new rolling forecast format.
- Preserves rolling forecast origins and horizon information.

Additional function:

`select_forecast_origin()`

This selects only the forecasts belonging to a particular rolling forecast origin.

Rolling scheduler:

`src/scheduler/rolling_scheduler.py`

Main function:

`select_task_candidate_at_origin()`

Inputs:

- Task information.
- Complete rolling forecast DataFrame.
- Current forecast origin UTC.
- Simulation start UTC.
- Existing scheduled tasks.
- CPU capacity.
- Forecast horizon.
- Maximum scheduling delay.
- Risk weight.

The function selects exactly four forecasts for the requested origin and passes them to the existing `select_task_candidate()` function.

It currently expects four forecast horizons: 1, 2, 3 and 4.

A task is not rescheduled if its complete baseline or candidate execution period is not covered by the selected forecast data.

## 8. Actual-carbon schedule evaluation

Location:

`src/evaluation/scheduler_metrics.py`

Functions:

- `calculate_schedule_emissions()`
- `compare_schedules()`

These functions evaluate task schedules using observed carbon intensity rather than predicted carbon intensity.

The evaluation calculates:

- Baseline emissions.
- TRACE schedule emissions.
- Carbon savings in grams.
- Carbon reduction percentage.

Energy is distributed uniformly across the task duration when calculating hourly emissions.

Complete observed-carbon coverage is required for every evaluated task.

## 9. Preliminary scheduling experiment

A synthetic task was used to verify the rolling forecast and scheduler integration.

Experiment settings:

| Parameter | Value |
|---|---:|
| Forecast origin | 2026-09-30 00:00 UTC |
| Original execution | 01:00 UTC |
| Task duration | 1800 seconds |
| CPU cores | 2 |
| Energy | 0.005 kWh |
| Maximum delay | 3600 seconds |
| CPU capacity | 8 cores |

Forecasted carbon intensities:

| Hour | Predicted intensity | Upper bound |
|---|---:|---:|
| 01:00 UTC | 706 | 785 |
| 02:00 UTC | 649 | 728 |
| 03:00 UTC | 569 | 648 |
| 04:00 UTC | 514 | 593 |

Risk-weight sensitivity:

| Risk weight | Risk-adjusted savings | Decision |
|---|---:|---|
| 0.1 | 0.206 g | Accepted |
| 0.2 | 0.127 g | Accepted |
| 0.3 | 0.048 g | Accepted |
| 0.5 | -0.110 g | Rejected |

At the initial risk weight of 0.5, the scheduler correctly rejected the candidate because its risk-adjusted savings were negative.

At a risk weight of 0.1, the scheduler selected a one-hour delay.

Retrospective actual-carbon evaluation for that accepted decision:

| Metric | Original | TRACE |
|---|---:|---:|
| Carbon intensity | 701 | 637 gCO2eq/kWh |
| Emissions | 3.505 g | 3.185 g |

Actual carbon savings: 0.320 g.

Actual carbon reduction: 9.13%.

This is a single synthetic-task proof of concept, not a full-workload performance result.

## 10. Integration responsibilities for Person 4

Person 4 should integrate the scheduler with the rolling-horizon controller.

Required integration work:

1. Call `select_task_candidate_at_origin()` at each hourly replanning point.
2. Preserve running and committed tasks.
3. Pass existing scheduled tasks into the scheduler for CPU validation.
4. Supply the correct four-hour rolling forecasts for each origin.
5. Maintain task assignments across replanning cycles.
6. Handle tasks whose execution periods exceed forecast coverage.
7. Evaluate completed schedules using observed carbon intensity.
8. Compare TRACE against baseline scheduling approaches.
9. Report infeasible tasks and scheduling failures.

## 11. Known limitations

- The scheduler is a task-level decision engine, not a complete rolling-horizon controller.
- Running-task protection must be implemented by the rolling-horizon controller.
- The upper-bound uncertainty penalty is heuristic.
- The rolling forecasts are historical replay forecasts, not live future predictions.
- Forecast coverage is limited to the eligible historical origins.
- Full-workload scheduler performance evaluation remains pending.
- The 8-core capacity and one-hour maximum delay are experimental assumptions, not properties supplied by the workload dataset.
- Tasks requiring more than 8 cores must be reported as infeasible under the initial capacity scenario.
- Tasks extending beyond available forecast coverage cannot be evaluated by the current four-hour integration without an additional forecasting strategy.

## 12. Testing

Run the complete test suite:

`py -m pytest -q`

Latest reported result:

**47 tests passed.**

This includes the original scheduler tests, rolling forecast adapter integration tests, rolling scheduler tests and actual-carbon evaluation tests.

## 13. Person 3 deliverables

- Risk-aware carbon ranking.
- Carbon-benefit calculation.
- Candidate execution-time generation.
- CPU capacity validation.
- Forecast adapter supporting rolling origins.
- Main scheduling decision engine.
- Four-hour rolling forecast generation integration.
- Rolling scheduler integration.
- Actual-carbon schedule evaluation.
- Unit and integration tests.
- This integration handover document.



