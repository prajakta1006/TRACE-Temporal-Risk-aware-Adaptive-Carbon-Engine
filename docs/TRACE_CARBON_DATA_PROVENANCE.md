# TRACE Carbon Data Provenance

## Principal Phase 6 carbon input

The evaluated carbon file is `data/raw/carbon/india_west_carbon_intensity.csv`. The table below separates properties present in the file from provenance claims not supported by a retrieval record. “Verified” means verified against the local file/code; it does not independently authenticate the upstream publisher.

| Attribute | Verified information | Evidence location | Status |
|---|---|---|---|
| Provider/source | Project provenance notes attribute this export to Electricity Maps. The CSV itself has no provider or download metadata; no original acquisition record was found. | `docs/data_provenance.md`; `src/evaluation/forecast_validation.py` labels provenance “Electricity Maps claimed by docs; original retrieval record absent.” | Partially verified |
| Retrieval URL/API endpoint | The project has a link to the provider's current carbon-intensity API documentation, but no saved request URL, endpoint, response, or download URL tied to this file. | `docs/data_provenance.md`; `results/phase6/full_real_20261111_run1/phase6_run_configuration.json` records local path/hash only. | Unknown |
| Retrieval date/API version | Not recorded in the file or run configuration. File `updatedAt`/`createdAt` columns describe row metadata and do not establish the download date. | Carbon CSV header/rows; run configuration. | Unknown |
| Zone | Every row has zone `IN-WE`. The zone label is verified; a separate source response establishing the provider's exact geographic boundary is not retained. | `data/raw/carbon/india_west_carbon_intensity.csv`; `_carbon_frame` filters zone in `src/scheduler/event_engine.py`. | Partially verified |
| Coverage and cadence | 216 continuous hourly UTC samples from 2026-09-22 00:00 through 2026-09-30 23:00; observed values range 469–731. | Carbon CSV; forecast dataset audit in `results/forecasting/forecast_evaluation_summary.json`; Phase 6 validation. | Verified |
| Intensity field/unit | Field is `carbonIntensity`. Project documentation and the current Electricity Maps API documentation describe carbon intensity in gCO2eq/kWh, but the CSV has no unit field and the original response is unavailable. | CSV schema; `docs/data_provenance.md`; `docs/TRACE_FORECASTING_VALIDATION.md`; provider API documentation linked there. | Partially verified |
| Emission factor type | All 216 rows show `lifecycle`. | Carbon CSV column `emissionFactorType`; dataset audit. | Verified |
| Flow tracing | All 216 rows have `flowTraced=True`. This verifies the local flag, not the provider's upstream processing. | Carbon CSV column `flowTraced`; local data audit. | Verified |
| Estimated flag | All 216 rows have `isEstimated=False`. This describes the dataset flag and does not make task-energy estimates measured. | Carbon CSV column `isEstimated`; 10 W/core energy model in `src/data/energy_model.py`. | Verified |
| Transformations | Scheduler filters to `IN-WE`, parses `datetime` as UTC, converts intensity to numeric, sorts chronologically, assigns row-index simulation hours, and evaluates task energy over hourly overlaps. It does not join the January files. | `src/scheduler/event_engine.py` (`_carbon_frame`, `_emissions`); `scripts/verify_phase6_emissions.py`; Phase 6 config. | Verified |
| License/redistribution | No license, terms, or permission to redistribute this exact export is present in the repository. | Search of repository provenance docs, dataset metadata, and run configuration; no license file or acquisition record found. | Requires team confirmation |
| January 2025 additional files | Two 30-minute files exist under `data/raw/carbon/additional/`, but provider, zone, units, and license are not established. They were not combined with the Phase 6 series. | Files under `data/raw/carbon/additional/`; `docs/TRACE_FORECASTING_VALIDATION.md`. | Unknown |

## Attribution and redistribution

The local documentation's Electricity Maps attribution is a project claim, not a verified acquisition chain. The provider's current [carbon intensity API documentation](https://app.electricitymaps.com/docs/reference/carbon-intensity) defines carbon intensity and unit conventions, but it does not prove that this particular CSV was obtained from that endpoint or under a particular license. The team must identify the original download/API transaction and review the terms that applied to it before redistributing raw or derived data. Until then, treat the carbon input and derived forecast file as externally sourced material with redistribution rights unverified; keep them out of a public archive or repository unless permission is established.

No extra carbon source was merged into the principal analysis.
