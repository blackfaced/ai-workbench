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
- Optimize for the Minimal Sufficient Change: completely satisfy the approved boundary, and do not implement adjacent improvements. Report them separately.
- Keep each Agent Attempt to one independently verifiable Change Slice. A completion signal ends an Attempt; only approved machine Evidence accepts a Todo or Run.
- Before proposing a Change Plan, gather bounded Existing Behavior Evidence. Do not assume a feature, test, or reusable pattern is absent.
- Keep Reviewers independent, read-only, and typed. They report findings to a Worker or Planner and never modify the reviewed Candidate.
- Keep Planner, Worker, and Reviewer as the only Agent roles. Express testing, implementation, execution, diagnosis, and rework as scoped Worker Assignments rather than new specialist roles.
- Keep shared behavior in one versioned Development Doctrine and role-specific differences in Role Profiles. Resolve and freeze both at Admission; do not reread or self-modify them during a Run.
- Let Workers request only Contract-approved Harness actions. Daemon-owned Harness execution and Evidence, not Work Reports, determine machine outcomes.
- Treat newly discovered boundary decisions, missing dependencies, and hard Change Budget violations as Replan Requests. Workers must not widen a Todo or Contract.
- Keep runtime learning immutable: record Adjacent or Guidance Findings instead of changing the active Run's guidance, Skills, Harness policy, or workflow.
- After Admission, execute only the immutable `ExecutionSnapshot` manifest. Do not reread a Contract, workflow, Harness policy, role guidance, branch ref, or other behavior-affecting input through its original path.
- Route every durable Run, Todo, queue, Attempt, Checkpoint, Lease, Transition, and Evidence-reference mutation through the `RunLedger`; do not create a second queue, status, or report authority.
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
