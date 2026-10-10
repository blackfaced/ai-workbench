# Staged review — optional execution policy

Select this policy when the user requests cheap-first/stronger-final review. It changes review placement, not acceptance requirements. Keep ordinary review available and do not change a confirmed run silently. Model cost/capability is client-specific: Luna for initial review and Astra for final review are examples, not mandatory defaults or evidence of native availability.

## Plan and roles

Include exact initial/final reviewer models and efforts, observed availability, per-Issue initial-review budget, early-escalation criteria and concurrent-agent capacity in the existing confirmation plan. Default proposal: one initial review and, only after repairs, at most one incremental recheck; one independent full review of the batch's final candidate. The limit is per Issue across agents, not reset by spawning a new reviewer. Additional rounds or model substitutions require a confirmed change; an already approved escalation does not require asking again.

Workers own implementation and substantive repairs. Review agents inspect candidates and return findings; they do not edit implementation, weaken tests, or merge. The integrator remains the only writer of the integration worktree and owns batch checks. The parent coordinates, records evidence and accepts the batch. A final reviewer is independent of implementation workers and initial reviewers, with fresh context; use the client's native model selection, not a prompt pretending to switch models. Required review axes remain correctness, standards and necessity; consolidate their coverage instead of recursively launching complete review workflows.

Reserve review capacity in the existing concurrency budget, counting the parent where applicable. Release completed workers or run reviews sequentially when necessary; do not exceed the client limit to add a review stage. Stronger review does not require a second integration branch or another scheduler.

## Route risk before initial review

The parent/integrator inspects spec constraints, changed paths and relevant callers. Authentication/authorization, secret handling, irreversible data changes/migrations, payments, critical concurrency/state consistency and cross-system trust boundaries need stronger review before the affected candidate is integrated. A small diff or a cheap review reporting no findings is not evidence of low risk. If impact cannot be determined, obtain context or escalate within the approved policy; do not silently classify it as low risk.

High-risk work can skip cheap review. Early stronger review is bounded to the affected contract and interactions; batch review still covers the final combined candidate. Reuse valid evidence by reference, explaining changed context rather than automatically rerunning the same checks. Existing implementations use the same risk routing and verification path without manufacturing a worker or auditing unrelated legacy code.

## Initial review and repair

1. Review each candidate against its exact base/complete patch, Issue criteria and relevant repository context. Require a concrete location, triggering condition, impact and supporting contract/call-path or test evidence for each proposed defect. Return an explicit result even when there are zero findings.
2. The integrator consolidates findings and their dispositions; the worker repairs confirmed defects and runs affected checks. Do not change code merely to satisfy unsupported comments or style preferences. Preserve rejected/disputed findings and reasons in the run record.
3. If repairs occurred, use the remaining incremental recheck to inspect the repair and its affected callers/tests. Zero initial findings needs no second scan. Unresolved disagreement, exhausted budget, repeated failure without new evidence or newly exposed high risk routes to the approved stronger reviewer/diagnosis; never loop until the cheap model says nothing.

A sufficiently reviewed candidate may enter the integration branch serially within existing authority. It remains provisional: neither a worker finishing nor initial review passing releases downstream dependencies. Unresolved required findings block candidate integration, or batch acceptance if discovered after integration; handle an approved scope change explicitly.

## Stronger batch review and verification

After candidate integration settles, provide a fresh stronger reviewer with the accepted batch base, final integration tip/complete patch, spec/Issue constraints, relevant code/callers and verification evidence. Include verify-existing scope and its evidence even when it contributes no new diff. First obtain its independent assessment before supplying earlier review conclusions; then reconcile previous findings, disputes and repairs. Keep outstanding concerns visible in that reconciliation and do not interpret independent review as permission to forget them.

Review the full net change and affected interactions, not just the cheap model's finding list. Check cross-Issue compatibility, architectural boundaries, unnecessary implementation and test/gate changes as well as correctness. Record the reviewed candidate identity and verdict. Finding nothing does not replace executable acceptance evidence.

Send required repairs to their owning workers, integrate serially, then ask the stronger reviewer to recheck the incremental changes and affected interactions. Reopen broader review when the repair changes the batch contract or invalidates earlier coverage. Do not restart cheap-first rounds or repeat full review for unchanged code; repeated failure without new evidence goes to diagnosis/replanning. Stop with an incomplete batch if required findings or evidence remain unresolved.

The integrator executes required batch-wide checks on the resulting final candidate. Existing valid evidence may be reused under the Skill's relevance rules; changes invalidate only affected evidence unless repository gates require more. A different reviewer is not itself a reason to rebuild or rerun tests. The parent accepts only when the stronger verdict and required checks cover the final relevant candidate. Only then may the next dependency batch start. Final spec integration acceptance remains a separate requirement after all batches.

## Evidence and comparison

Use [the existing run record](run-record.md) for policy, stage/model, candidate identities, finding origin/disposition, repairs, escalations and timing/usage. Count genuinely new confirmed findings separately from duplicate reports or bugs introduced by repairs. Compare end-to-end elapsed time and all observed costs, including rework/checks; a cheap review call alone does not establish savings. Do not infer benchmark recall or savings from a small uncontrolled trial.
