# Spec acceptance — outline

Use the target repository's test-document convention; otherwise `docs/testing/spec-<issue-id>.md`. This document holds case design and execution evidence, not a second task tracker. Link the parent Issue and repository integration guide. The parent agent owns expected results; the execution agent fills observations and status.

## Scope and coverage

- Parent Issue/spec revision, child Issue references, and in-scope behavior.
- Repository guide links and reviewed case-design revision.
- Map every parent acceptance criterion to case IDs, including cross-Issue workflows. Explain any uncovered requirement.
- Cover relevant happy paths, boundaries, invalid inputs, authorization, dependency failure/recovery, and compatibility; omit categories that do not apply with a brief reason.

## Case <stable ID>: <behavior>

- Requirement: parent criterion and related child Issues.
- Preconditions: environment, account role, data, candidate identity, permissions.
- Steps: executable command reference or repeatable browser/API actions.
- Expected: observable behavior/assertions, including cleanup effects where relevant.
- Evidence: what response/assertion/log/artifact proves this result; sanitize sensitive data.
- Cleanup: run-owned resources/data to remove, and actions that need separate authority.
- Initial status: NOT_RUN.

## Execution record

For every attempt record run ID/date, executor/model, tested commit or complete starting patch, image/deployment identity if applicable, environment, case-design revision, and relevant commands. Use sequential attempts when shared test data makes parallel execution unsafe. Preserve earlier failures and their evidence when recording retests. Keep evidence in a persistent project artifact location. For reused results, cite the original attempt and why it still covers this candidate/environment; for repeated checks, state what changed or which evidence was missing. BLOCKED entries record sources already checked and the fact or event required to resume, so a handoff does not restart the same investigation.

| Case | Attempt | Status | Actual result | Evidence reference | Reason / follow-up |
| --- | --- | --- | --- | --- | --- |

- PASS: observed evidence matches the expected result on the identified candidate.
- FAIL: executed behavior contradicts the expected result.
- BLOCKED: a prerequisite, permission, environment, identity, or oracle is unavailable; describe why.
- NOT_RUN: execution has not been attempted.

A process exiting zero or a model saying it passed is insufficient when the case requires observable API/UI behavior. No test run, old-candidate results, missing evidence, and unexplained status rows are not PASS. Ambiguous expectations go back to the parent; the executor does not rewrite them.

## Final verdict

Counts and case IDs by status; coverage gaps; first failures and retests; cleanup outcomes and retained resources. Parent acceptance requires all required cases PASS on the final relevant candidate, or an explicitly approved scope change recorded with its rationale. BLOCKED/NOT_RUN means acceptance remains incomplete. Do not silently omit difficult cases or replace required real integrations with mocks.
