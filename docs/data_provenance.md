\# TRACE Carbon Data Provenance



\## 1. Dataset identity



\- Provider: Electricity Maps (confirm the original retrieval source).

\- Zone: IN-WE

\- Dataset file: india\_west\_carbon\_intensity.csv

\- Temporal coverage: 2026-09-22 00:00 UTC to 2026-09-30 23:00 UTC

\- Records: 216

\- Observed interval: hourly

\- Timestamp timezone: UTC



\## 2. Carbon intensity



\- Source field: carbonIntensity

\- Unit: gCO2eq/kWh (verify against the source documentation).

\- Emission factor type: lifecycle

\- Flow traced: True in the five sample rows inspected.

\- isEstimated: False in the five sample rows inspected.

\- estimationMethod: blank in the five sample rows inspected.



Check the complete dataset for consistent metadata values. The source's isEstimated flag describes the carbon data, not the accuracy of TRACE's task-energy estimates.



\## 3. Workload energy model



\- Assumed power: 10 watts per allocated CPU core.

\- Energy (kWh) = duration\_seconds × cpu\_cores × 10 / 3,600,000.

\- This is a modeling assumption, not measured server power.



\## 4. Emissions calculation



\- Estimated emissions = energy\_kwh × carbon intensity.

\- Hourly allocation splits task energy proportionally across runtime.

\- Tasks crossing hourly boundaries use the intensity assigned to each occupied simulation hour.



\## 5. Simulation-time mapping limitation



Workload start\_time is treated as relative simulation seconds. Carbon records are sorted chronologically and assigned simulation-hour indices starting at zero.



This is a simulation mapping, not a direct alignment of workload timestamps with the carbon dataset's real dates.



Tasks extending outside the available carbon window are rejected.



\## 6. Data quality



The checked dataset version had:



\- Workload rows: 13,288,830

\- Carbon rows: 216

\- Missing required workload values: 0

\- Negative workload durations: 0

\- Negative CPU allocations: 0

\- Workload duration mismatches: 0

\- Duplicate job/task pairs: 0

\- Duplicate carbon timestamps: 0

\- Missing carbon hours: 0



Regenerate these results if the input files change.



\## 7. Source documentation



Electricity Maps API reference: https://app.electricitymaps.com/docs/reference/carbon-intensity/latest



Add the original dataset download URL, retrieval date, API version, and applicable license when available.

