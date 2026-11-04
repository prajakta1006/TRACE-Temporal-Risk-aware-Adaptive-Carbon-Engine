\# Person 3 – Scheduler Handover Documentation



\## 1. Overview



Person 3 implemented the risk-aware carbon scheduling module for TRACE (Temporal Risk-aware Adaptive Carbon Engine).



The scheduler identifies alternative task execution times that can reduce carbon emissions while respecting CPU capacity and accounting for forecast uncertainty.



\## 2. Implemented modules



| Module | Responsibility |

|---|---|

| `carbon\_ranking.py` | Ranks forecast hours using risk-adjusted carbon intensity |

| `carbon\_benefit.py` | Calculates expected carbon savings and uncertainty penalties |

| `candidate\_selection.py` | Generates feasible candidate execution times |

| `constraints.py` | Validates CPU capacity and scheduling constraints |

| `forecast\_adapter.py` | Converts Person 2's forecast CSV into scheduler input |

| `scheduler.py` | Selects the best feasible task candidate |



\## 3. Main scheduler interface



Function:



`select\_task\_candidate()`



Location: `src/scheduler/scheduler.py`



Inputs:



\- `task`: pandas Series containing task information.

\- `forecasts`: pandas DataFrame containing hourly forecasts.

\- `current\_time`: current simulation time in seconds.

\- `scheduled\_tasks`: existing scheduled tasks.

\- `cpu\_capacity`: available CPU cores (default 8).

\- `forecast\_hours`: planning horizon (default 4).

\- `max\_delay\_seconds`: maximum scheduling delay (default 3600).

\- `risk\_weight`: uncertainty penalty weight (default 0.5).



Required task columns:



\- `start\_time`

\- `duration\_seconds`

\- `cpu\_cores`

\- `energy\_kwh`



Required forecast columns:



\- `simulation\_hour`

\- `predicted\_carbon\_intensity`

\- `upper\_bound`



Output:



Returns the selected candidate as a dictionary or `None` when no beneficial feasible candidate is found.



Important output fields:



\- `start\_time`

\- `end\_time`

\- `risk\_adjusted\_savings\_g`

\- `expected\_savings\_g`

\- `uncertainty\_penalty\_g`

\- `candidate\_predicted\_carbon`

\- `candidate\_upper\_bound`



\## 4. Risk-adjusted carbon benefit



Expected carbon savings:



`expected\_savings = baseline\_emissions - candidate\_emissions`



Uncertainty penalty:



`uncertainty\_penalty = energy × (baseline\_uncertainty + candidate\_uncertainty)`



Risk-adjusted savings:



`risk\_adjusted\_savings = expected\_savings - risk\_weight × uncertainty\_penalty`



The initial experiment uses risk weight 0.5.



The uncertainty penalty is a heuristic based on upper prediction bounds. It is not a formal statistical lower confidence bound.



\## 5. Initial experiment settings



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



\## 6. Long-running task behaviour



Candidate starts may fall within the planning horizon even when the task finishes after that horizon.



The scheduler requires complete forecast coverage for both the original and candidate execution periods before calculating full-duration carbon savings.



A missing forecast hour causes the candidate to be skipped. Missing baseline coverage raises a ValueError.



The scheduler does not itself implement running-task protection or hourly replanning.



\## 7. Forecast adapter



Function:



`load\_scheduler\_forecasts()`



Location: `src/scheduler/forecast\_adapter.py`



Inputs:



\- Forecast CSV path.

\- Explicit simulation start UTC timestamp.



The adapter converts UTC timestamps into simulation-hour indices.



Person 4 must supply a fresh forecast covering the complete execution periods being evaluated. Person 2's existing historical test predictions should not be treated as live future forecasts.



\## 8. Integration responsibilities for Person 4



Person 4 should integrate the scheduler with the rolling-horizon controller.



Required integration work:



1\. Call `select\_task\_candidate()` at each replanning point.

2\. Preserve running and committed tasks.

3\. Pass existing scheduled tasks into the scheduler for CPU validation.

4\. Supply updated four-hour forecasts.

5\. Maintain task assignments across replanning cycles.

6\. Evaluate completed schedules using observed carbon intensity.

7\. Compare TRACE against baseline scheduling approaches.



\## 9. Known limitations



\- The scheduler is a task-level decision engine, not a complete rolling-horizon controller.

\- Running-task protection must be implemented by the rolling-horizon controller.

\- The upper-bound uncertainty penalty is heuristic.

\- Full workload experiments and retrospective observed-carbon evaluation remain pending.

\- The 8-core capacity and one-hour maximum delay are experimental assumptions, not properties supplied by the workload dataset.

\- Tasks requiring more than 8 cores must be reported as infeasible under the initial capacity scenario.



\## 10. Testing



Run the complete test suite:



`py -m pytest -q`



Latest reported result: 41 tests passed.



\## 11. Person 3 deliverables



\- Risk-aware carbon ranking.

\- Carbon-benefit calculation.

\- Candidate execution-time generation.

\- CPU capacity validation.

\- Forecast adapter.

\- Main scheduling decision engine.

\- Unit tests.

\- This integration handover document.



