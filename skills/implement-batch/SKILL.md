Deliver a spec through small, verifiable slices using the selected harness and Git. Accept a parent Issue, explicit Issue list, or approved spec. Verify existing implementations before writing replacements. This Skill defines handoffs and acceptance, not a scheduler, lock service, or second Issue tracker.

## Two feedback loops

- **Inner: master → worker → QA → master.** The worker implements a slice; independent QA reviews the change and exercises its behavior; the master routes repairs or accepts verified integration.
- **Outer: master → architect → inner loop → SRE → master (PDCA).** Plan the approach, build and check slices, verify the applicable operating environment, then use the evidence to close the task or plan the next bounded iteration. The last master is the same coordinator, not another competing session.

These are responsibilities, not a requirement to launch five bots. The master can handle straightforward design; bring in an architect for unresolved cross-layer decisions or repeated failures needing a new approach. SRE owns applicable startup, deployment, readiness, access and recovery checks, not business acceptance. Involve SRE early when the environment blocks implementation; local-only work need not gain a deployment stage. Mark inapplicable responsibilities explicitly.

QA owns independent correctness, standards and necessity review plus behavior acceptance. For application work, use the testing/QA role to lead this review; it may request bounded specialist review when needed. A worker's self-review is not QA. One designated integrator alone writes the integration worktree and runs batch checks; the master may fill this role. Keep QA read-only on implementation. An explicit role/ownership handoff is required before a former reviewer makes integration writes.

## Inspect and propose — read-only

Read the spec, comments, dependencies, repository rules and relevant code/tests. Map every parent criterion to child work or final verification. Classify children as **implement**, **verify-existing**, or **blocked**; inspect existing candidates at a concrete commit/patch and determine whether they are on the integration baseline. Closed Issues and agent reports are leads, not proof. If decomposition is missing, use selected `to-tickets` or propose independently verifiable children; publishing Issues needs authorization.

Plan an early **tracer bullet** when a cross-layer or external assumption is uncertain: one real entrypoint, observable result and explicit dependency boundary. Prefer slices by user behavior over technical layers. Gate dependent expansion on accepted slice evidence; independent work may continue. Reuse existing valid evidence; simple local edits need no artificial slice. A mocked path cannot release work that depends on the real integration it bypasses.

Inspect repository setup scripts, integration guides, configuration names and credential-provider status without exposing values. Separate configured, reachable and behaviorally verified. Missing/stale test instructions route to installed `setup-aiwb` (source: `skills/setup-aiwb/SKILL.md`); include its work in the plan. Retrieve only relevant project lessons, checking their applicability against the current spec. Keep business facts and records with their owning project.

Inspect harness session isolation, concurrency and model/effort selection for each chosen role. Record exact supported identifiers or `unverified`, including unknown inherited defaults; bot names are not model identities. Required unavailable capabilities need a confirmed alternative, not silent substitution.

- **Botmux selected:** read [botmux transport](references/botmux.md) before planning or dispatch. Every dispatched role, including QA, keeper and reviewer, must read its [completion-report contract](references/botmux.md#completion-report-contract); reference it in role instructions and supply the actual dispatch root. Otherwise use native harness agents. Installation alone does not select botmux.
- **Staged review selected:** read [staged review](references/staged-review.md) before proposing stages/models. Otherwise use ordinary QA review; existing confirmed runs keep their policy.

Surface cycles, missing dependencies, overlapping writes and unclear acceptance. Group missing inputs into one request. For blockers, record checked sources and a concrete resume condition; stop equivalent searches or unchanged-status polling once evidence is exhausted.

## Confirm once, within a clear boundary

Before creating worktrees, dispatching agents, running project checks or editing artifacts, present one compact plan:

- Scope, criterion coverage, non-goals, existing implementations, dependency edges and batches; first slice and dependent work.
- Repository/base, selected starting patch, integration branch, persistent worktrees, evidence/checkpoint locations and write owners.
- Master/worker/QA/integrator assignments, applicable architect/SRE work, exact models/efforts or uncertainty, final fresh QA executor and concurrency. Reserve capacity for required review.
- Targeted checks, batch/final gates, integration-guide and case-document locations; real versus simulated dependencies, service owner/access/review window, missing prerequisites.
- Review/repair policy and bounded budget: rounds, elapsed time or reliably measurable cost, with escalation conditions. Do not use an unmeasurable cost limit as the only bound.
- Authority for local commits/integration, push/MR/merge, Issue updates, installs, deployment, test-data writes, billable calls and cleanup; distinguish retained authority from new requests.

Reuse explicit confirmation covering this same plan. Otherwise ask once and wait; a generic implementation request or silence does not approve an unseen plan. Within that boundary, role handoffs, QA findings and repairs consume the approved budget without another approval ritual. Material scope, dependency, model, permission or verification changes require confirmation of the changed part. Exhausted budget stops affected work; spawning a new session does not reset it. Continue independent authorized work while waiting.

## Prepare the feedback path

After confirmation, use `setup-aiwb` where needed and write [spec acceptance cases](references/spec-acceptance.md). The master owns expected outcomes; QA checks coverage and proposes missing assertions before dependent implementation. Ambiguous requirements return to the master. Start cases at NOT_RUN; preserve failures and invalidate affected evidence when approved requirements change.

For application work, validate the chosen worktree's startup, health, browser/API access and usable test-data path before expanding implementation. Exercise an existing baseline behavior if the new one does not exist yet. Verify the smallest authorized public contract needed by cross-system work, including identifiers, response shape and pagination; configuration presence is insufficient. Prefer sanitized known-good fixtures over guessed positive inputs. Billable/write probes require the plan's authority.

Keep gate timing explicit:

| Point | Required result |
| --- | --- |
| Start dependent work | A usable feedback path, or an explicitly approved narrower verification boundary; missing authority/environment blocks only dependent work. |
| Iterate a slice | Red tests, incomplete code and reproducible failures guide repair. They are not themselves external blockers. A failed or unverified slice does not release dependent expansion. |
| Accept delivery | Independent QA, required build/checks and acceptance evidence cover the identified candidate. Unrun checks, test names and a Ready log are not PASS. |

A development preview may be shared before build/QA passes when access is authorized: label it **WIP**, identify the candidate, known failures and unverified boundaries. Preview access is feedback, not acceptance, and does not waive repository commit/build gates. Keep the agreed service available during the review window, including useful failing states unless unsafe or authorized cleanup requires stopping; follow `setup-aiwb` for ownership and version updates. Human feedback is optional unless selected in the plan; waiting for it is NOT_RUN, not PASS.

## Run the inner loop

1. **Master dispatches.** Choose children whose prerequisites are accepted on the integration branch. Give each implementation worker its own persistent worktree based on the accepted tip, Issue/slice, constraints, checks, model, permissions and return route. Verify its actual directory/base before edits. Preserve unrelated user changes; carry only the approved starting patch. Worktrees still share ports, data and credentials. Verify-existing work goes directly to QA/integrator, without manufacturing implementation. For partial work, assign only the evidenced gap.
2. **Worker implements and demonstrates.** Use the repository's test method; bugs need a regression that catches the defect, and selected `tdd` keeps its red-before-green contract. For application changes, demonstrate the first usable slice through browser/API actions or the explicitly selected human check before expanding dependent features. Keep mocks and real dependencies explicit. Return the exact base/candidate or complete patch (including relevant untracked files), commands/results and remaining concerns. Do not invoke upstream `implement`, which owns a conflicting workflow.
3. **QA reviews and exercises.** Inspect the complete candidate, affected callers and test assertions against the spec for correctness, standards and necessity. Run/reuse applicable behavior evidence, not just worker summaries. For UI changes, check the actual interaction and relevant loading/error/recovery/edit-conflict states; a screenshot or unrelated assertion cannot stand in for them. If a review Skill defaults to committed HEAD, supply the actual patch. Return reproducible findings and case results; do not repair implementation, rewrite expectations or weaken gates.
4. **Master routes feedback.** Send confirmed defects to the owning worker within the budget, then have QA check repairs and affected behavior. Preserve disputed findings with evidence and decision. Repeated failures without new evidence return to diagnosis/architect input in the outer loop, not endless reviewer resets. A QA session ending means a verdict arrived, not that the task passed.
5. **Integrator verifies the combined candidate.** Review compatibility against the current integration tip and integrate serially within authority. Send semantic conflicts/substantive repairs to workers, who reconcile their branches and return a new base plus remaining changes. Preserve accepted work. Run agreed full checks at batch end and mandatory per-change gates. The master accepts the batch only after applicable QA verdicts and checks pass; then fresh workers/QA use the accepted tip for the next batch.

In staged mode, initial approval permits only provisional integration; required stronger review must pass before batch acceptance. For code that already exists elsewhere, review the Issue-relevant change, integrate within authority and verify it on the integration tip before releasing dependencies.

## Close the outer loop

After inner batches pass, SRE verifies applicable operating conditions on the identified candidate: startup/deployment, readiness/access, relevant logs and agreed recovery/cleanup. Use existing project commands and authorized local or development targets; no production deployment is implied. No separate SRE session is needed for an already verified local-only path. Environment failures return to SRE, code defects to worker/QA, design conflicts to architect/master; keep the same evidence trail.

Dispatch a fresh QA acceptance executor with the confirmed model, case document, guides, final identities and test/cleanup authority. Choose for the needed browser/API/review capability, not price alone. The executor records every case as PASS, FAIL, BLOCKED or NOT_RUN with observations and evidence, changing result records only. Stop affected cases on ambiguous expectations, unsafe side effects or missing prerequisites; independent cases may continue. Repairs return through worker → QA → serial integration; rerun affected acceptance against the resulting candidate.

The master compares the final evidence with the whole spec, including cross-Issue behavior and real versus simulated coverage. Then close within publication authority, or name the bounded next iteration, owner and resume condition. Record reusable lessons in the project's existing location; a lesson does not silently change active scope or authorization. A new task, deployment or recurring monitor requires its own authority. Report accepted versus merged/pushed/closed separately, and retain worktrees until changes are safely preserved and cleanup is authorized.

## Evidence, progress and recovery

Initialize the [run record](references/run-record.md) before dispatch; the master is its sole writer. Agents return attempt facts with normal handoffs. Keep case outcomes in the acceptance document, attempt/finding history in the run record and recovery pointers in the existing checkpoint. Issue state remains in the tracker; do not copy project records into AIWB.

Evidence identifies the commit or complete patch, command/exit status, executed behavior/tests, environment and sanitized artifact. Reuse it only when relevant code, configuration, dependencies, expectations and environment remain unchanged; cite origin and applicability. Candidate changes, unreliable/missing evidence or mandatory repository gates trigger affected reruns. A role change alone is not a reason to repeat the suite. Transfer check ownership before another process writes the same outputs.

Progress handoffs expose the current slice, responsible session, last observed activity/evidence and time, candidate/preview identity, blocker and next action. Separate **session ended**, **QA failed**, **waiting for input** and **accepted**; unknown/stale activity stays unknown. Use harness status/events/report wake-ups for updates; notify on actionable change, not repetitive acknowledgments. This Skill does not provide automatic telemetry or background monitoring.

At handoffs/interruption, checkpoint accepted prerequisites, current Git state, write ownership, WIP/evidence paths and resume conditions. Preserve selected unfinished changes via authorized commits or complete patches, including needed untracked/binary files but never credentials. Keep recoverable work in persistent project locations, not disposable scratch directories. After restart, reconcile artifacts, live sessions and Git before resuming; missing artifacts invalidate claims. Stop a previous writer and its write-producing children within authority before transferring ownership. Unknown ownership blocks replacement, not permission for a competing writer.
