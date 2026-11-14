# TRACE Technical Demonstration Script

**Target duration:** 5–7 minutes. Presenter: [PRESENTER NAME]. Use existing artifacts; do not launch the full simulation during the demo.

## 0:00–0:40 — Introduce the project

“TRACE is a carbon-aware scheduling prototype. It compares FIFO, earliest-feasible, and a forecast-guided policy under CPU and deadline constraints. The large Phase 6 run is already complete, so today I’ll inspect its validated outputs rather than start a multi-hour job.”

Show the repository root and README. Point out that datasets and full-scale outputs are local ignored artifacts, not bundled in Git.

## 0:40–1:30 — Show inputs and validation

Open `docs/TRACE_FINAL_PROJECT_AUDIT.md` and the Phase 2 validation summary. Explain the 13,288,830-row chronological workload and stable `source_row` / `task_id` identity. Note the 72 over-capacity requests and that they remain counted as infeasible.

## 1:30–2:25 — Explain forecasts and policy

Show `docs/TRACE_SCIENTIFIC_METHODOLOGY_AND_RESULTS.md`. Explain the 24-hour seasonal-naive replay, four leads, and forecast eligibility. Emphasize that historical replay does not establish live forecast availability. Describe the uncertainty-adjusted score and earliest-feasible fallback without claiming formal calibration.

## 2:25–3:20 — Inspect ledger integrity

Open `results/phase6/independent_validation/independent_validation.json` and `cross_check_report.json`. Show per-policy row/unique counts, zero missing/duplicate/unexpected IDs, zero sequence/identity errors, SHA-256, checkpoint offset agreement, and zero CPU/task constraint violations. Mention the independent SQLite uniqueness index is disk-backed.

## 3:20–4:20 — Explain emissions

Open `emissions_recalculation.json`. Show the 10 W/core assumption, exact executed populations, observed IN-WE carbon series, and per-task energy/emissions recomputation. Point out that 10 W/core is modeled rather than measured and that predictions are only used to schedule.

## 4:20–5:30 — Present findings

Show the strategy table in `docs/TRACE_FINAL_EVALUATION.md`. Clarify the populations: FIFO completed 297,143; earliest-feasible and TRACE completed 313,268. Then show the common population of 165,474 tasks and the 0.1836 g (0.00403%) TRACE/FIFO difference. State that this does not demonstrate material superiority.

## 5:30–6:20 — Recovery and tests

Show the run progress/completion records and checkpoint recovery documentation. Explain that the run resumed from a durable checkpoint and that the ledgers reconcile with committed offsets. State the verified suite result: 93 passed, one third-party deprecation warning; the first attempt's temp/cache permission errors were fixed by dedicated writable directories.

## 6:20–6:50 — Close

“TRACE demonstrates a full-scale, auditable scheduling experiment. The main next steps are longer verified carbon data, recorded live forecast issue times, measured system energy, and broader workloads. The current evidence supports this one run and its limits.”

## Demo safety

Do not run `--full-run`, `--resume-full`, or an unbounded `--mode full` command on stage. Do not edit or regenerate Phase 6 outputs during the demonstration. Use JSON/Markdown artifacts already on disk.
