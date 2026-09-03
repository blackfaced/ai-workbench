# AGENTS.md

This repository is a personal AI development workbench knowledge base.

## Collaboration Rules

- Keep top-level organization by artifact type, not by life domain.
- Put agent skills and reusable instruction packs under `skills/`.
- Put MCP servers, plugins, CLIs, browser tools, and integrations under `tools/`.
- Put repeatable usage patterns and multi-step processes under `workflows/`.
- Put personal action items under `todo/`.
- Record repository governance and structure decisions under `decisions/`.
- Use `Domain:` metadata for fields like `coding`, `investing`, `research`, `learning`, and `ops`.
- Prefer one entry per file plus a directory `README.md` index.
- Do not create new top-level directories without adding or updating an ADR.
- Keep entries concise and practical: when to use, setup notes, evaluation status, and personal observations.
- Treat engineering skills as lightweight and opt-in; do not impose a heavyweight process framework by default.
- Keep each Agent Harness Attempt bounded. A Harness completion signal ends an Attempt; only approved Verification Harness Evidence accepts a Run.
- Before proposing changes, gather bounded evidence of relevant implementation, tests, call paths, and base behavior. Do not assume a reusable pattern is absent.
- Let the selected Agent Harness own planning, roles, subagents, tool use, review, and rework. AI Workbench must not reproduce those internals as a provider-neutral workflow.
- Freeze the owner's natural-language instructions and the complete Agent Harness Profile at Admission. Do not reread or self-modify them during a Run.
- Resolve, install, display, and lock explicitly named Harness Extensions during setup. Their invocation and internal ordering remain the Agent Harness's responsibility.
- Keep runtime learning immutable: it may inform a later Contract or Profile but cannot change the active ExecutionSnapshot.
- After Admission, execute only the immutable `ExecutionSnapshot` manifest. Do not reread a Contract, workflow, Verification Harness policy, Agent Harness Profile, branch ref, or other behavior-affecting input through its original path.
- Route every durable Run, queue, Attempt, Activity Event, Checkpoint, Lease, Transition, and Evidence-reference mutation through the `RunLedger`; do not create a second queue, status, or report authority.
- Keep RunTrace as append-only RunLedger-owned audit records with large payloads behind Evidence references. Extend the existing ExecutionManifest rather than adding a parallel resolved manifest or trace database.
- Keep status and report outputs as Projections over canonical ledger state, not independently persisted copies.
- Treat destructive state-format changes as explicit setup/reset operations. A Daemon must fail safely on an incompatible state schema and must never silently delete state.
- Keep the durable-state interface behavior-oriented and storage-neutral, while shipping only the SQLite implementation until another backend is required.

## Agent skills

### Issue tracker

Issues live in GitHub repository `blackfaced/ai-workbench`; external pull requests are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five configured canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository: use root `CONTEXT.md` and `decisions/`. See `docs/agents/domain.md`.
