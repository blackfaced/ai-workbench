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

### CodexDriver executes real Attempts

`aiwb daemon serve` now starts with the production `CodexDriver` instead of
refusing to run. One admitted Run executes one Codex Attempt through
`codex exec --json` inside the admitted AIWB worktree, streaming bounded
Activity Events before Codex exits. The Driver validates the frozen Agent
Harness Profile and fails closed on unsupported sandbox permissions, reasoning
effort, capabilities, tools, paths, resource limits, native configuration,
trace coverage, or non-skill Harness Extensions. An admitted `tokens` resource
limit terminates owned execution with a typed `token budget exhausted` outcome.
Quota, authentication, timeout, transport, and invalid-output failures are
classified as typed terminal Attempt outcomes.

### RunLedger rejects illegal Run and Attempt transitions

The RunLedger now enforces a minimal explicit Run transition table at its
mutation authority: `queued`, `attempting`, `verifying`, the terminal
`candidate`/`failed`/`interrupted` states, and `retry` back to `queued` are the
only edges. Terminal Runs are immutable — a late `fail` or checkpoint clear
against a finished Run is rejected with no durable partial effect. An Attempt
can only start while its Run is `queued` or `attempting`, and starting the
first Attempt moves an unclaimed Run to `attempting`. Activity Events remain
rejected before Attempt start and after the terminal Attempt outcome.
