# Release Notes

## Next release

### Breaking: explicit reset required for legacy Run state

The RunLedger durable-state format replaces the former two-database
`state.db`/`daemon.db` format. There is no migration. Existing users must run
`aiwb setup --repo /path/to/project --state-dir ~/.ai-workbench`, review the
listed Run state and managed workspaces, and confirm the one-time reset before
starting the Daemon.

Automation may opt in with `--reset-incompatible-state`. The Daemon never
performs this reset: it exits with `incompatible_state` and preserves legacy
state until setup receives explicit approval. An interrupted reset remains
recorded and can be retried safely.

Current `run-ledger.db` files now carry a stable schema-version marker. Daemon
startup validates the marker, complete schema, and SQLite integrity on an
isolated recovery copy. Normal crash WAL files remain valid recovery input;
corrupt, incomplete, and unsupported-version ledgers are refused without
modification. `--reset-incompatible-state` remains strictly a legacy-state
operation and cannot delete a current RunLedger.
