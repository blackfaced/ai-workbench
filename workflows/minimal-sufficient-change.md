# Minimal Sufficient Change

Use this workflow whenever AI Workbench advises, plans, or executes a code change. Advice and planning recommend it; an admitted Run enforces it.

## Principle

> Do not optimize for completeness.
>
> Optimize for the smallest change that fully satisfies the ticket.
>
> If you notice adjacent improvements, report them separately. Do not implement them.

This means **complete inside the approved boundary and intentionally minimal outside it**. It never permits a partial implementation, reduced test coverage, compressed code, or a placeholder merely to make the diff smaller.

## Controlled Ralph loop

AI Workbench adopts Ralph's short-context, one-item, fast-feedback discipline without giving the Agent authority to expand the backlog or declare acceptance.

1. The Daemon selects one dependency-ready, approved Todo.
2. A fresh Worker session gathers bounded Existing Behavior Evidence instead of assuming work is absent.
3. The read-only Worker proposes one typed Change Plan within that Todo.
4. Deterministic preflight checks the Change Plan against the Todo and Change Budget.
5. After preflight, the Daemon resumes that Worker session with only the current Change Slice's write authority.
6. The smallest relevant machine test checks the Change Slice.
7. The complete Todo gate checks the Todo before it can be accepted.
8. Contract and Harness gates check the integrated Candidate.
9. Agent completion signals end Attempts; machine Evidence accepts work.

The durable cross-iteration truth is the Contract, ExecutionSnapshot, RunLedger, Git checkpoints, and Evidence. Do not introduce a mutable `progress.txt` as another authority or inherit an entire chat transcript into a new implementation Attempt.

Output-format correction may resume the same session without tool authority. The first implementation failure in a Change Slice may receive one bounded repair in that session. Repeating the same failure signature starts one clean diagnostic Attempt; an unresolved result becomes a Replan Request or terminal failure rather than an open-ended loop.

## Scope discipline

A change may belong to the Contract but still be illegal in the current Todo. Shared foundations must be assigned to an explicit Todo and represented through dependencies before Admission.

If an Agent finds useful work outside the current boundary, it records an Adjacent Finding. If it learns that guidance, Skills, Harness policy, or workflow knowledge should change, it records a Guidance Finding. Neither changes the active Run.

Tests for new behavior map to approved Requirements. A Preservation Test may protect relevant existing behavior only when it maps to Existing Behavior Evidence; it cannot create a new product behavior under the name of characterization.

A Worker records a Replan Request only when correct completion is impossible because of a missing dependency, contradictory requirement, unauthorized L3 boundary decision, or hard Change Budget violation. The Planner may draft a Contract Revision and classify the affected dependency-closed subgraph, but cannot approve it or mutate the active ExecutionSnapshot.

## Decision and change boundaries

- L1 mechanical decisions create no new behavior or boundary.
- L2 local design decisions stay inside existing approved module and architecture boundaries.
- L3 decisions change a public API, persistence schema, dependency, runtime, security permission, Harness, or acceptance meaning.

The Contract authorizes the maximum Decision Level. A newly discovered L3 choice requires replanning and approval.

Change Budgets distinguish hard boundaries from soft drift signals. Forbidden paths, dependencies, permissions, production access, and unapproved public boundaries stop work. Expected paths, changed-file counts, and line estimates may trigger explanation and traceability review, but they are never optimization targets.

A soft warning may continue through a typed Budget Deviation only while every additional change maps to the current Requirement and Test and remains below the hard stop. The deviation cannot authorize a new concept or Decision Level. Reaching the stop or failing traceability requires replanning.

## Pre-existing failures

Do not repair an unrelated pre-existing failure inside the current Todo. A Contract may pre-authorize a Run-local Failure Quarantine when the same failure is reproduced on the pinned base, remains unchanged on the Candidate, is not acceptance-critical, and introduces no new failure. Keep the original test and approved command unchanged, attach comparative Evidence, record an Adjacent Finding, and report the Candidate distinctly from a completely green result.

One flaky result is not proof of a pre-existing failure. Automatic quarantine requires either a project Harness entry with stable identity and expiry or a Contract-approved repeated comparison rule. Inconclusive evidence remains inconclusive and cannot be presented as a historical failure.

## Replanning and supersession

The Planner receives the typed Replan Request and decides whether it affects a dependency-closed Todo subgraph or the whole Run. The Daemon validates dependency closure; if local impact is not established, it pauses the whole Run. Independent work may continue only under a valid local Planning Disposition, and Candidate acceptance waits for resolution.

The Planner may automatically produce an unapproved Contract Revision and a human-readable diff. Approval creates a new Admission and Run. The original Run becomes `superseded`, points to its successor, and cannot resume. Prior verified work transfers only through an explicitly approved carry-forward list and is rechecked by the new Candidate gates.

## Review feedback

Reviewers use clean, read-only sessions and emit typed Review Results. They never repair the Candidate. A blocking finding must cite a concrete diff or symbol and a Contract-authorized Requirement, Change Budget, security rule, category, and severity. Style preference and adjacent improvement remain advisory.

An authorized blocking finding returns a bounded local correction to a new Worker Attempt or a boundary problem to the Planner. One rework and rereview cycle is allowed. A repeated finding or a new blocking finding after that cycle stops as `failed_review` or requests replanning. Every correction reruns the relevant machine regression gates.

The Planner proposes a Review Policy for Contract approval. It chooses Candidate review, risk-based Todo review, deterministic triggers such as Budget Deviation, Failure Quarantine, carry-forward, conflict repair, or security-sensitive work, authorized blocking classes, and cycle limits. Admission freezes the policy; runtime roles cannot change review granularity.

## Test backpressure

Map approved tests to the cheapest sufficient stage:

- Change Slice: static analysis and the smallest relevant unit tests;
- Todo: local integration using disposable dependencies such as containers or in-memory databases;
- Candidate: cross-Todo integration, image, browser, and end-to-end Harnesses;
- non-production Kubernetes: only when explicitly selected by the Contract for Candidate or delivery-preparation verification;
- production: never an AI Workbench Harness target.

Planner choices are limited to capabilities discovered by Harness Setup and approved before Admission. A runtime role cannot add a new environment or weaken a selected stage.

Planner, Worker, and Reviewer are the only Agent roles. Test authoring, product implementation, test execution, diagnosis, and rework are Worker Assignment types with separate clean sessions, allowed paths, tools, and typed outputs. A test-authoring Assignment may modify only approved test paths; an implementation Assignment cannot weaken the accepted RED test.

A Worker invokes only Contract-approved Harness actions through the controlled Harness seam. The Daemon owns the command, environment, timeout, cleanup, raw output, commit or digest binding, and durable Evidence. The Worker interprets that Evidence in a typed Work Report but cannot report a machine pass by assertion.

Every failed Harness result returns to planning. A Work Report may propose a likely attribution and next Assignment. A deterministic Planner policy handles a unique, pre-approved local action without a model call; ambiguous, repeated, cross-Todo, Harness, or potentially out-of-boundary failures invoke a clean Planner Agent. The resulting Planning Disposition selects another Worker Assignment, bounded Harness retry, Replan Request, or stop. Workers never reassign themselves.

Each Work Report records the Assignment outcome, Requirement and Test mappings, commit, paths or symbols, requested Harness action, Evidence references, Findings, and suggested next Assignment. It is a claim and a feedback artifact, not acceptance Evidence.

## Traceability

RunTrace records one reconstructable audit trajectory inside the canonical RunLedger. It links stable identities rather than persisting line numbers:

```text
Requirement ID
  -> Test ID
  -> Worker Assignment ID
  -> Change Slice ID
  -> commit + path + symbol
  -> Harness Evidence ID
  -> Review Finding ID
```

EvidenceStore retains content-addressed prompt, tool, Harness, and report payloads; RunTrace retains ordered facts and references; reports remain projections. Extend the existing ExecutionManifest with capability/profile identity, exact argv, adapter versions, trace policy, and Trace Coverage. Do not add a `ResolvedExecutionManifest`, trace database, or another recovery authority.

AIWB-controlled model inputs, Harness actions, and tool requests must be reconstructable. Provider-internal events are recorded when exposed and explicitly marked opaque otherwise. A Contract that requires complete trace coverage rejects an Adapter that cannot provide it; no mode persists unrestricted chain-of-thought.

## Roles, assurance, and cost

Planner, Worker, and Reviewer are Contract-frozen Role Profiles over one AgentAdapter seam, not long-lived processes or handoff authorities. A clean Planner session receives a bounded Planning Brief rather than Worker transcripts or hidden reasoning. The Run provider remains fixed with no fallback; role models and reasoning effort inherit one default unless the Contract explicitly freezes different values. Runtime failure or quota never changes them.

Keep assurance, interaction, and diagnostics orthogonal:

- lean assurance uses machine gates and risk-triggered review;
- standard assurance includes Candidate review;
- strict assurance adds high-risk Todo review and stronger approved Harness coverage;
- interactive and unattended modes change observation, not quality or authority;
- browser capture, trace detail, and extra logging are diagnostic capabilities, not assurance modes.

Every level preserves Minimal Sufficient Change, approval, Admission, machine acceptance, path and production boundaries.

Planner, Worker, and Reviewer share one versioned Development Doctrine containing the invariant principles in this document. Role Profiles contain only role-specific duties and controls. Admission resolves and freezes the complete Doctrine and Role Profile text; a runtime Skill reference or later file edit never changes an active Run.

Project setup should review and persist defaults for Chinese human output, assurance, Role Profiles, provider and optional per-role model/effort, Harness capabilities and test levels, Failure Quarantine, Decision Levels, Change Budgets, and required Trace Coverage. Ordinary unattended Runs consume these reviewed defaults rather than asking the user overnight.

`/ask` applies the Doctrine as non-authoritative advice: it proposes the Minimal Sufficient Change, acceptance boundary, Todo or Change Slice shape, existing capabilities to reuse, unresolved L3 decisions, separately listed adjacent improvements, and an assurance/Harness recommendation. It neither approves a Contract nor starts work.

The default assurance level is standard: machine gates at slice and Todo boundaries plus one independent Candidate review. Lean is an explicit recommendation for mechanical work; strict is an explicit recommendation for security, persistence, concurrency, and delivery boundaries. The approved Contract freezes the selection.

Guidance Findings never self-modify the Doctrine. A separate knowledge-refresh action groups repeated Findings, upstream Skill changes, and Run Evidence into a proposed doctrine diff. Owner approval increments the Doctrine version and affects only later Admissions.

## Report projection

Keep the final report compact and layered:

1. Machine Outcome: Harness results and commit, image, environment, and Evidence identities;
2. Scope and Traceability Outcome: Change Budget, mappings, and Budget Deviations;
3. Review Outcome: blocking and advisory findings;
4. Exceptions: Failure Quarantine, carry-forward, and conflict repair;
5. Follow-ups: Adjacent and Guidance Findings plus Contract Revisions;
6. Resource Outcome: Attempts, Harness time, and provider-reported tokens when available.

Do not merge Agent claims, machine Evidence, and accepted exceptions into one undifferentiated completion statement.

Human-readable AIWB status, Run reports, Replan projections, Finding summaries, and explanatory fields in typed Planner, Worker, and Reviewer output default to Chinese through `output_locale: zh-CN`. Admission freezes the Agent output locale in Role Profiles so one Run remains consistent. Stable schema keys, IDs, enums, and RunTrace event kinds remain English; compiler errors, test output, logs, and other raw Evidence preserve their source language. Future languages add renderers and locale values without migrating canonical RunLedger facts. GitHub Issue language is outside this rule.

## Delivery order

Finish the #43 RunLedger cutover and #46-#53 acceptance scope without adding this role and change-control redesign. Issue #54 then adds only the existing ExecutionManifest extensions, RunLedger-owned RunTrace, Trace Coverage, and stable traceability substrate. A separate parent specification owns Development Doctrine, Change Control, Planner/Worker/Reviewer feedback, assurance, replanning, quarantine, and localized reports, and depends on both foundations.

The first tracer bullet proves one standard-assurance Todo with fake Agent and Harness adapters: frozen Doctrine and Role Profiles, one Planner assignment, a read-only Worker Change Plan, deterministic preflight, one resumed Change Slice, Harness Evidence, Work Report, Candidate Reviewer, Chinese layered report, and Requirement-to-Evidence RunTrace. Multi-Todo replanning, Failure Quarantine, carry-forward, Kubernetes, and additional locales follow only after that control loop is proven.

The first real dogfood repeats that path in one local non-production repository and includes at least one Harness failure returned to Planner for reassignment. It must produce Candidate review and complete Requirement-Test-Change-Evidence trace without target-branch merge, production access, or Kubernetes.

New workflow Contracts expose only Planner, Worker, and Reviewer. Old Test Designer, Implementer, and Verifier behavior remains interpretable only for immutable older ExecutionSnapshots; snapshots are never migrated or rewritten. Explicit version-compatible readers may remain while old Runs are active and are removed only through a later compatibility decision.
