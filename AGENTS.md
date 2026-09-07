# AGENTS.md

This repository maintains personal development environments. The primary entry point is `tools/environment/bootstrap.sh`.

## Collaboration Rules

- Keep top-level organization by artifact type, not by life domain.
- Put agent skills and reusable instruction packs under `skills/`.
- Put MCP servers, plugins, CLIs, browser tools, and integrations under `tools/`.
- Put repeatable usage patterns and multi-step processes under `workflows/`.
- Track active work in the issue tracker; `todo/` contains historical evaluation notes.
- Record repository governance and structure decisions under `decisions/`.
- Use `Domain:` metadata for fields like `coding`, `investing`, `research`, `learning`, and `ops`.
- Prefer one entry per file plus a directory `README.md` index.
- Do not create new top-level directories without adding or updating an ADR.
- Keep entries concise and practical: when to use, setup notes, evaluation status, and personal observations.
- Treat engineering skills as lightweight and opt-in; do not impose a heavyweight process framework by default.
- Before proposing changes, gather bounded evidence of relevant implementation, tests, call paths, and base behavior. Do not assume a reusable pattern is absent.
- Let the selected client own planning, subagents, tool use, review, and rework; environment tooling configures capabilities without reproducing the client agent loop.

## Environment changes

- Default to read-only planning. Keep plan, apply, and check on the same component logic.
- Prove ownership before overwriting or removing managed files; preserve user edits and unrelated configuration. Explicit force must still retain a recoverable backup.
- Keep restore guarded and configuration-block aware. Do not promise package downgrade or restoration of external installer side effects.
- Register installation channels only after verification; missing channels must remain visible failures.
- Preserve one source of truth for Skills and external rules. Client discovery failures must fail checks, never pass as an empty inventory.
- Validate changes with `python3 tools/environment/tests/regression.py`. Keep tests isolated from real machine configuration.
- Report maintenance, fresh installation, and inaccessible-machine coverage separately.

## Agent skills

### Issue tracker

Issues live in GitHub repository `blackfaced/ai-workbench`; external pull requests are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five configured canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use root `CONTEXT.md` for environment terminology and `decisions/` for scope decisions. See `docs/agents/domain.md`.
