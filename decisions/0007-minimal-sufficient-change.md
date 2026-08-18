# 0007 - Optimize Runs for Minimal Sufficient Change

## Status

Accepted

## Context

Long-running coding Agents tend to optimize for apparent completeness: they repair adjacent defects, introduce abstractions for possible future work, and reinterpret implementation obstacles as permission to widen scope. Ralph-style repetition can amplify that drift because another loop is cheap, while a successful build or an Agent completion signal does not prove that every change was authorized or necessary.

AI Workbench already freezes the approved execution authority and uses machine Harness Evidence for acceptance. It also needs a durable rule for deciding what work belongs inside that authority.

## Decision

Every AI Workbench Run optimizes for the **Minimal Sufficient Change**: it must completely satisfy the approved Contract while remaining intentionally minimal outside that acceptance boundary. Every implementation change, test, dependency, and new concept must serve the current Todo. Useful adjacent work is recorded separately and never implemented by the current Run.

AI Workbench adopts Ralph's short feedback loop only inside this control boundary. One fresh Agent Attempt proposes and implements one independently verifiable Change Slice, receives a bounded Iteration Brief, and is evaluated first by the smallest relevant machine gate, then by its Todo gate, and finally by the complete Candidate gates. Agent completion signals end Attempts but never accept work.

A Worker may make approved mechanical and local design decisions, but it cannot reinterpret a boundary-changing decision or supporting refactor as implicit authority. When correct implementation requires a missing dependency, contradictory requirement, unauthorized boundary decision, or hard Change Budget violation, it records a Replan Request. The Planner may produce an unapproved Contract Revision and determine the affected dependency-closed subgraph; only explicit approval and a new Admission create executable authority.

Each Worker session begins read-only, emits a typed Change Plan, and receives write authority for that Change Slice only after deterministic preflight. One bounded repair may reuse the session; repeated failure moves to one fresh diagnostic Attempt instead of an unbounded same-context loop. Soft budget warnings use typed, non-authorizing Budget Deviations, while hard stops require replanning.

Before planning a change, the Worker gathers bounded Existing Behavior Evidence so that search omissions do not produce duplicate implementations. Tests for approved behavior map to Requirements; Preservation Tests may protect evidenced existing behavior but cannot invent product requirements.

Pre-existing failures may continue only through an explicitly authorized, Run-local Failure Quarantine backed by comparative base and Candidate Evidence. Tests remain unchanged, acceptance-critical failures cannot be quarantined, and the Candidate is reported distinctly from a completely green result.

A Planner-generated Contract Revision never mutates the active Run. Approval creates a new Admission and Run, supersedes the old Run, and carries forward prior work only through an explicitly approved list followed by complete Candidate re-verification.

## Consequences

The workbench is boundary-complete rather than repository-complete. It can run repeatedly without turning eventual consistency into permission for scope growth. Planner, Worker, Reviewer, prompts, Skills, and future workflow modes share the same principle, while enforcement remains deterministic and authoritative only inside an admitted Run.

The additional planning and traceability artifacts increase control-plane work. AI Workbench limits their cost through typed, bounded projections, fresh sessions, staged machine backpressure, and final or risk-triggered LLM review rather than an unconditional reviewer after every slice.

Planner, Worker, and Reviewer are Contract-frozen Role Profiles over the same AgentAdapter seam. The provider remains fixed without fallback, while the owner may explicitly freeze different model and reasoning settings per role. Lean, standard, and strict assurance levels vary review and approved Harness intensity without changing scope or safety invariants; interaction and diagnostic choices remain separate dimensions.

Role Profiles also freeze a human-output locale, defaulting to Chinese. Machine schemas and durable identities remain language-neutral English, raw Evidence preserves its source language, and localized reports remain projections so later language support does not migrate RunLedger facts.

All roles share one versioned Development Doctrine, resolved and frozen at Admission. Setup reviews project defaults once, `/ask` applies the Doctrine as advice without execution authority, and a separate owner-approved knowledge-refresh flow is the only way Guidance Findings alter later Doctrine versions. Standard assurance is the default; lean and strict are explicit Contract-approved variations rather than hidden runtime simplifications or escalations.

This decision does not expand the in-progress #43 RunLedger rewrite or its #46-#53 acceptance boundary. After that cutover, #54 supplies only ExecutionManifest and RunTrace foundations; a separate parent specification introduces this workflow through a one-Todo tracer bullet and local non-production dogfood before multi-Todo replanning and exceptional recovery paths.

The new workflow replaces Test Designer, Implementer, and Verifier as public roles with Planner, Worker, and Reviewer. Testing, implementation, execution, diagnosis, and rework are Worker Assignments. Existing immutable ExecutionSnapshots are never migrated: supported older workflow readers may finish active Runs, while new Admissions use the new version. When implemented, this decision supersedes ADR 0006 only for the preserved legacy role sequence; ADR 0006's Admission, RunLedger, Evidence, recovery, Harness, and safety authority remain unchanged.

Reviewers are independent, read-only, and unable to accept work or modify the Candidate. Contract-authorized typed findings may block and return work to a bounded Worker rework or Planner feedback path; preferences and adjacent improvements cannot block. Review/rework is bounded rather than repeated until a model agrees.

The Planner proposes risk-based Review Policy and staged test coverage before approval. Admission freezes Todo and Candidate review triggers plus Harness levels. Cheap slice feedback precedes Todo-local integration and complete Candidate integration; non-production shared environments remain explicit and production remains forbidden.

Planner, Worker, and Reviewer are the only Agent roles. Test authoring, implementation, test execution, diagnosis, and rework remain permission-scoped Worker Assignments rather than specialist Agent concepts. Workers may request approved Harness actions and write typed Work Reports, while the Daemon owns execution and Evidence.

All test failures return to planning. Unique pre-approved local responses may be selected by deterministic policy; ambiguous, repeated, cross-boundary, or infrastructure failures invoke a clean Planner Agent. Planner dispositions, not Worker suggestions, authorize the next Assignment within the frozen Contract or request a new Contract Revision.
