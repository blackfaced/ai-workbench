# Implement Batch — run record

Use the target project's persistent artifact convention; otherwise `docs/testing/runs/<run-id>.md`, with a unique run ID. Link it from the spec acceptance document and existing checkpoint. Records stay with the owning project; AIWB distributes only this outline. Issue state remains in the tracker. Recording does not authorize publication, committing artifacts or external telemetry.

The parent is the sole record writer. Include the attempt ID and required return fields (start/end evidence, effective model, outcome, finding/repair links and available usage) in each dispatch. Other agents return facts in their existing handoffs; no logging agent, extra review or polling loop is needed. Initialize after confirmation and record attempt starts before dispatch. Append outcomes at handoff, batch acceptance and final/early stop. On recovery reconcile open attempts with client evidence; preserve an interrupted/unknown outcome when completion cannot be established. Keep previous outcomes and mark corrections rather than rewriting failures as successes.

## Run context

- Run ID; confirmed execution start and completion/stop timestamps; parent/spec reference and revision; repositories and starting candidate identities.
- Client/version; Skill source commit plus dirty-patch identity or installed-content digest; use `unknown` with a reason when unavailable.
- Confirmed plan reference: graph/batches, implement versus verify-existing children, concurrency, and review policy. Record stages, requested models/efforts, round limits and escalation rules as actually approved, including an ordinary single-review policy. Do not introduce staged review solely to populate this record.
- Acceptance document, integration guides, persistent evidence and checkpoint links; relevant environment identity without credentials.
- Comparison run ID, if any. Note differences in scope, risk, diff size, checks, environment and policy; unrelated runs are not a controlled comparison.

## Attempts

One row per actual implementation/repair, review, integration, check group or final acceptance attempt; not per tool call. Give attempts stable IDs, batch/Issue scope and parent attempt IDs where work is nested. Record both requested and observed effective model/effort; inherited or unavailable identity is `unknown`, not the requested value.

| Attempt / parent | Batch / Issues | Role / review stage / round | Client task ID; requested → effective model/effort | Start / end (ISO 8601 with timezone) | Candidate base → tip or complete patch | Outcome / reason | Evidence / usage reference |
| --- | --- | --- | --- | --- | --- | --- | --- |

- Outcomes: running, completed, failed, blocked, interrupted or unknown. A completed review means it returned a result, not that the candidate passed acceptance. Link the review verdict or test result, including explicit zero findings where observed.
- Record each repair/re-review as a new attempt linked to the triggering finding IDs. Record escalations, retries and repeated checks with their reason; reused check evidence links the original attempt and applicability assessment, not a fictitious new execution.
- Read timestamps/durations and usage from available client/command evidence. Label parent dispatch/receipt times as such when exact child timing is unavailable. Never reconstruct precise timings from prose; retain open ends and report timing gaps.
- For observed waits, retain interval and cause (queue/capacity, human approval, environment/blocker). Unknown wait decomposition stays unknown. Include failures and stopped runs, not just successful batches.

## Review findings

Keep one stable finding ID per root cause; repeated reports link that ID. Retain the first discovery stage/model and candidate, later confirmations and regressions. References to sanitized review reports avoid copying their full text.

| Finding | Issue / location / root cause / severity | First-seen attempt / candidate | Disposition / evidence / decision owner | Repair candidate / verification attempt | Later reports / reopenings |
| --- | --- | --- | --- | --- | --- |

Dispositions: confirmed defect, rejected with reason, duplicate of another ID, suggestion/out of scope, or unresolved. A worker accepting a comment or changing code is not proof of a defect: cite a reproduction, failing assertion or concrete contract/call-path evidence. Preserve disputed findings for adjudication under the selected review policy. Zero comments does not establish zero defects. Confirmed defects may still be unfixed; disposition and repair verification are separate.

## Usage and cost evidence

Link available client usage records with their accounting scope (attempt, task/session or whole run) and unique source ID. Preserve reported input/cached-input/output token categories without inventing missing categories. Store provider-reported cost with currency, or label an estimate with the dated pricing source and calculation. Never substitute account-wide usage for task usage. Shared session totals belong at that scope; do not allocate them to children without evidence or add them again to child totals.

Use `unknown — <reason>` for unavailable usage/cost, including clients that expose neither. Missing metrics do not block delivery, but must be visible in analysis. Do not dump prompts, full conversations, hidden reasoning, secrets or raw API bodies into the record; use compact facts and sanitized evidence links. This outline does not require copying client databases or installing telemetry.

## Summary at completion or stop

- Final/stop status, accepted candidate, acceptance evidence and remaining blockers.
- Observed elapsed time from confirmed execution start to completion/stop, per-batch boundaries, and known waits. Show summed attempt time separately: parallel or nested durations must not be added and presented as elapsed time.
- Attempts by stage/model, repair/review rounds, escalation and rerun reasons. Summarize all recorded stages, including implementation, repairs and tests, not review calls alone.
- Confirmed unique defects, rejected reports, duplicate reports, suggestions and unresolved reports by discovery stage/model. State counting units and denominators; unresolved reports are not automatically false positives. Report later-stage newly confirmed defects separately from repeated findings. A later defect could have been introduced by a repair: check candidate history before calling it an earlier review miss.
- Observed cost/token totals with accounting scope and coverage (which attempts/scopes are missing), estimates separately. A partial total is not total run cost; do not infer savings without a comparable baseline. Describe workflow/candidate differences when comparing runs and do not claim recall without a complete defect inventory.
- Later escaped bugs: append the bug/lesson link and affected candidate when supplied or discovered; no background monitoring is implied. Keep the original acceptance record intact.

If older runs lack records, retain only facts recoverable from evidence and label the gaps. Do not fill a retrospective baseline with guessed metrics.
