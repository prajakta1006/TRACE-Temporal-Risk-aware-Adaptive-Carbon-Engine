# TRACE Reproducibility Archive

## Completeness: reference-based, not self-contained

This archive contains copied documentation, configuration, summaries, and validation reports under `evidence/`. It does **not** include the workload datasets, carbon datasets, full-scale schedule ledgers, forecast source file, checkpoints, or disk-backed validation indexes. Those files are listed as `External reference` in `ARCHIVE_MANIFEST.csv` with their existing repository-relative locations, sizes, hashes where available, and licensing/storage notes. The archive cannot reproduce the full run without access to those files.

No original source data or Phase 6 outputs were moved, changed, or deleted. The archive avoids duplicating multi-gigabyte artifacts. The C: volume had 24,761,110,528 bytes free (about 24.76 GB or 23.05 GiB) before archive creation; only compact evidence files are copied.

## Contents

- `evidence/README.md`, requirements, and relevant project documentation.
- Phase 6 run configuration, engine/evaluation summaries, completion/progress logs, preflight records, and independent reconciliation reports.
- Forecast and workload validation summaries and compact metric outputs.
- `ARCHIVE_MANIFEST.csv`, which records source or archive-relative paths, sizes, SHA-256, inclusion status, and notes.

Copied machine-readable text artifacts have workstation-root path strings normalized to `<PROJECT_ROOT>` where present. The original local files remain untouched; the manifest notes transformed copies.

## Important restrictions and limitations

- Carbon source license/redistribution rights are not established. Raw carbon inputs and derived forecasts are referenced but not copied.
- Original workload licensing/redistribution status is not established; workload files are referenced but not copied.
- Full-scale ledgers, checkpoint, and validation databases remain in their existing local run directories; hashes are recorded in the manifest where available.
- `results/forecasting/forecast_evaluation_summary.json` is copied as an historical Phase 3/forecast artifact and contains the stale phrase “full simulation not run.” It has not been edited; Phase 6 execution records supersede that historical status.
- The final checkpoint/run configuration hashes use different carbon representations; consult `evidence/docs/TRACE_CARBON_HASH_RECONCILIATION.md`.

Before redistribution, the team must confirm source licenses and obtain the referenced input files through an authorized channel. Do not describe this archive as complete until those files are lawfully included or formally waived by the evaluator.
