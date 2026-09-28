# Spec acceptance — outline

Use the target repository's test-document convention; otherwise `docs/testing/spec-<issue-id>.md`. This document holds case design and execution evidence, not a second task tracker. Link the parent Issue and repository integration guide. The parent agent owns expected results; the execution agent fills observations and status.

## Scope and coverage

- Parent Issue/spec revision, child Issue references, and in-scope behavior.
- Repository guide links and reviewed case-design revision.
- Map every parent acceptance criterion to case IDs, including cross-Issue workflows. Explain any uncovered requirement.
- Cover relevant happy paths, boundaries, invalid inputs, authorization, dependency failure/recovery, and compatibility; omit categories that do not apply with a brief reason.

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
- Invariant / boundary: applicable behavior-sequence mapping and evidence level, including mocked dependencies.
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

During preflight, identify the project's existing report location, intended readers and access method, and include them in the execution plan. Prefer a summary/index in this acceptance document pointing to existing results; if the project requires a separate report, make it a linked summary of those records. Business reports and raw evidence stay in the owning project's approved artifact location. AIWB supplies the outline only.

The parent assembles the requirement-level self-test report from worker observations and the records above, without another agent or a repeat test run just to produce the report. Include:

- Requirement and acceptance-design revisions; tested branch/commit or complete patch; relevant environment and served version.
- Requirement → case → actual outcome → evidence links, with commands and execution times available from their original records. Distinguish developer self-test, independent QA and final integration acceptance, naming each executor/attempt; one role's report cannot stand in for another's missing execution.
- Initial failures, repair candidates and retests; remaining FAIL/BLOCKED/NOT_RUN cases; mocked versus real dependencies; reuse/invalidation decisions after candidate or environment changes. Retain historical results separately from current-candidate coverage.
- For UI cases, sanitized screenshots or recordings of the key observed behavior alongside assertions. If capture was unavailable, report that gap; a screenshot of a loaded page alone proves no interaction. Unexecuted cases have no fabricated observations or media.
- Report entry, publication state and reader-access evidence or limitation. A report with failing or unverified cases is still deliverable as evidence, with acceptance explicitly incomplete.

Check the entry and required evidence links using authorized access checks for the intended audience, recording what was actually verified. Author access, an HTTP success or a remote absolute path alone does not prove reader access. If verification is unavailable, mark access unverified; if denied, fix within existing authority or identify the required grant. Without publication authority, retain the complete local report and report “local report ready; publication pending” with its path and intended destination. Never publish privately scoped evidence to obtain a convenient link.

Attach the entry and access/publication status to the final reply and authorized requirement/MR updates. A chat-only PASS needs persistent supporting records; a remote-only path needs an authorized reader-accessible route; an old-candidate report needs an applicability assessment and affected retests; an inaccessible link remains an unresolved delivery gap. If the agreed report is missing, delivery materials are incomplete regardless of test counts.
