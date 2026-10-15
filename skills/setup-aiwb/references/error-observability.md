# Project error handling and observability setup

Turn general engineering guidance into conventions grounded in this project's current implementation. Use during project onboarding, maintenance after relevant changes, or an explicit error/observability review. Apply only to the affected runtime surfaces; document why a surface is not applicable. Reuse the project's selected engineering rules instead of copying another project's error taxonomy, SDK or monitoring stack.

## 1. Inspect a bounded sample

Record the target repository/worktree, branch and commit; identify uncommitted changes separately. Read applicable rules and maintained error, logging, monitoring and test documentation. Find the current error definitions, public adapters, logger/metric/trace wrappers and their actual callers before proposing a convention.

Review a small set of relevant recent fixes and their tests, following the touched paths into the target revision. Record what failure motivated each fix and which mechanism prevents it. A commit title, helper's docstring or historical PASS is a lead, not proof. A helper on another branch is a candidate, not an available dependency. For cherry-picked/squashed work, verify the current code and callers rather than inferring absence from commit ancestry alone. State when remote freshness is unverified.

Trace a representative production entry through a known failure and an unknown failure to its real consumer. Add asynchronous, retry or partial-success paths only where applicable. Follow cross-repository boundaries to the owning API/worker/UI contract using links to each repository's sources; a matching field name does not prove the contract. Stop once the affected boundaries are understood; setup is not a full repository audit.

Check candidate patterns against their callers and tests:

- Error classification: typed/domain errors and structured codes survive wrapping; protocol status, business status and terminal task status agree. Separate public compatibility mappings from internal diagnostic detail. Legacy text decoding needs a named compatibility boundary, known input shapes and negative cases; arbitrary text must not relabel an unknown fault.
- Diagnostics: locate the shared logging boundary, context propagation and sanctioned fields. Retaining the original cause does not authorize emitting it; decoder/SDK exceptions can contain rejected values or secrets. Verify safe structured fields and how to correlate them with the request/task/attempt.
- Measurements: locate real recording nodes and exporters. Distinguish logical operations, attempts, per-item failures and terminal outcomes; check label bounds, duration units and actual exported names. Retryability and final-attempt status are independent. Inspect fault isolation at callers, not just a helper promising best-effort behavior.
- User-facing failures: when applicable, trace the code to localized messages, the retry action and persisted task/item history. Confirm unknown errors stay neutral, late responses cannot replace a newer attempt, and public details have a defined disclosure boundary. Preserving provider text is not automatically a safe pattern to promote.

## 2. Write project-owned conventions

First choose a maintained project document or section and its owner. Extend it in place; create a small document only if no suitable location exists. For a team repository, use the approved shared or private location and preserve team-owned guidance as required by [project context setup](project-context.md). Keep project facts and evidence in that location, not in AIWB or a second cross-project lessons database.

Use a short table or equivalent prose for the applicable entries:

| Entry | Project-specific content |
| --- | --- |
| Error contract | Definition/registry, conversion function, real callers and outward protocol/task response; safe message and retry rules; compatibility exceptions and unknown-error behavior |
| Diagnostic reuse | Logger/helper and call site; ID source and propagation across applicable boundaries; allowed fields, level, cause/redaction policy and duplicate-log ownership |
| Observability reuse | Recorder/exporter and recording nodes; metric names, bounded labels, units and counting rules; current trace/sampling support; failure isolation and known delivery limits |
| Consumer behavior | Applicable UI translator, error/details/history components and recovery action; binding to the current task/item/attempt; public/internal disclosure boundary |
| Verification and lookup | Existing tests and runnable commands with cwd; what they assert and bypass; log/metric/trace query entry and required environment/access; applicable dashboard/alert source |

For each adopted pattern include a source path/symbol at the verified revision, its applicability limits, and the regression or evidence that supports it. Prefer links to maintained code/scripts; a minimal invocation example is useful only when its parameters and lifecycle placement are verified. Record the few choices an implementer must make: where to add a code, where to map it, which helper to call, what fields to supply and which checks to run. Avoid inventories of every metric or repeated source code.

Separate adopted conventions, observed inconsistencies and unverified candidates. Missing helpers, unsafe patterns, failing tests and unmerged fixes remain visible gaps with existing tracker/evidence references. Do not turn an incidental implementation or a known defect into policy, silently change public behavior, repair neighboring code, or introduce a framework during setup. Extend implementation scope only when already authorized.

## 3. Make the conventions reachable and verifiable

Put a short conditional pointer in the effective project context: when changing validation, error mapping, external calls, async state, retries, measurement or user-visible failures, read the project conventions and their relevant tests. Preserve the chosen instruction pack's source/revision. Verify every required companion is distributed and reachable in the target worktree; an absolute link into a temporary checkout is not a durable setup.

Use the native loading checks in [project context setup](project-context.md) for the startup paths the project actually uses. Distinguish observing the pointer in the loaded context from verifying that its target exists, and from proving an agent followed it. A renderer copying a rule file cannot infer the project's engineering choices; the analysis and adoption decision belong to the client running this Skill.

Within the existing authorization, run the smallest useful existing checks for an adopted pattern; otherwise record exact commands and why they remain unverified. Include a known error versus unknown-error control and the applicable context, retry/counting, telemetry-failure or UI-message assertions. A missing translation or a logger mock being called cannot establish an actionable user error or a usable observation path.

Report these results separately:

- **Source analysis:** candidate identity, actual call paths, adopted patterns, applicability and unresolved inconsistencies.
- **Context setup:** project-owned artifact, source revisions, effective pointer, distributed companions and direct/worktree/Botmux loading evidence as applicable.
- **Behavior evidence:** local output tests versus real collection/query and dashboard/alert checks; reuse existing evidence only with its version/environment limits. Setup completion does not imply production observability acceptance.

Refresh affected entries when error adapters, schemas, shared helpers, lifecycle/attempt semantics, locale mappings, exporters/queries or client/source revisions change. Preserve still-valid entries and existing evidence; repeat setup with unchanged facts should produce no duplicate documents or instruction sections. Link the project's integration guide to these checks rather than maintaining a second command list.
