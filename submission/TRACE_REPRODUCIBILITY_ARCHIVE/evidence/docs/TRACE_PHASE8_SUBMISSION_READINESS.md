# TRACE Phase 8 Submission Readiness

## Overall status

**READY AFTER TEAM ACTIONS**

The technical evidence is internally consistent with the completed Phase 6 machine-readable outputs and independent checks. Submission still requires confirmed team/institution details and an explicit carbon-data licensing/redistribution decision. The reproducibility archive is reference-based and is not self-contained.

## Seven Phase 8 files reviewed

Reviewed the current contents of:

- `docs/TRACE_FINAL_EVALUATION.md`
- `docs/TRACE_FINAL_PRESENTATION.md`
- `docs/TRACE_FINAL_PROJECT_AUDIT.md`
- `docs/TRACE_FINAL_REPORT.md`
- `docs/TRACE_PHASE6_EXECUTION.md`
- `docs/TRACE_REPRODUCIBILITY_AND_RUNBOOK.md`
- `docs/TRACE_SCIENTIFIC_METHODOLOGY_AND_RESULTS.md`

The historical Phase 4–5 reports now identify themselves as snapshots. The Phase 3 forecasting report similarly identifies its “simulation not run” statement as historical. Its original machine-readable forecast summary remains untouched and contains a stale `full simulation not run` limitation string; Phase 6 completion and independent ledger outputs are the authority for scheduler execution status. The 0.00403% TRACE/FIFO common-population difference is consistently described as small, specific to this run, and not evidence of general or statistically significant superiority.

## Additional files created or updated

- Added `docs/TRACE_CARBON_DATA_PROVENANCE.md` and `docs/TRACE_CARBON_HASH_RECONCILIATION.md`.
- Added this acceptance report and `submission/TEAM_INFORMATION_TO_COMPLETE.md`.
- Added `submission/TRACE_REPRODUCIBILITY_ARCHIVE/ARCHIVE_README.md` and `ARCHIVE_MANIFEST.csv`.
- Updated Phase 6 hash explanations, the seven reviewed deliverables where needed, the Phase 3/4/5 historical context labels, README links, and runbook safety notes.
- No scheduler or forecasting algorithm was changed.

## Carbon provenance findings

The local main input is `data/raw/carbon/india_west_carbon_intensity.csv`: 23,438 bytes, zone label IN-WE, 216 hourly UTC records spanning 2026-09-22 00:00 to 2026-09-30 23:00, intensity field `carbonIntensity` (469–731), and local metadata flags `emissionFactorType=lifecycle`, `flowTraced=True`, `isEstimated=False` on all rows. Project documentation attributes the data to Electricity Maps, but the original acquisition record is absent. The exact retrieval URL/endpoint, retrieval date/API version, and license/redistribution terms are **not verified**. The unit gCO2eq/kWh is documented and consistent with the provider's current API documentation, but the local CSV has no unit column and the original response is unavailable.

The scheduler filters the selected zone, parses timestamps as UTC, converts intensity to numeric, sorts by timestamp, and maps row order to relative simulation hours. It did not combine the extra January 2025 half-hour datasets. Their provider, zone, units, and license also remain unverified. Before public redistribution, the team must identify the source transaction and confirm the applicable terms for the raw data and derived forecast.

## Carbon hash reconciliation

The raw-file SHA-256 is `d6b4eaf55d2118e5f8e4096971bb4aea75f6f87d8281f0cb9a9d672e5c468108`; it hashes the 23,438 raw CSV bytes and is recorded in the full-run configuration. The normalized timeline SHA-256 is `789c3264423c92b0c527b19633348ab653e21002cb2f04760070ce1c650b79f3`; it hashes UTF-8 CSV serialization of normalized UTC timestamps and numeric intensity for the selected zone, sorted chronologically. It appears in both preflight reports and the checkpoint compatibility configuration.

The hash functions both use SHA-256 but hash different representations; the values are not interchangeable. Current raw bytes match the raw hash, and the current normalized timeline matches the preflight/checkpoint hash. The checkpoint completed 13,288,830 tasks with this normalized timeline fingerprint. The preflight JSON omits its carbon path and original command line, so exact historic file selection at preflight cannot be proved from that report alone; project defaults/run configuration indicate the main IN-WE file. There is no evidence of changed normalized values. The discrepancy is explained as a representation difference, with a limited historical path-record gap; emissions were independently recalculated from current raw observations and match the ledgers. See `TRACE_CARBON_HASH_RECONCILIATION.md` for details.

## Independent evidence consistency

Machine evidence inspected: the three independent reports; `final_evaluation.json`; `event_run_summary.json`; `execution_summary.csv`; run configuration; initial/resume preflight reports; checkpoint database; completion marker; progress log; validation summary; rolling forecast evaluation output; and all three ledgers.

| Check | Verified result |
|---|---|
| Source and each ledger row count | 13,288,830 |
| Unique expected IDs per ledger | 13,288,830 |
| Missing / duplicate / unexpected IDs | 0 / 0 / 0 per ledger |
| Sequence / source-row identity errors | 0 / 0 per ledger |
| Independent CPU / task constraint violations | 0 / 0 per strategy |
| Independently observed peak allocated CPU | 8 cores |
| Over-capacity task requests | 72, classified infeasible in each strategy |
| Common completed and observed-covered population | 165,474 IDs |
| Common-set TRACE vs FIFO emissions | TRACE lower by 0.1836 g CO2e (0.00403%) |

The independent comparison confirms the row counts, mutually exclusive task states, emissions-covered populations, energy, emissions, and checkpoint offsets match the engine summary and saved evaluation. Independent row-wise emissions recomputation uses all executed tasks (297,143 FIFO; 313,268 earliest-feasible; 313,268 TRACE); every such scheduled interval is covered by the 216 observed IN-WE rows. The 10 W/core value is an assumption, not measured server energy. Predictions are used only for scheduling; final emissions use observed carbon.

Forecast replay eligibility is 1,699,114 tasks; 11,589,716 are ineligible (11,589,436 missing origin; 280 incomplete origin coverage). TRACE fallback decisions total 11,649,044: 253,870 missing-origin, 59,392 no-positive-risk-savings, and 3 incomplete-origin fallbacks. Three forecast-rescheduled decisions were recorded. Eligibility, fallback decisions, and reschedules have distinct meanings. Forecasts are historical replay without verified live issue-time availability, and uncertainty intervals are not established as formally calibrated.

## Archive classification

`submission/TRACE_REPRODUCIBILITY_ARCHIVE/` is **reference-based, not self-contained**. Compact reports, configuration, summaries, and metadata are copied under `evidence/`; every copy has a SHA-256 in the manifest. The manifest has `Included`, `External reference`, and `Excluded` statuses.

Large inputs/results are not duplicated. They remain at their existing repository-relative paths and are listed in the manifest with sizes and hashes where available. Examples include the 837,894,918-byte processed workload, 1,235,960,676-byte chronological workload, 920,371,200-byte checkpoint, 1,721,425,920-byte validation ID index, and 2.65-GB schedule ledgers. The raw carbon files and forecast are external references because redistribution terms are unknown. The original upstream acquisition/license record is excluded because it is not present. Review `ARCHIVE_README.md` and `ARCHIVE_MANIFEST.csv` before transferring the archive.

## Team information required

No names, institution, department, or supervisor were inferred. Fill the explicit placeholders in `docs/TRACE_FINAL_REPORT.md`, Slide 1 of `docs/TRACE_FINAL_PRESENTATION.md`, and the presenter field in `docs/TRACE_DEMO_SCRIPT.md`. The exact fields and locations are listed in `submission/TEAM_INFORMATION_TO_COMPLETE.md`.

## Runbook audit

The documented modules and flags were checked against their `--help` output. Validation, forecast evaluation, preflight, event-engine, and Phase 6 runner entry points exist. Examples use Windows CMD syntax. Validation and forecast evaluation use separate Phase 8 output directories. The full-run and resume commands are clearly marked as resource-intensive, explicit opt-ins; no simulation was launched. Forecast generation writes to a fixed output path and is documented as potentially overwriting the existing replay. The Phase 6 verification scripts have fixed targets and overwrite report outputs/reset the disk-backed ID index; the runbook now says not to rerun them in place. Test command uses the verified writable directories.

## Test and repository checks

Final test command:

```cmd
py -m pytest -q -o cache_dir=C:\TRACE_pytest_cache --basetemp=C:\TRACE_test_temp
```

Expected final result: 93 passed, one third-party `dateutil` deprecation warning. `git diff --check` passes with the existing README line-ending conversion warning.

The branch remains `feat/final-integration`. Existing worktree edits and untracked project files were preserved. No source algorithm changes were made. The original Phase 6 ledgers, checkpoint, evaluation, progress records, and independent reports remain in place. No full simulation was rerun; no commit, push, merge, or reset occurred.

## Remaining limitations and exact team actions

1. Add confirmed student/team names, institution/department, and supervisor if required in the report, presentation, and demo script.
2. Establish the original carbon-data acquisition source, endpoint/retrieval date, and license/redistribution terms. Decide whether the raw carbon data and derived forecast may be included in the submitted archive. Until confirmed, do not publicly redistribute them.
3. Supply or arrange authorized access to the external-reference files listed in the archive manifest if the evaluator needs to reproduce the full run; the archive itself is not self-contained.
4. Retain the stated scientific limitations: assumed 10 W/core energy, historical forecast replay, uncalibrated uncertainty evidence, relative workload/carbon timeline, short carbon series, sparse TRACE rescheduling, and a tiny common-set emissions difference that does not establish general superiority.

No unresolved ledger-integrity, checkpoint-offset, emissions-recalculation, or test failures were found. The remaining blockers are team metadata, data rights/provenance confirmation, and evaluator access to reference-only large artifacts.
