# Unattended Agent Development

This context describes the language used to plan, execute, and verify long-running agent-assisted development without relying on a chat session remaining open.

## Language

**Goal**:
A durable development objective with an agreed requirement and acceptance boundary. A Goal can outlive conversations and have more than one Contract version or Run.
_Avoid_: Task, workflow, chat

**Contract**:
An approved, immutable version of a Goal's requested scope, acceptance tests, natural-language instructions, permissions, Harness selections, and run limits. A Contract is the owner's approved intent; it is not the executable authority after Admission.
_Avoid_: Plan, prompt, brief

**Admission**:
The atomic process that validates an approved Contract, resolves and authorizes every behavior-affecting input, pins the repository commit, and creates an ExecutionSnapshot and queued Run.
_Avoid_: Preflight, parsing, submit

**ExecutionSnapshot**:
The immutable, versioned execution authority produced by Admission. It retains the approved source for audit and a fully resolved manifest for execution; its identity covers every non-secret input that can change Run behavior.
_Avoid_: Contract path, envelope, mutable configuration

**ExecutionManifest**:
The typed, resolved portion of an ExecutionSnapshot that fixes the Agent Harness, Model, capabilities, Verification Harness actions, exact authorized commands, paths, limits, provenance, and trace policy for execution.
_Avoid_: ResolvedExecutionManifest, runtime profile, mutable composition

**Run**:
One resumable control and acceptance lifecycle for an ExecutionSnapshot and its worktree. A Run starts one primary Agent Harness Attempt; a bounded retry starts a fresh Attempt, and recovery never depends on resuming a harness Session.
_Avoid_: Session, job, workflow

**Agent Harness**:
A coding-agent runtime that owns its agent loop, context, tools, planning, and any internal roles or subagents. AI Workbench selects and constrains an Agent Harness but does not reproduce its internal orchestration.
_Avoid_: Provider, Model, Agent role, Verification Harness

**Agent Harness Driver**:
The AI Workbench adapter that starts one Attempt in an Agent Harness and normalizes observable events and its terminal outcome. Driver selection is independent of Model selection.
_Avoid_: AgentAdapter, provider adapter, model adapter

**Model**:
The language-model selection interpreted by an Agent Harness for an Attempt. A Model is configuration carried through a Driver, not an AI Workbench integration seam.
_Avoid_: Provider, Agent Harness, Driver

**Lease**:
A time-bounded, fenced grant allowing one Daemon generation to mutate a Run. An expired or superseded Lease cannot write durable Run state.
_Avoid_: Lock, owner flag, running status

**Transition**:
An append-only record of one authorized Run or Attempt state change. Current state is stored directly; recovery does not replay Transitions.
_Avoid_: Arbitrary update, event-sourcing event

**RunTrace**:
The RunLedger-owned, append-only audit trajectory linking model-visible inputs, observable Agent Harness activity, Attempts, Verification Harness executions, Checkpoints, Evidence, and decisions. Large or sensitive bytes remain content-addressed Evidence, and trace reports are disposable Projections rather than another state authority.
_Avoid_: Trace database, chat transcript, report log

**Trace Coverage**:
The ExecutionManifest declaration of which Agent Harness activity its Driver can expose. Required AIWB-controlled activity must be reconstructable; unavailable harness-internal activity is explicitly opaque and may be rejected by a stricter Contract.
_Avoid_: Claimed full observability, chain-of-thought capture, best-effort logging

**Activity Event**:
A bounded, structured observation emitted while an Attempt is running, such as lifecycle, visible extension or tool activity, usage, or terminal outcome. Activity Events update live RunTrace Projections without claiming progress or reconstructing opaque Harness internals.
_Avoid_: Complete transcript, progress percentage, chain of thought

**Projection**:
A derived status or report view assembled from the RunLedger's canonical state. A Projection is disposable and never a second state authority.
_Avoid_: Report snapshot, copied state

**Agent Harness Profile**:
The Contract-frozen Driver, Model, effort, permissions, paths, tools, input artifact, output schema, timeout, retry, resource limits, and harness-native configuration for an Attempt. Setup resolves and displays the effective profile, while AI Workbench hashes it without interpreting harness-internal roles.
_Avoid_: Role Profile, provider configuration, mutable user settings

**Harness Extension**:
A Skill, MCP server, plugin, hook, or native command made available to an Agent Harness through its resolved Profile. AI Workbench locks its identity and installation without interpreting the workflow it enables.
_Avoid_: Harness Requirement, Agent Harness Driver, implicit ambient tool

**Development Doctrine**:
The versioned behavioral principles supplied to the selected Agent Harness and resolved into an ExecutionSnapshot at Admission. Runtime learning can only propose a later Doctrine version.
_Avoid_: Prompt collection, mutable Skill, self-improving instructions

**Assurance Level**:
The Contract-approved intensity of review and Verification Harness execution, such as lean, standard, or strict. Every level preserves the same scope, Admission, machine-acceptance, and non-production invariants.
_Avoid_: Interaction mode, permission level, completeness

**Interaction Mode**:
Whether a Run is observed interactively or continues unattended. It changes user interaction, not assurance, permissions, or acceptance meaning.
_Avoid_: Assurance level, headless quality mode, provider mode

**Attempt**:
One bounded execution of an Agent Harness against a Run's worktree. A terminal or interrupted harness outcome ends the Attempt but does not accept the Run; recovery starts a fresh Attempt from durable AI Workbench state, and only approved machine Evidence can accept the Run.
_Avoid_: Retry, turn

**Checkpoint**:
A durable Run state from which execution can safely resume without trusting partially completed Agent work.
_Avoid_: Status, save point

**Evidence**:
An immutable observation supporting a Run decision, tied to the relevant commit, image digest, Verification Harness profile, and environment identity.
_Avoid_: Log, output, claim

**Verification Harness**:
The project-owned, repeatable mechanism that provisions a test target, seeds data, executes checks, collects Evidence, and cleans up resources.
_Avoid_: Agent Harness, test script, environment

**Candidate**:
The worktree commit and Evidence set that has satisfied its Contract but has not been merged into the project's target branch.
_Avoid_: Release, completed work
