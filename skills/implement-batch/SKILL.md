Implement a spec-level parent Issue through dependency-ordered batches. The parent agent coordinates and accepts the spec; each implementation agent owns one child Issue in its own worktree; one integration agent per batch reviews and integrates candidates serially. Explicit Issue lists and an approved spec without a parent Issue are also valid inputs. This Skill uses native client capabilities and Git, not a background scheduler or an enforcement service.

## Inspect and propose — read-only

Read the spec, child Issues, comments, blocking edges, repository rules, and relevant implementation/tests. Map every parent acceptance criterion to child work or final system-level verification. If decomposition is missing, use the installed `to-tickets` process when selected; otherwise propose small independently verifiable children. Publishing or changing Issues follows existing authorization and is separate from read-only planning.

Build a dependency graph with actual Issue identifiers. Surface cycles, missing/external blockers, ambiguous completion, and uncovered spec requirements. Never invent successful dependencies or silently expand the spec to fill gaps. Classify each child as needs implementation, existing implementation to verify, or blocked. Closed status, a PR link, or another agent's success claim is a lead to inspect, not proof.

Locate existing implementation at a concrete commit or working-tree patch and compare it with the intended integration baseline. Record whether it is already included, exists only on another branch, or is partial. Plan verification against existing behavior rather than rewriting it. A feature on another branch still needs authorized integration and verification there before it can satisfy dependent work.

Inspect the task-relevant environment before asking the user for setup information: repository setup instructions, required variable names, existing configuration, available credential providers, and target context. Use bounded read-only presence/status probes within existing authorization; report present, missing, or unverified separately. A configured key or endpoint is not proof of authentication or connectivity. Ask only for missing inputs or unresolved choices, grouped into one request with their purpose; prefer local environment/credential-provider setup rather than pasting secrets into chat. Keep secret values out of output, logs, patches, and agent handoffs; pass variable names and authorized retrieval methods instead. Deployment, write probes, and billable test calls belong in the execution plan, not this read-only inspection.

Inspect native subagent support, available concurrency, working-directory isolation, and model selection. List exact supported model identifiers/efforts for implementation and integration roles when inspectable. Otherwise mark them unverified, including any inherited default whose effective model is unknown. Never invent support or substitute a model silently. If a required capability is unavailable, propose an explicit alternative for confirmation.

## Confirm the execution plan

Before creating worktrees, dispatching execution/verification agents, running project checks, or editing implementation, show the user a compact plan containing:

- Parent scope and acceptance boundary; children classified as implement, verify-existing, or blocked.
- Dependency graph (Mermaid or an edge list), proposed batches, unresolved blockers, and overlap risks.
- Repository/base commit, spec integration branch, and per-Issue worktree strategy; disclose any required starting patch.
- Worker and integrator models/efforts, whether defaults are inherited or unverified, and maximum simultaneous workers. Count the parent if the client includes it in the limit; reserve capacity for the integrator and repository-required review agents.
- Per-Issue targeted checks, batch-end build/full checks, final spec acceptance, and test seams already agreed.
- Environment readiness: verified prerequisites, missing inputs, unverified access, and the authorized way workers will obtain configuration; include no secret values.
- Authority for temporary local commits and integration, target-branch merge, push, Issue updates/closure, external effects, and cleanup. Distinguish retained prior authorization from newly requested authority.

Ask the user to confirm this concrete plan and wait. A generic request to implement the spec is not confirmation of an unseen plan. Reuse an earlier explicit confirmation only when it covers this same plan. Confirmation authorizes only the actions actually presented; leave ungranted publication or cleanup authority absent. No response is not approval.

After confirmation, execute unchanged batches without repeated approval. Material changes to scope, dependency structure, model choice, permissions, or verification guarantees require confirmation of the changed part. Continue only independent work covered by the existing plan while waiting.

## Execute the dependency frontier

Use one spec integration branch throughout. Each batch selects children whose prerequisites are accepted on that branch. Limit the batch by confirmed concurrency and overlapping edits; keep high-risk shared changes separate when practical. A completed worker does not release dependencies. Start the next batch only after the current batch's integration checks pass and the parent accepts it.

Create fresh implementation agents/worktrees for new batches, all based on the same accepted integration commit. The first baseline is the confirmed starting state. Preserve unrelated user changes; carry only an explicitly selected starting patch if needed and record it. Never silently stash or commit the user's checkout. Confirm each agent's actual working directory before edits.

Give each worker its Issue, relevant parent constraints, acceptance criteria, scope/non-goals, dependency evidence, absolute worktree and base, chosen model, existing permissions, and targeted checks. Use compact fresh context rather than the whole conversation when supported. Worktrees share ports, databases, credentials, and other machine resources: preserve the confirmed external-effect boundary.

For verify-existing children, assign verification directly to the integrator; create no implementation agent merely to redo finished work. For code on another branch, the integrator extracts and reviews only the Issue-relevant candidate against its source base, then applies it within confirmed authority and verifies the affected behavior on the integration tip. Read existing code and run targeted acceptance/regression checks. If complete and present on the integration baseline, record verified evidence and release dependencies only at the batch boundary. If partial or failing, report the specific gap and assign a bounded repair to an implementation agent under the confirmed scope/model; material scope changes return to confirmation. Inability to run verification means blocked/unverified, not missing implementation or success. If every child already exists, perform verification and parent acceptance without manufacturing code changes.

Workers run relevant tests/types during implementation. Bug fixes first demonstrate a regression check that catches the defect. If upstream `tdd` is selected, follow its red-before-green and agreed-seam requirements; otherwise follow the repository's testing method. Reuse approved seams rather than asking per Issue. Return exact candidate identity/diff (including untracked files), acceptance results, commands/results, and remaining concerns. Do not invoke upstream `implement`, which owns a conflicting review/commit sequence.

## Serial integration and batch verification

The integrator is the sole writer to the spec integration worktree. Receive candidates as they finish; review each against its Issue and parent constraints for correctness, standards, and necessity. Follow repository-required independent review axes; use available review agents sequentially if capacity is limited and the policy permits it. An implementation worker's self-review is not independent acceptance.

Review the complete candidate against its recorded base, including any uncommitted/untracked changes. If a selected review Skill defaults to committed HEAD, provide the actual working-tree patch instead; never create a commit just to hide an authorization gap. Compare a candidate with the current integration tip before applying it: earlier accepted candidates may change its compatibility.

Integrate reviewed candidates serially within the confirmed local authority, checking affected interactions after each integration. Keep earlier accepted changes intact; a stale candidate is not permission to overwrite the integration branch. Send semantic conflicts and substantive repairs back to the responsible worker, then review the corrected candidate. The worker reconciles its owned branch with the latest integration tip without rewriting others’ branches, and returns the new base plus only the remaining Issue changes so already-integrated work is not replayed. Repeated failure without new evidence calls for diagnosis/replanning rather than indefinite retries. Other independent work in the approved batch may continue while an Issue is blocked; do not accept the batch until unresolved work is addressed or the user confirms a revised plan.

Run the agreed build/full checks once at batch end on the final integration state, plus mandatory per-change gates when the repository requires them. Per-Issue targeted checks remain early feedback. Additional complexity/coverage/mutation tools are risk-based, not universal thresholds. Review changes to tests and gate settings rather than treating a weaker check as a fix.

Evidence names the tested commit or complete patch, commands/results, and relevant environment. Reuse it only while relevant code, configuration, dependencies, and environment remain unchanged. Subsequent repairs require affected checks again; avoid rerunning identical checks solely because another agent takes over.

The integrator reports per-Issue results, integration tip, findings and checks. The parent inspects this evidence and accepts the batch; then starts a fresh batch of workers and a fresh integrator using a compact handoff of the accepted tip, verified prerequisites, remaining graph, and unresolved constraints. Batch grouping is execution bookkeeping, not a second Issue tracker.

## Accept the spec

After all children are verified and integrated, evaluate every parent acceptance criterion, including end-to-end behavior crossing child boundaries and requirements missed in decomposition. Reuse the last batch's checks if they cover the same final state; run remaining spec-level checks. All children closed or individually passing does not establish parent acceptance.

Report the spec verdict, each child's implemented/verified/blocked outcome, final integration identity, checks actually run, and remaining publication steps. Distinguish accepted integration branch from merged target branch, pushed changes, and closed Issues. Keep worktrees until changes are safely retained and cleanup is authorized. Missing required evidence leaves acceptance incomplete.
