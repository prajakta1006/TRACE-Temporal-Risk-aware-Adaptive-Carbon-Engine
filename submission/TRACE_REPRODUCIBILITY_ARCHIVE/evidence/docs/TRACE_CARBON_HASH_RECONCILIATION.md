# TRACE Carbon Hash Reconciliation

## Finding

The two reported SHA-256 values hash different byte sequences. The difference is explained by hashing procedure; available evidence does not show that the IN-WE observations changed between preflight and the completed run. The raw-byte and normalized-timeline hashes are not interchangeable.

| Representation | SHA-256 | What was hashed | Recorded in |
|---|---|---|---|
| Raw file bytes | `d6b4eaf55d2118e5f8e4096971bb4aea75f6f87d8281f0cb9a9d672e5c468108` | Exact bytes of `data/raw/carbon/india_west_carbon_intensity.csv` (23,438 bytes in the inspected workspace). Standard SHA-256 over binary file contents. | `results/phase6/full_real_20261111_run1/phase6_run_configuration.json`; same value in current raw-file verification and forecast evaluation metadata. |
| Normalized timeline | `789c3264423c92b0c527b19633348ab653e21002cb2f04760070ce1c650b79f3` | UTF-8 CSV serialization, including header, of two columns: parsed UTC `timestamp` converted to string and numeric `carbon_intensity` converted to float, after zone filtering and chronological sort. Standard SHA-256 over those serialized bytes. | Initial and resume `phase6_preflight_report.json`; checkpoint `config_json.carbon_sha256`. |

## Procedure comparison

Both code paths use SHA-256. They do not hash the same input:

- `src/scheduler/preflight.py::_carbon_hash` hashes the normalized two-column DataFrame after `_carbon_frame` filters the requested zone, parses timestamps, converts intensity, and sorts the rows.
- `src/scheduler/event_engine.py` computes the same normalized signature for the checkpoint compatibility fingerprint. The completed checkpoint stores `789c3264…` and marks all 13,288,830 tasks complete.
- `src/evaluation/phase6_execution.py::run_full_execution` records SHA-256 of the raw carbon CSV bytes in `phase6_run_configuration.json`. Current raw bytes reproduce `d6b4eaf5…`.
- The engine consumes the parsed carbon frame produced from the configured raw file. Its checkpoint fingerprint pins the normalized timeline values used by the scheduler, while the wrapper configuration pins the raw file bytes at wrapper startup.

The raw and normalized procedures differ in input selection, serialization, and metadata treatment. The normalized hash omits non-scheduler metadata columns and represents only sorted timestamp/intensity values for the selected zone. Consequently different raw files could, in principle, produce the same normalized timeline if only ignored metadata or formatting changed; the hash values must not be compared as if they were two checksums of one representation.

## Timing and impact

The preflight JSON records the zone and normalized hash but does not record a carbon path or original command line. The project defaults and full-run configuration identify `data/raw/carbon/india_west_carbon_intensity.csv` as the intended file; exact historical preflight path selection cannot be independently proven from that JSON alone. The preflight normalized hash matches the completed checkpoint's normalized fingerprint and a fresh normalization of the current file. The run-configuration raw hash matches current raw bytes. The two preflight reports also agree with each other. No evidence establishes a file change between checks; their differing hashes follow directly from the code's distinct hash inputs.

The full simulation's carbon values are identified by its normalized checkpoint fingerprint and the raw-file digest recorded at wrapper startup. This resolves the apparent hash mismatch as a representation difference, subject to the preflight path-record limitation above, and does not by itself undermine the emissions calculations, which were separately recomputed from the current raw file and match the ledgers. The available evidence does not provide a historical raw-byte hash or explicit carbon path captured by preflight, so it cannot prove byte-for-byte identity of every metadata field or exact historical file selection at preflight. It verifies that the normalized carbon timeline used by the checkpoint matches current normalized values.

Remaining reproducibility limitation: the original provider retrieval event, exact endpoint, and license are not recorded. See `TRACE_CARBON_DATA_PROVENANCE.md`.
