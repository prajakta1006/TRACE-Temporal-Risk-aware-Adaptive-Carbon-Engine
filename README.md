

\# TRACE — Temporal Risk-aware Adaptive Carbon Engine



A research project exploring carbon-aware workload scheduling using workload traces, carbon-intensity data, forecasting, and rolling-horizon scheduling.



\## Project structure



\- `src/data/` — workload and carbon data integration

\- `src/forecasting/` — carbon-intensity forecasting

\- `src/scheduler/` — carbon-aware scheduling

\- `src/evaluation/` — experiments and evaluation

\- `tests/` — automated tests

\- `data/raw/` — locally stored source datasets

\- `data/processed/` — generated datasets

\- `results/` — experiment outputs



\## Data policy



Large datasets and generated outputs are excluded from Git. Document source URLs, units, time ranges, missing values, and simulation assumptions.

## Data Integration and Simulation Assumptions

### Workload data
- Workload traces are loaded from CSV files.
- Required fields include job name, task name, start time,
  end time, duration in seconds, and CPU cores.
- The loader validates required columns and rejects invalid
  or negative duration and CPU-core values.

### Energy estimation
- Estimated CPU power is 10 watts per allocated CPU core.
- Estimated energy is calculated as:

  energy_kwh = duration_seconds * cpu_cores * 10 / 3,600,000

- This is a simplified estimate, not measured server energy.
- Memory, storage, networking, idle power, and cooling overhead
  are not explicitly modeled.

### Carbon-intensity data
- The current dataset uses zone IN-WE (India West).
- The tested file contains 216 hourly records.
- Timestamps are parsed as UTC and sorted chronologically.
- The source's units and lifecycle methodology must be verified
  against its documentation before final reporting.

### Simulation-time mapping
- Workload start_time is treated as relative simulation seconds.
- Carbon records are assigned sequential simulation-hour indices,
  starting with index zero.
- A task's full estimated energy is multiplied by the carbon
  intensity assigned to its start hour.
- Tasks crossing hourly boundaries are not split across hours.
- Missing carbon-hour matches raise an error.
- This mapping is a simulation assumption, not a match between
  the workload's original timestamps and real-world carbon times.

### Reproducibility and data handling
- Raw and processed datasets are kept out of Git.
- Automated tests use small synthetic datasets.
- Reported emissions are model estimates and depend on the
  energy model and simulation-time mapping assumptions.



