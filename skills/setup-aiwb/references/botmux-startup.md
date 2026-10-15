# Botmux project-context startup

Use after the owner authorizes automatic setup for specified projects. This opt-in integration prepares the selected checkout before the native CLI starts, including worktrees created through Botmux's own picker or another Git entry. Botmux continues to own sessions, roles, input, model selection and transport.

## Verified runtime and installation

Botmux 3.40.0 local tmux + bash passes `-i -c SCRIPT _ CWD ENV... CLI ARGS...` through `launchShell`. Install a small executable named `bash` in an owner-managed stable release directory. It calls the pinned release's `botmux_context.py --registry <owner-registry> --shell /bin/bash -- "$@"`. The gate prepares CWD synchronously, then execs the original bash with every argument unchanged. Bind it through the existing per-bot `launchShell` setting; preserve the original setting and a guarded rollback record. The release installer includes the gate and its shared I/O helpers in its hash manifest.

Recheck installed-version source and actual argv before enabling. This contract is specific to local bash launches: strict-env/sandbox paths can bypass the shell, and remote, adopted, already-running, RPC-only or other-shell paths are not covered. Do not claim this gate protects them. `session.start` lifecycle notifications run asynchronously after startup; prompt-submit gates do not cover every startup path. Neither substitutes for pre-exec preparation.

Use Botmux's existing authenticated local configuration endpoint to set `launchShell` without switching CLI identity or restarting live workers. Verify both persisted and effective settings and preserve active session IDs/PIDs. Never log the shared IPC secret, request headers, environment assignments, CLI argv or raw native input. A direct bots.json edit alone does not prove the running daemon adopted a setting.

## Project-owned registry

Keep an owner-only version-1 JSON registry outside business source control. It contains:

- `installer`: stable `setup-aiwb-context` path and its SHA-256.
- `clients`: absolute native `codex` and `trae` executable paths. These remain the real clients, avoiding recursive startup checks.
- `projects`: keyed by canonical Git common-dir. Each entry declares canonical `repo`, `declaration` and `declaration_sha256`, rules `pin`, existing `workenv`, absolute `companions` with SHA-256, reviewed relative `source_files` with SHA-256 (null records expected absence), and `team_sha256` for root AGENTS.md.

Optional `native_companions` maps relative `.trae/` or `.codex/` artifact paths to pinned `{source, sha256, worktrees_only?}` entries. `worktrees_only: true` limits provisioning to additional checkouts while retaining the source checkout's own native metadata. These are copied only when absent; matching existing files are retained, conflicts and tracked/unexcluded paths block startup. Native config files themselves remain owned by the renderer. Use this for verified project-local client startup metadata. On TraeX 0.209.1, choosing “Do not ask again for selected data” creates `.trae/.coco-resources-migrated` with `skipped_by_user=true\n`; explicitly provision that project-local skip decision when legacy resources would otherwise prompt. Preserve team `.coco` content and global migration preferences. Verify the installed client behavior before registering this compatibility artifact.

Use the project's existing declaration and analysis record. Include referenced rules/observability documents in companions. Registration authorizes exact checkout trust provisioning when Botmux selects a real root of that registered Git repository; it never trusts a parent or matches repositories by remote URL/name. Keep private native paths in that Git common-dir's existing local excludes before registering. Existing explicit untrusted values, foreign native blocks, symlinks and source drift retain the renderer's refusal behavior.

A worktree may use a different commit only while all reviewed files and team guidance still match. A changed error adapter or observation helper requires the project's setup analysis to be refreshed; an unattended shell gate cannot perform that analysis. Shared source pointers are appropriate only when their registered main-checkout source has a stable lifetime. Missing/moved sources block startup.

## Runtime and verification

The gate serializes starts for one registered repo, validates pinned inputs, runs the renderer's apply and check with the selected explicit worktree, then inspects both native clients' no-model input from that exact cwd. Project instructions, rule pin and complete team guidance must be present in their expected roles. Any failure exits 78 with `AIWB_CONTEXT_STARTUP_BLOCKED`; the shell and business CLI are not executed. A sanitized refusal record is saved at `<registry-directory>/failures/<cwd-sha256>.json`, because a failed tmux pane may disappear before its stderr can be inspected. Unregistered repositories pass through without project/trust writes.

The selected checkout gets `.ai-workbench/project-context/botmux-startup.json`: source/target revisions, registry/declaration hashes, cwd, timestamp and sanitized loading checks. Renderer backups and ownership ledger remain in the registered source checkout. This receipt proves provisioning/loading, not model behavior or live telemetry collection.

Before declaring completion, create a fresh Git worktree without native configs and start it through the ordinary configured Botmux entry. Persist actual Botmux/native session IDs, cwd, startup receipt timestamp preceding native session creation, developer/team input and a pinned readable project-document pointer. Record any model-backed document-read probe separately: capacity queueing does not invalidate persisted startup-input evidence, but must never be reported as a successful model action. Exercise a source/foreign-config failure and prove no native session started. Repeat setup and compare native hashes; check an unrelated Git repository receives no private context. Close only owned probes, remove only clean owned worktrees, and restore only exact probe trust entries/ledger rows under ownership guards. Retain the setup source, backups and sanitized evidence.

Tests: `python3.11 tools/environment/tests/test_botmux_context.py`, the existing project-context suites, and `python3 tools/environment/tests/regression.py`.

Protocol source: [Botmux 3.40.0 tmux backend](https://github.com/deepcoldy/botmux/blob/v3.40.0/src/adapters/backend/tmux-backend.ts), [launch-shell configuration endpoint](https://github.com/deepcoldy/botmux/blob/v3.40.0/src/core/dashboard-ipc-server.ts). Source revision: `47d4d38dc47137be22244e43597ec06e4776a78a`.
