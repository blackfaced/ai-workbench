# 0006 - Make ExecutionSnapshot and RunLedger the Durable Control Authority

## Status

Accepted

## Context

ADR 0002 established the host Daemon as the durable owner of unattended Runs and described an approved Contract as fixed for execution. The implementation does not fully preserve those invariants.

Submission currently queues a mutable Contract filesystem path. Execution and restart recovery read that path again, together with project workflow and role-guidance files. The recorded hash covers only part of the resolved execution policy and does not pin every behavior-affecting input or the resolved base commit. A queued Run can therefore observe different inputs from those validated at submission.

Durable control state is also divided between two SQLite databases. One store owns queue status, the mutable Contract path, errors, and a copied report. Another owns Run and Todo checkpoints, Attempts, Evidence references, stop state, and recovery details. Status and report views can drift from the state that actually controls recovery, and admission cannot create the execution input, Run, and queue record atomically across the two authorities.

The workbench is intended to run unattended for long periods on a development machine. Recovery must not depend on a chat session, a mutable project file, a moving Git reference, or two stores agreeing after a crash.

## Decision

Introduce Admission as the only boundary that may turn an approved Contract into executable work.

Admission will:

- require a clean target repository for the first implementation;
- resolve the requested base reference to an exact commit;
- validate approval and authorize the complete project policy;
- resolve Contract content, role guidance, Harness selections and commands, publish policy, provider, model, and resource policy;
- retain exact source bytes for audit and produce a typed, versioned manifest for execution;
- exclude secret values while recording only required secret names or references;
- compute an immutable ExecutionSnapshot identity over every non-secret input that can alter Run behavior; and
- atomically create or reuse the ExecutionSnapshot, create a distinct Run, and enqueue that Run.

Preflight remains read-only and produces no durable ExecutionSnapshot or Run. Every submit creates a new Run even when an identical ExecutionSnapshot already exists. Explicit idempotency keys may prevent accidental duplicate submission; ExecutionSnapshot identity must not collapse intentional repeated Runs.

After Admission, the Daemon and GoalRunner consume only the stored ExecutionSnapshot manifest. They must not reread the Contract, project workflow, role guidance, Harness policy, publish policy, or moving Git reference through its original path. The source portion exists for audit; the resolved manifest is the execution authority. Old ExecutionSnapshots remain immutable and are read through version-compatible readers rather than rewritten in place.

Replace the existing durable stores in one coherent state-layer rewrite with one deep `RunLedger` module. Its interface is expressed as domain operations such as admission, Run claim, checkpoint recording, pause, resume, completion, and report projection. It does not expose generic CRUD or database-specific types.

The RunLedger will own:

- ExecutionSnapshots and their identities;
- Runs and their current state;
- queue entries and Leases;
- Todo state;
- Attempts, Checkpoints, Transitions, and stop records;
- Evidence references, while complete Evidence bytes remain in the existing content-addressed Evidence store; and
- the canonical data used to derive status and report Projections.

Persistence uses a hybrid model. ExecutionSnapshots are immutable. Runs, Todos, and Leases store current queryable state. Attempts, Checkpoints, Transitions, and Evidence references are append-only. Recovery reads current state and does not replay an event log. Status and reports are derived Projections, not independently persisted JSON authorities.

Queue ownership uses a time-bounded Lease with a generation-based fencing token. Every mutation made by an executing worker carries the current generation. An expired or superseded worker cannot write. SQLite transactions remain short and never enclose an Agent or Harness process.

The local implementation supports one Daemon process for one state directory, enforced by a process lock. That Daemon may run distinct Runs or dependency-ready Todos concurrently within resource policy. Lease and fencing semantics cover crash recovery and stale workers; they do not imply distributed scheduling. A future database implementation may support multiple Daemons without changing the RunLedger behavioral contract.

SQLite is the only implementation delivered now. Storage replacement remains an internal seam and will be validated with backend contract tests when a second implementation is actually required. No MySQL or PostgreSQL dependency, configuration, schema, or deployment path is added by this decision.

ExecutionSnapshots record the AI Workbench engine version, Admission schema version, and transition-policy version. A restarted Daemon resumes automatically only when the current engine explicitly supports those versions. Otherwise it preserves the Run and reports `incompatible_engine` rather than silently continuing with different semantics.

The existing state format will not be migrated. Setup detects incompatible legacy state and may delete it only through an explicit interactive confirmation or non-interactive reset option. The Daemon reports the incompatibility and exits; it never silently deletes state. Release notes and user documentation must identify this one-time breaking reset.

The `aiwb goal run` command remains as a foreground user experience but stops being an alternate execution path. It submits through the same Admission and Daemon control plane, follows status and output, and leaves the Run alive if the terminal disconnects.

The rewrite will be delivered in one Pull Request with reviewable internal commits. It replaces the complete durable state layer and removes both old stores and the second database before merge. It preserves the external CLI, MCP, AgentAdapter, Harness, prompt, strict test-first workflow, resource, Git worktree, Evidence, and Candidate-acceptance behavior except where this decision explicitly changes submission, foreground following, or state reset.

## Consequences

One immutable execution input and one durable state authority now govern every unattended Run. A changed project file, branch ref, role Skill, Harness policy, or restart cannot silently change a queued Run. Admission and enqueue become genuinely atomic, while CLI and MCP observe the same status and report semantics.

The RunLedger becomes a deep module with a small behavioral interface and high leverage. Its implementation absorbs parsing-adjacent persistence, queue coordination, current Run state, recovery, and report assembly without widening the external orchestration interface. The existing AgentAdapter remains the seam for provider execution, and the existing Evidence store remains the seam for complete artifact bytes.

The one-time rewrite carries more short-term implementation risk than an incremental compatibility layer. That risk is bounded by behavior-level contract tests, crash and fencing tests, complete existing regression coverage, an explicit breaking state reset, and one Pull Request that does not merge until the old authorities are removed.

This decision supersedes ADR 0002 only where ADR 0002 assumed that a Contract hash plus mutable project paths fixed execution, that CLI and MCP observed one existing SQLite state, or that direct `goal run` could be a separate synchronous path. ADR 0002's provider, Harness, worktree, recovery, permission, non-production, and interaction-adapter boundaries remain accepted.

This decision does not introduce a declarative role workflow engine. A code-owned Role Transition Policy remains a later bounded experiment after Admission and RunLedger are stable. The accepted strict Test Designer, RED gate, Implementer, Verifier, and Candidate acceptance flow remains unchanged.
