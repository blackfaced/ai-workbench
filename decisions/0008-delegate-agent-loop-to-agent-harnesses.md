# 0008 - Delegate the Agent Loop to Agent Harnesses

## Status

Accepted

## Context

AI Workbench currently models Test Designer, Implementer, Verifier, Planner, Worker, and Reviewer execution as its own durable orchestration workflow. Codex, Claude Code, and ACP-compatible coding harnesses already own agent loops, context, tools, planning, and subagents, so reproducing those details in AI Workbench creates a second orchestration model and obscures live execution.

## Decision

AI Workbench will be the durable control and acceptance layer, not another coding-agent loop. One Run owns an approved ExecutionSnapshot and worktree, starts one primary Agent Harness Attempt, and accepts the result only through project-owned Verification Harness Evidence. A bounded retry starts a fresh Attempt; AI Workbench does not persist Planner/Worker/Reviewer or Todo-DAG states.

Agent Harness integration will live behind one small `AgentHarnessDriver` seam. Codex and Claude may have native Drivers, while ACP provides the generic extension path. Models remain Driver configuration rather than integration adapters. Admission, approval, permissions, worktree ownership, RunLedger, Evidence, liveness policy, and Verification Harness execution remain AI Workbench responsibilities; the selected Agent Harness owns its internal planning, tools, roles, subagents, and context management.

AI Workbench freezes the complete harness-native profile rather than defining common Planner, Worker, or Reviewer fields. Setup must display the resolved Harness, primary and internal-role Models where the Harness exposes them, effort, permissions, and configuration summary. Admission hashes that exact profile, and a changed profile requires a new approval. A Driver passes and verifies the profile but does not interpret harness-internal role semantics; unsupported requested configuration fails closed instead of degrading silently.

AI Workbench passes the owner's approved natural-language development and assurance instructions, while the Agent Harness decides how to plan, delegate, review, and rework to satisfy them. AI Workbench will not introduce a portable requirement or workflow DSL. Setup resolves explicitly named Skills, MCP servers, plugins, hooks, and commands into the immutable Agent Harness Profile and verifies that they are installed and available. Invoking those extensions remains a Harness responsibility: AI Workbench projects invocation events when the Driver can observe them but does not create a cross-Harness invocation gate. The first implementation does not start a second AIWB-owned Review Attempt or persist a provider-neutral review/rework state machine. A Harness may use an internal read-only Reviewer or other subagents, but its completion remains insufficient for acceptance without Verification Harness Evidence.

Run recovery relies on AI Workbench's durable worktree, RunLedger state, Checkpoints, and Evidence rather than requiring a provider Session to resume. A Driver may expose a Session identifier for observation, but an interrupted Attempt is terminal and any retry starts a fresh Attempt under the same immutable execution authority.

Every Driver streams a small common set of bounded Activity Events while its Attempt is running: lifecycle start, Session identity, observable activity, usage when available, and terminal outcome. Harness-specific extension, tool, subagent, command, and file events are projected only when Trace Coverage declares them visible; unavailable internals remain explicitly opaque. RunLedger owns the timeline and live Projections, while large or sensitive provider payloads remain redacted, bounded Evidence references. AI Workbench does not collect chain of thought, infer completion percentages, or reconstruct provider-independent role state.

## Consequences

The existing AgentAdapter, role-transition workflow, and Todo-DAG execution path will be removed. They have no active compatibility consumer, so AI Workbench will not ship a legacy execution mode, feature flag, state migration, compatibility Router, or dual-write path. Existing ExecutionManifest, RunLedger, Evidence, and Verification Harness modules remain authoritative. This decision supersedes ADR 0002 and ADR 0006 only where they require AI Workbench to own provider-independent role or Todo orchestration.

Delivery starts with one Codex vertical cutover that removes the legacy execution path and is dogfooded before another Driver is added. Claude is the second native Driver and ACP is the generic third Driver. Each later Driver must satisfy the same existing interface rather than widening it to reproduce harness-specific orchestration.
