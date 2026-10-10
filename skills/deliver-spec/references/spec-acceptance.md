# Spec acceptance — outline

Use the target repository's test-document convention; otherwise `docs/testing/spec-<issue-id>.md`. This document holds case design and execution evidence, not a second task tracker. Link the parent Issue and repository integration guide. The parent agent owns expected results; the execution agent fills observations and status.

## Scope and coverage

- Parent Issue/spec revision, child Issue references, and in-scope behavior.
- Repository guide links and reviewed case-design revision.
- Map every parent acceptance criterion to case IDs, including cross-Issue workflows. Explain any uncovered requirement.
- Cover relevant happy paths, boundaries, invalid inputs, authorization, dependency failure/recovery, and compatibility; omit categories that do not apply with a brief reason.

## Backward-compatibility coverage

When existing callers or stored/configured behavior may be affected, map **old observable contract → affected callers/modules → before/after action → assertion → evidence** before implementation. Backward compatibility outranks maintainability, deduplication and code cleanliness unless the approved requirement explicitly authorizes a named migration or breaking change.

Cover applicable boundaries rather than only touched files:

- Public API/request/response shapes, exported types and error semantics.
- Configuration defaults, feature-flag-off behavior and authentication/authorization decisions.
- Persisted data read/write, reload, migration and rollback behavior.
- Shared components, hooks, utilities and each known sibling-module caller class.
- User-visible state, side effects, ordering, polling/retry cadence, performance or resource ceilings when those are part of existing behavior.

Use production-entrypoint characterization or regression cases to pin current behavior before replacing internals. A helper unit test, new-path happy case, source scan or build success alone cannot prove old callers remain compatible. Prefer an additive adapter/wrapper, optional field, default-off flag or retained old path; state the removal/migration condition separately. Any compatibility boundary without executable evidence remains BLOCKED/NOT_RUN unless the owner explicitly accepts that named gap with migration and rollback responsibility. Do not silently weaken or remove old-behavior assertions to make the candidate pass.

## Behavior-sequence coverage

For applicable behaviors, map **invariant → action sequence → observable assertion → evidence** into the cases below. Read the actual entrypoints and callers when designing the sequence. Select boundaries by the requirement and change risk; state why other categories are not applicable rather than building a Cartesian product of all states.

| Behavior | Sequence to consider | Assertion required at the owning boundary |
| --- | --- | --- |
| Stateful interaction | A → B → A, then edit again | Retained state and the next operation both match the contract; seeing each static screen is insufficient. |
| Frozen inputs / retry | Start an operation, change external settings, fail and retry through the production caller | Observe the actual retry request and resulting behavior against the original frozen-input contract. A helper copy/equality test alone does not cover caller selection of inputs. |
| Human edits / upstream synchronization | Explicitly clear a value, and separately change it to a non-empty value; then reload or re-adopt upstream content as applicable | Preserve or replace each value according to the contract; distinguish uninitialized state from an explicit empty edit. Inspect persisted and displayed values where both matter. |
| Identity / invalidation | Change each independent relevant identity or invalidation trigger with other factors held constant | Assert which state is invalidated and which is retained. A combined navigation test proves that combination, not each trigger in isolation. |

Identify the evidence level per case: source inspection, production-function test, browser with mocked dependencies, or real integration. State which layers the check executes or bypasses; counts of passing tests do not upgrade that boundary. Use existing tests when they assert the required behavior. Later escaped defects link to the run record's existing escaped-bug entry; retain the original PASS and add the finding/retest rather than rewriting history.

## Case <stable ID>: <behavior>

- Requirement: parent criterion and related child Issues.
- Invariant / boundary: applicable behavior-sequence and backward-compatibility mapping, affected caller/module classes, evidence level, and mocked dependencies.
- Preconditions: environment, account role, data, candidate identity, permissions.
- Steps: executable command reference or repeatable browser/API actions.
- Expected: observable behavior/assertions, including cleanup effects where relevant.
- Evidence: what response/assertion/log/artifact proves this result; sanitize sensitive data.
- Cleanup: run-owned resources/data to remove, and actions that need separate authority.
- Initial status: NOT_RUN.

## Execution record

Link the parent-maintained [run record](run-record.md) for attempt timing, model/usage provenance and review findings; keep case outcomes here and reference their attempt IDs rather than duplicating results.

For every attempt record run ID/date, executor/model and role (developer self-test, independent QA, or final integration acceptance), tested branch/commit or complete starting patch, image/deployment identity if applicable, environment, case-design revision, execution time and relevant commands. Reuse identity/timing fields from the linked run record. Use sequential attempts when shared test data makes parallel execution unsafe. Preserve earlier failures and their evidence when recording retests. Keep evidence in a persistent project artifact location. For reused results, cite the original attempt and why it still covers this candidate/environment; for repeated checks, state what changed or which evidence was missing. BLOCKED entries record sources already checked and the fact or event required to resume, so a handoff does not restart the same investigation.

| Case | Attempt | Status | Actual result | Evidence reference | Reason / follow-up |
| --- | --- | --- | --- | --- | --- |

- PASS: observed evidence matches the expected result on the identified candidate.
- FAIL: executed behavior contradicts the expected result.
- BLOCKED: a prerequisite, permission, environment, identity, or oracle is unavailable; describe why.
- NOT_RUN: execution has not been attempted.

A process exiting zero or a model saying it passed is insufficient when the case requires observable API/UI behavior. No test run, old-candidate results, missing evidence, and unexplained status rows are not PASS. Ambiguous expectations go back to the parent; the executor does not rewrite them.

## Final verdict

Counts and case IDs by status; coverage gaps; first failures and retests; cleanup outcomes and retained resources. Parent acceptance requires all required cases PASS on the final relevant candidate, or an explicitly approved scope change recorded with its rationale. BLOCKED/NOT_RUN means acceptance remains incomplete. Do not silently omit difficult cases or replace required real integrations with mocks.

## Self-test report and delivery

During preflight, identify the project's report location, intended readers and access route. Read the [self-test-report Skill](../../self-test-report/SKILL.md) for report writing, updates and evidence review, using its [template](../../self-test-report/assets/report-template.md) only when the project has no suitable existing report. If unavailable, resolve that reporting dependency before claiming complete delivery; continue independent authorized work.

The parent assembles the report from existing observations and case records, without another agent or a repeat test run merely to fill it. Keep one result source: this acceptance record owns case design and execution outcomes; the report is its summary/index. Report-specific identity, role separation, evidence validity, UI capture, open-defect and reader-access rules live in self-test-report, not a second copy here. Preserve this document's original execution statuses; attach evidence validity separately rather than relabeling history.

Implement-batch retains expected outcomes, execution permissions, role assignments and final acceptance. A report cannot accept the spec or waive missing required evidence. Attach its concrete entry and publication/access status to the final reply and authorized Issue/MR updates, including failed or incomplete deliveries. Missing the agreed report remains an incomplete delivery even when tests pass.
