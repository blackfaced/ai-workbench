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

### Guided setup resolves the exact Agent Harness Profile

`aiwb setup` can now resolve one exact Agent Harness Profile against the live
Codex model catalog (`codex debug models`) without starting an Attempt. Name
the exact Model with `--harness-model`; reasoning effort defaults to the
catalog default and can be pinned with `--harness-effort`. The read-only
preview displays the resolved Profile, sandbox permission, token resource
limit, named Extensions with locked digests, Trace Coverage, catalog source and
digest, exposed internal-role Models, and one `profile_digest`. Unsupported
Models, efforts, or Extensions fail closed; hidden internal identifiers are
never selectable as the primary Model. An explicit `--apply` persists the
resolved Profile to the repository-local `.ai-workbench/agent-harness.yaml`;
apply is idempotent for an unchanged resolved Profile, and any Model, effort,
permission, Extension, or catalog drift requires a new explicit setup.
`CodexDriver` now accepts the catalog's `max` and `ultra` reasoning efforts.
