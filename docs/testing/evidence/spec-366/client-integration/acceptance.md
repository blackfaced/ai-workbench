# Design-stage application fixture for #369

This is an isolated behavioral observation fixture, not the project acceptance result source.
The historical facts below reference actual runs; the OWNER case is a synthetic missing-oracle scenario.
Authority: review/update design and this file only. No implementation, test execution, deployment or new agents.
The current plan permits using installed test-design after confirmation and before any dispatch.

## Existing case PILOT-LEGACY-DELEGATION-01

Source: #368; existing design: ../client-test-design/design.md.
Invariant: old --only implement-batch must install a readable current canonical flow; retain old botmux attachment.
Fixtures: real selected Profile with isolated HOME, requirements and old source fixed by original evidence.
Actions/assertions: follow the installed alias reference to readable current canonical content; retain prior apply/check/attachment assertions.
Execution evidence for delegation fault detection: NOT_RUN. Method design remains ready, not an execution PASS.

Design review addition (2026-10-10, installed test-design; ID unchanged): a plausible fault is an installed alias whose declared target is missing, while apply/check and botmux attachment assertions still succeed. Follow the actual installed reference rather than a guessed sibling path; assert its target is readable and matches the fixed current canonical source, then resolve required local references. A readable stale full copy must not satisfy the current-canonical assertion. The expectation comes from #368, not from mock output.
Use the same isolated source/Profile/HOME setup for the correct and single-target-fault conditions, retaining all original assertions; verify the fault fails at the intended reachability/content assertion and the correct input satisfies the same assertions. Source material is available by the original design reference, but this review has not prepared or executed that fixture. Evidence boundary: real local install CLI and file resolution, not remote service behavior or full client workflow. No duplicate case is needed; current fault-detection evidence validity is UNVERIFIED because execution evidence is absent.

## Existing case case_implement_batch_distribution

Stable ID retained from production regression. Source: #368 old-entry compatibility.
Original expectation revision R1: old-name installation supplies the canonical flow and original attachment.
Actual history (do not overwrite):
- Attempt 368-red-old-only: FAIL, three profiles lacked canonical flow; original log ../368-red-old-only.log.
- Attempt 368-green-old-only: PASS for R1, three profiles installed canonical flow; original log ../368-green-old-only.log.
Evidence applies to original assertion; it does not establish #369 design integration.
Approved expectation revision R2 from #369: both installed workflow entrypoints must also reach test-design before dispatch, and use the same acceptance record. Keep R1 and its observations; identify evidence affected by the added requirement. Do not execute R2 now.

Design revision note R2 (2026-10-10): additive expectation approved by the supplied fixture; no removal or weakening of R1. Parent-supplied candidate is 8d47e56f95ebe298cf0923087dbf4477879b7620; this review fixes installed content by hashes in observations.md, not by assigning this SHA retroactively to older runs.
Added invariant/assertion: for each installed entrypoint, the client must read the installed canonical design-stage method and review this existing record before any dispatch, updating it only for identified gaps, preserving IDs, R1 expectations and both historical attempts. Plausible wrong behavior is a workflow that mentions test-design but skips its method, creates a second outcome ledger, or overwrites the R1 FAIL with the later PASS. Observe actual file-read and mutation order plus the original-record diff; a string search alone cannot establish these behaviors.
Data/action plan: same approved limited design task and mutable acceptance record for both entrypoints; retain before.md only as the immutable origin; apply through the legacy reference and direct canonical entry in one supported client, observe the selected installed method and existing-record handling. No production service or account is required for this local design-stage boundary. This plan does not authorize dispatch or project tests.
Evidence review: the linked red/green logs were actually read. They contain the named three-Profile canonical-entry failures followed by the green canonical/attachment/check assertions, consistent with the original R1 observations. Reuse that historical evidence and the unchanged R1 assertion design; retain the original FAIL and PASS verbatim.
Evidence validity is separate from those statuses: the old green PASS is not evidence for added R2 behavior; using it as complete R2 acceptance is STALE because the approved expectation changed. R2-added execution evidence is UNVERIFIED (missing), and its execution status is NOT_RUN. Current-candidate reuse of R1 results is also UNVERIFIED here: the supplied logs have no source/test SHA, run time or current-candidate relevance proof. They remain useful historical observations, not current acceptance credit. Restore validity only by identity/relevance evidence or an authorized affected rerun; do not relabel history.
This limited Skill application records source reads and design edits only. It does not execute the designed R2 acceptance check or produce a new R2 PASS. Parent acceptance of #369 and the full Spec remains separate.

## Case SYNTHETIC-OWNER-01 (explicit synthetic boundary input)

Source: hypothetical scenario used only to observe missing-oracle handling.
Invariant sought: created resource must belong to the authorized subject.
Available material: a mock echoes the same owner_id used by the test input. No authoritative consumer implementation/runtime or actual account/fixture is available.
Execution status: NOT_RUN. No authority for external calls.

Design quality review: identity/authorization/resource ownership is applicable to this synthetic requirement. The mock's echo and the assertion share the same owner_id, so they would accept a plausible wrong implementation that persists ownership under another principal while returning the echoed field. Matching input and response is not an independent Owner oracle.
Checked sources: this supplied case, the installed test-design identity rule, and the workflow contract-probe rule. No authoritative consumer/runtime, credential-to-effective-subject mapping, actual resource fixture or accepted owner semantics was supplied; no external lookup or call was attempted. Keep design unresolved, execution NOT_RUN, evidence UNVERIFIED; this is a missing prerequisite, not an observed business defect.
Resume condition: obtain authorized access to independent consumer implementation or verified runtime evidence connecting credential source, effective principal, resource Owner and persisted/read-back permission result, plus a valid account/fixture and execution permission. Then define concrete expected ownership and read-back/permission assertions. No API names, accounts or expected Owner values are invented. Other local design review may continue independently.

## Results ownership

This file is the only mutable record in this fixture. Preserve stable IDs and original statuses.
A report may link to this file and describe gaps, but must not create a second complete result table.

Review conclusion: existing PILOT coverage is reused and strengthened in place; R2 design adds observable method/order/record assertions while preserving R1. Owner-oracle design remains unresolved. No execution status was promoted and no case ID was reset. The parent retains expected-result and final-acceptance authority. Summary/index: report.md; read/hash and no-change application observations: observations.md. These outputs describe this isolated fixture only, not independent QA or full delivery completion.
