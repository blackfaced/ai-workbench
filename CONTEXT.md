# Unattended Agent Development

This context describes the language used to plan, execute, and verify long-running agent-assisted development without relying on a chat session remaining open.

## Language

**Goal**:
A durable development objective with an agreed requirement and acceptance boundary. A Goal can outlive conversations and have more than one Contract version or Run.
_Avoid_: Task, workflow, chat

**Contract**:
An approved, immutable version of a Goal's requested scope, acceptance tests, Todo graph, permissions, Harness selections, and run limits. A Contract is the owner's approved intent; it is not the executable authority after Admission.
_Avoid_: Plan, prompt, brief

**Minimal Sufficient Change**:
The smallest change that fully satisfies an approved Contract: complete inside the acceptance boundary and intentionally minimal outside it. Every included change must serve that boundary; adjacent improvements are separate work and never expand the current Run.
_Avoid_: Minimal patch, completeness, opportunistic improvement

**Decision Level**:
The authority class of an implementation choice: L1 mechanical, L2 local design within approved boundaries, or L3 boundary-changing. An Attempt may make only the levels authorized by its Contract; a newly discovered L3 choice requires replanning and approval.
_Avoid_: Difficulty, model reasoning level, confidence

**Change Budget**:
The approved hard boundaries and expected soft limits used to detect scope, decision, diff, and complexity drift. A Change Budget constrains how a Contract is satisfied; it never rewards fewer tests, compressed code, or incomplete behavior.
_Avoid_: Token budget, line-count target, implementation estimate

**Budget Deviation**:
A typed explanation that one Change Slice exceeded a soft Change Budget warning while remaining below its hard stop and fully traceable to the current Requirement and Test boundary. It records drift but grants no new scope, concept, or Decision Level.
_Avoid_: Budget override, exception, retroactive approval

**Admission**:
The atomic process that validates an approved Contract, resolves and authorizes every behavior-affecting input, pins the repository commit, and creates an ExecutionSnapshot and queued Run.
_Avoid_: Preflight, parsing, submit

**ExecutionSnapshot**:
The immutable, versioned execution authority produced by Admission. It retains the approved source for audit and a fully resolved manifest for execution; its identity covers every non-secret input that can change Run behavior.
_Avoid_: Contract path, envelope, mutable configuration

**ExecutionManifest**:
The typed, resolved portion of an ExecutionSnapshot that fixes provider and role profiles, capabilities, Harness actions, exact authorized commands, paths, limits, provenance, and trace policy for execution.
_Avoid_: ResolvedExecutionManifest, runtime profile, mutable composition

**Run**:
One resumable execution of one ExecutionSnapshot using a fixed agent provider. Repeated submissions of the same ExecutionSnapshot create distinct Runs.
_Avoid_: Session, job, workflow

**Superseded Run**:
A terminal Run replaced by an explicitly approved Contract Revision and new Admission. It cannot resume, and its Checkpoints transfer only through an approved carry-forward list followed by new Candidate verification.
_Avoid_: Resumed Run, migrated Run, failed Run

**Lease**:
A time-bounded, fenced grant allowing one Daemon generation to mutate a Run. An expired or superseded Lease cannot write durable Run state.
_Avoid_: Lock, owner flag, running status

**Transition**:
An append-only record of one authorized Run or Todo state change. Current state is stored directly; recovery does not replay Transitions.
_Avoid_: Arbitrary update, event-sourcing event

**RunTrace**:
The RunLedger-owned, append-only audit trajectory linking model-visible inputs, observable tool and subagent activity, Worker Assignments, Change Slices, Harness executions, Checkpoints, Evidence, and decisions. Large or sensitive bytes remain content-addressed Evidence, and trace reports are disposable Projections rather than another state authority.
_Avoid_: Trace database, chat transcript, report log

**Trace Coverage**:
The ExecutionManifest declaration of which Agent, tool, subagent, and Harness activity an Adapter can expose. Required AIWB-controlled activity must be reconstructable; unavailable provider-internal activity is explicitly opaque and may be rejected by a stricter Contract.
_Avoid_: Claimed full observability, chain-of-thought capture, best-effort logging

**Projection**:
A derived status or report view assembled from the RunLedger's canonical state. A Projection is disposable and never a second state authority.
_Avoid_: Report snapshot, copied state

**Todo**:
A vertical, independently verifiable slice of a Contract and the complete change boundary for its assigned Worker. A change valid elsewhere in the Contract is not valid in the current Todo unless the approved Todo graph assigns it there.
_Avoid_: Layer, phase, subtask

**Change Slice**:
One independently verifiable increment within a Todo, with a single purpose and explicit Requirement and Test mappings. A Todo may require several Change Slices; one Change Slice may touch several necessary files without combining unrelated intent.
_Avoid_: Turn, iteration, batch of changes

**Change Plan**:
A Worker's typed proposal for one Change Slice, identifying its single purpose, planned paths, Requirement and Test mappings, and expected concept delta. It is checked against the approved Todo and Change Budget but never grants new authority.
_Avoid_: Todo, Contract revision, implementation permission

**Existing Behavior Evidence**:
A bounded observation of relevant implementation, tests, call paths, and base behavior gathered before a Change Plan. It demonstrates why existing behavior is insufficient and which established patterns the Change Slice will reuse.
_Avoid_: Exhaustive codebase analysis, assumption, implementation guess

**Preservation Test**:
A test that protects relevant existing behavior while an approved change is made. It maps to Existing Behavior Evidence rather than inventing a new product Requirement.
_Avoid_: New requirement, speculative test, unrelated characterization

**Iteration Brief**:
The bounded, immutable context assembled for one fresh Agent Attempt from the current Todo, Change Plan, relevant requirements and tests, fixed guidance, Change Budget, recent Checkpoint, failure Evidence, and related code changes.
_Avoid_: Chat history, progress file, full Run transcript

**Planning Brief**:
The bounded, immutable context assembled for one clean Planner session from the Contract, Todo graph, relevant Work Reports, Evidence, Checkpoints, Review Results, Change Budget, and unresolved Findings.
_Avoid_: Worker transcript, chain of thought, complete Run history

**Role Profile**:
The Contract-frozen provider configuration, model and effort, output locale, permissions, paths, tools, input artifact, output schema, timeout, retry, and resource limits for Planner, Worker, or Reviewer sessions. Roles share one AgentAdapter seam and never own Run state.
_Avoid_: Long-lived Agent, provider adapter, runtime persona

**Development Doctrine**:
The versioned common behavioral principles shared by Planner, Worker, and Reviewer and resolved into an ExecutionSnapshot at Admission. Role Profiles add role-specific duties without copying or weakening the Doctrine, and runtime learning can only propose a later version.
_Avoid_: Prompt collection, mutable Skill, self-improving instructions

**Assurance Level**:
The Contract-approved intensity of review and Harness verification, such as lean, standard, or strict. Every level preserves the same scope, Admission, machine-acceptance, and non-production invariants.
_Avoid_: Interaction mode, permission level, completeness

**Interaction Mode**:
Whether a Run is observed interactively or continues unattended. It changes user interaction, not assurance, permissions, or acceptance meaning.
_Avoid_: Assurance level, headless quality mode, provider mode

**Adjacent Finding**:
An immutable observation about useful work outside the current Todo or Contract boundary. It may be reported with supporting Evidence, but it never expands the current Run or becomes implementation work without separate approval.
_Avoid_: Extra task, opportunistic fix, scope extension

**Guidance Finding**:
An Adjacent Finding proposing a change to project guidance, Skills, Harness policy, or workflow knowledge. It cannot alter the immutable behavior inputs of the current Run and affects execution only after separate approval and a new Admission.
_Avoid_: Self-modifying instruction, runtime learning

**Replan Request**:
An immutable Worker report that the current Todo cannot be completed correctly within its approved boundary because of a missing dependency, contradiction, unauthorized L3 decision, or hard Change Budget violation. It asks the Planner for a disposition but never expands the current Run.
_Avoid_: Scope change, dynamic Todo, implementation exception

**Contract Revision**:
An unapproved successor proposal produced by the Planner from a Replan Request. It may revise Todos, dependencies, acceptance boundaries, or Change Budgets, but becomes executable only through explicit approval and a new Admission.
_Avoid_: Live Contract edit, Run mutation, automatic replan

**Planning Disposition**:
The Planner's reasoned classification of a Replan Request, including whether the affected boundary is a Todo dependency-closed subgraph or the whole Run. The Daemon validates the dependency closure and defaults to whole-Run pause when the disposition cannot establish local impact.
_Avoid_: Worker decision, automatic scope expansion, scheduler guess

**Worker Assignment**:
A Planner-selected, Todo-bounded instruction for one Worker session, such as test authoring, implementation, test execution, diagnosis, or rework. Assignment type changes permissions and expected output without creating a new Agent role or expanding the Contract.
_Avoid_: Specialist Agent, dynamic Todo, prompt-only role

**Work Report**:
A typed Worker claim describing completed or analyzed work, Requirement and Test mappings, changed code, requested Harness actions, Evidence references, Findings, and a suggested next Assignment. It informs the Planner but never substitutes for machine Evidence or authorizes a transition.
_Avoid_: Test Evidence, completion signal, mutable progress file

**Attempt**:
One bounded Agent effort on a Todo in a specific role. An Agent completion signal ends the Attempt but does not accept a Todo; repeated Attempts never change the acceptance boundary.
_Avoid_: Retry, turn

**Checkpoint**:
A durable Run state from which execution can safely resume without trusting partially completed Agent work.
_Avoid_: Status, save point

**Evidence**:
An immutable observation supporting a Run decision, tied to the relevant commit, image digest, Harness profile, and environment identity.
_Avoid_: Log, output, claim

**Review Result**:
A typed, read-only assessment of a Todo or Candidate whose findings cite the reviewed change and an approved Requirement, Change Budget, or rule. Only Contract-authorized categories and severities may block; preference and adjacent improvement findings remain advisory.
_Avoid_: Reviewer prose, acceptance Evidence, reviewer patch

**Review Policy**:
The Planner-proposed and Contract-approved rules that select Candidate or Todo review, deterministic risk triggers, blocking finding classes and severities, and bounded rework. Runtime roles cannot widen or weaken it.
_Avoid_: Reviewer preference, runtime review choice, universal review step

**Failure Quarantine**:
A Contract-authorized, Run-local exclusion of a test failure proven unchanged from the pinned base commit. It preserves the original test and command, records comparative Evidence and an Adjacent Finding, and never hides a new, worsened, or acceptance-critical failure.
_Avoid_: Disabled test, skipped test, ignored failure

**Harness**:
The project-owned, repeatable mechanism that provisions a test target, seeds data, executes checks, collects Evidence, and cleans up resources.
_Avoid_: Test script, environment

**Candidate**:
The integrated branch and Evidence set that has satisfied its Contract but has not been merged into the project's target branch.
_Avoid_: Release, completed work
