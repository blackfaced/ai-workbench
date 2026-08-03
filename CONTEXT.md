# Unattended Agent Development

This context describes the language used to plan, execute, and verify long-running agent-assisted development without relying on a chat session remaining open.

## Language

**Goal**:
A durable development objective with an agreed requirement and acceptance boundary. A Goal can outlive conversations and have more than one Contract version or Run.
_Avoid_: Task, workflow, chat

**Contract**:
An approved, immutable version of a Goal's requested scope, acceptance tests, Todo graph, permissions, Harness selections, and run limits. A Contract is the owner's approved intent; it is not the executable authority after Admission.
_Avoid_: Plan, prompt, brief

**Admission**:
The atomic process that validates an approved Contract, resolves and authorizes every behavior-affecting input, pins the repository commit, and creates an ExecutionSnapshot and queued Run.
_Avoid_: Preflight, parsing, submit

**ExecutionSnapshot**:
The immutable, versioned execution authority produced by Admission. It retains the approved source for audit and a fully resolved manifest for execution; its identity covers every non-secret input that can change Run behavior.
_Avoid_: Contract path, envelope, mutable configuration

**Run**:
One resumable execution of one ExecutionSnapshot using a fixed agent provider. Repeated submissions of the same ExecutionSnapshot create distinct Runs.
_Avoid_: Session, job, workflow

**Lease**:
A time-bounded, fenced grant allowing one Daemon generation to mutate a Run. An expired or superseded Lease cannot write durable Run state.
_Avoid_: Lock, owner flag, running status

**Transition**:
An append-only record of one authorized Run or Todo state change. Current state is stored directly; recovery does not replay Transitions.
_Avoid_: Arbitrary update, event-sourcing event

**Projection**:
A derived status or report view assembled from the RunLedger's canonical state. A Projection is disposable and never a second state authority.
_Avoid_: Report snapshot, copied state

**Todo**:
A vertical, independently verifiable slice of a Contract. Todos form a dependency graph and each Todo owns its implementation worktree.
_Avoid_: Layer, phase, subtask

**Attempt**:
One bounded Agent effort on a Todo in a specific role. Repeated Attempts do not change the Todo's acceptance boundary.
_Avoid_: Retry, turn

**Checkpoint**:
A durable Run state from which execution can safely resume without trusting partially completed Agent work.
_Avoid_: Status, save point

**Evidence**:
An immutable observation supporting a Run decision, tied to the relevant commit, image digest, Harness profile, and environment identity.
_Avoid_: Log, output, claim

**Harness**:
The project-owned, repeatable mechanism that provisions a test target, seeds data, executes checks, collects Evidence, and cleans up resources.
_Avoid_: Test script, environment

**Candidate**:
The integrated branch and Evidence set that has satisfied its Contract but has not been merged into the project's target branch.
_Avoid_: Release, completed work
