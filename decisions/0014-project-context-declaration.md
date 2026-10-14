# 0014 — Maintained, project-owned context renderer and pinned local entry

- Status: Candidate; extends accepted ADR 0013, not merged.
- Domain: ops
- Starting baseline: `b3f60d55bdf9f9ead54e8d91b3bf6852f0d26760`.
- Recovery provenance: previously untracked renderer, schema, tests and draft ADR from the retained cleanup archive; archive and original files remain unchanged.

## Decision

`project_context.py` is a configuration tool, not a new agent runtime. It consumes project-owned instructions, an explicitly selected profile body, or a SHA-256-pinned local rule source. Tracker kind and work-item pattern are project input. AIWB contains no built-in business-rule text.

New input uses profile `project`. Historical `none`, `owned-full`, `legacy-only`, native config paths, marker IDs and v2 ledger components remain supported. An existing provenance-proven legacy block can be checked/retained without re-emitting hard-coded text. New provisioning or policy updates require a declaration (`--declaration`, `AIWB_PROJECT_DECLARATION`, or project `.aiwb/project-context.json`). Absence is still the `none` output. Existing callers are not silently switched.

## Authority and ownership

- Trust writes require explicit runtime `--manage-trust`; a non-none profile or `trust: true` declaration grants no permission. Only named checkout realpaths are in scope. Existing untrusted values block all target writes.
- Project files are separate from team `AGENTS.md`. Unknown declaration keys, unsupported native paths, malformed TOML, unowned/edited managed blocks and tracked private-config targets are refused, not silently ignored.
- No global instruction injection, automatic hook, Botmux role edit, model-backed probe or active-session interruption is included.

## Write and restore safety

TOML parser is mandatory (Python 3.11+ `tomllib`, or explicit `tomli`). Apply/check share validation. Unique same-directory temporary files, fsync, per-resource POSIX locks, fresh plans and pre-replace digest comparison protect cooperating writers and detected external edits. Ledgers and manifests are atomically written. System checkout aliases are resolved to realpaths; target symlinks and foreign-owned/non-writable files are refused.

This is not a filesystem transaction across every native file and ledger. Cooperative locking cannot eliminate the last digest-check/rename race with an editor that does not cooperate. Mid-run I/O failure can leave an applied prefix with backups; report it and reconcile before retry. Do not claim universal concurrency/crash safety.

Restore validates component identity, target/checkout relation or ledger provenance, marker identity, backup digest and current block/table state. New trust snapshots restore only their named project table, preserving other projects. Legacy trust snapshots require the old whole-file guard; they do not authorize guessing a narrower restoration. Force cannot bypass apply ownership refusal.

## Stable installation

`install_project_context.py` copies the renderer, companion `env.py`, its support modules and installer into an immutable named release, records every payload digest and source identity, and writes an ownership-guarded stable launcher. The launcher pins the release manifest and verifies payload hashes before dispatch. No launcher imports a moving worktree or main path.

Install/check/rollback are explicit. Upgrade selects a new version; old releases remain. Installation does not apply context or trust to business repositories. Runtime installation and source merge/publication are different operations. Candidate content must retain its dirty/source status honestly until committed.

## Verification gates

- Legacy behavior characterization with rule text moved to project fixtures, assertions retained.
- New tests: declaration source/validation, default-off trust, explicit untrusted, foreign edits, parser absence, real Git worktrees, same-repo and cross-repo trust concurrency, guarded restore, immutable install/upgrade/rollback and edited payload/launcher refusal.
- Maintained environment regression remains required.
- Real Codex/Trae prompt-input checks use isolated HOME, actual checkout cwd, harmless team/private markers and unrelated/missing-config negative controls. No paid prompt or group message.
- Separate local candidate installation from three-host operating acceptance and automatic worktree hook coverage; unrun paths stay unverified.
