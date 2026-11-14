# TRACE Checkpointing and Recovery

## Durable state

The event runner stores state in `checkpoint.sqlite3` in the output directory. SQLite uses WAL mode and `synchronous=FULL`. A checkpoint row records the SHA-256 of the ordered workload, absolute input and output paths, canonical simulation configuration, strategies, checkpoint interval, byte cursor after the last complete CSV record, last task ID, processed count, simulation clock, serialized strategy state, output byte offsets, elapsed time, peak RSS, and completion flag. The database's `seen` table is the disk-backed task identity index and shares the checkpoint transaction.

The serialized strategy state contains the event heap, active/running and committed task identities, CPU reservation calendar, counters, forecast state, and per-strategy cursors. Task decisions are deterministic from that state and the ordered input.

## Commit and recovery protocol

For each task, the engine inserts its identity into SQLite and writes one decision to each strategy ledger. At each configured checkpoint interval it flushes and fsyncs every ledger, records their byte offsets, then commits the identity rows and checkpoint together. The input cursor points to the byte immediately after a complete logical CSV record.

If a process stops before a checkpoint transaction commits, SQLite rolls back its identity inserts. On resume, the runner truncates each ledger to its last committed byte offset and replays from the saved input cursor. A crash after output fsync but before the SQLite commit therefore discards only the uncommitted output tail. The final checkpoint is marked complete only after summary and ledgers are durable. A completed run can be reopened without replay.

Resume rejects changed workload contents, input/output paths, carbon or forecast data, strategies, simulation parameters, task limit, or checkpoint interval. Use the same output directory and options. Choose a new output directory for a new run. The input hash is recomputed on resume, so startup includes a full sequential hash pass.

The CSV reader tracks logical records and supports quoted fields spanning physical lines. The task identity index is SQLite-backed, so duplicate detection does not require retaining all IDs in RAM. Recovery rechecks the stable task ID from each source row, and rejects input that is not chronologically ordered.

## Use

```powershell
py -m src.main --mode full --checkpoint-interval 10000
py -m src.main --mode full --checkpoint-interval 10000 --resume
```

Run `py -m src.scheduler.preflight --resume` against the same run options before resuming. Preflight validates compatibility without starting execution. A smaller checkpoint interval reduces replay and output-tail loss after interruption but increases fsync and SQLite overhead. The default is 10,000 tasks.

## Recovery verification

`tests/test_event_checkpoint.py` compares uninterrupted and resumed outputs for interruptions between decisions, after an output write, while tasks are running, and at an hour boundary. It compares per-task ledger bytes and stable completion/emissions metrics and checks changed-input/config rejection and output-tail truncation. The test suite also covers identity deduplication and scheduler determinism.

The checkpoint payload uses Python pickle for internal scheduler state. Keep checkpoints with the same TRACE code/runtime version; cross-version migration is not supported. Checkpoints are local files, not a portable interchange format. A storage device failure that corrupts both SQLite and ledgers is outside the recovery guarantee.
