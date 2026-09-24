# Botmux — optional session transport

Use this guide when botmux bot-to-bot execution is selected. The parent harness runs `implement-batch`; botmux carries dispatches, progress and results between harness sessions. Keep one coordinator and the existing Issue tracker, checkpoint and [run record](run-record.md). Botmux's separate workflow/orchestration Skills do not own this run; a chat progress board, if requested, only displays the existing state.

## Preflight and approval

Read the installed `botmux --version`, `dispatch --help` and `report --help`. From the intended parent bot conversation, use `botmux bots list` to check recipients and mentionability. Inspect existing configuration without exposing credentials; an online bot is not proof of peer delivery or permission. Record in the existing plan:

- Execution host/group, participating bots and their underlying harnesses; verified versus configured/unknown models and reasoning efforts. Bot names are not model identities. Verify that each harness can discover the required Skill and its references.
- Role-to-session assignments and concurrency, counting active sessions rather than bot accounts. Reuse bot identities with fresh sessions for new batches and independent reviewers/final acceptance; give reviewers candidate artifacts and constraints, not the worker's conversation.
- Absolute per-Issue worktrees and the integration worktree, reachable on the receiving host. A new topic isolates conversation, not files, ports or databases. Preserve the integrator's exclusive write ownership.
- The chosen group/audience, message/session creation and any peer conversation grants required by dispatch. These do not grant management commands, repository publication or additional execution permissions.

Check directory selection separately from message delivery. In the inspected 3.28.0 CLI, `dispatch --bot-app` establishes scoped peer conversation grants but does **not** support the `--repo` management command. Follow the installed help and an authorized directory-selection path; do not assume every dispatch mode accepts both flags. Before edits, each recipient must verify its actual directory, repository/base and applicable repository instructions against the assigned worktree. A mismatch stops that recipient, not unrelated approved work.

Include these choices in the Skill's existing execution-plan confirmation; there is no second approval ceremony for unchanged batches. Use that confirmation to authorize any first-use delivery probe. Unavailable routing, model or directory capabilities require an explicit alternative, not a silent fallback.

## Dispatch and return

Keep this identity block in the existing checkpoint and reference it from each brief; fill the recipient identity from actual delivery evidence before edits:

```text
Run / attempt:
Coordinator: bot identity + original parent session ID + parent topic root
Executor: bot identity + actual recipient session ID + assigned role
Return route: dispatch root + original parent session ID
Write owner (if authorized): session ID -> absolute worktree + branch/base; otherwise read-only
```

Bot names and topic IDs alone do not identify the authorized session. Each recipient checks its own identity and role against this block and verifies the worktree before writing. The recorded coordinator alone changes the plan or accepts results; another session of the same bot reports the mismatch through the verified route instead of acting as a replacement coordinator. Unknown identity or ownership blocks the affected assignment until reconciled. This is a handoff check, not a lock or a guarantee of botmux routing.

1. The parent records an attempt before dispatch and writes its brief in the project's persistent evidence location. Use the existing handoff fields: run/attempt and Issue scope, role, worktree/base, acceptance and permissions, targeted checks and return evidence. Only the parent coordinates the batch; recipients execute their assigned role rather than recursively running the whole batch workflow.
2. Use `botmux dispatch` to create a fresh child topic/session. Prefer the installed stable bot-identity option when its permissions and directory setup satisfy the plan. Save returned bot/session identifiers, parent and child topic roots, and dispatch identifiers in the existing checkpoint, associated with that attempt. Keep message-root IDs distinct from display thread IDs; use the identifier required by the receiving command, not a guessed conversation target.
3. Before sending follow-ups/repairs with `botmux dispatch --into <child-root> ...`, match that root to the current executor in the identity block. A retained root may resume a suspended, superseded writer; a known root is not proof of current ownership. An ordinary mention in the parent topic can create a different child session. Normal queued delivery is the default; interruption/steering requires an intentional decision within the approved plan, not a retry shortcut.
4. Recipients save their evidence and use `botmux report --content-file <persistent-report>` to return through the dispatch association. Use the exact `--dispatch-root` when provided and supported by the installed version. Check the selected route: a platform-Issue-bound session may instead update that Issue to `in_review`, requiring approved tracker-update authority; verify parent delivery separately. A report must reach and wake the original parent session; mentioning the parent inside the child topic can start a context-free session instead. If routing cannot be established, retain the report and surface the blocker rather than broadcasting it to another group/topic.
5. The parent matches the report to the recorded attempt and candidate, inspects the evidence, and proceeds through the existing review/integration/batch gates. A send acknowledgment, receipt, idle session, or `completed` status is not acceptance. Duplicate reports do not create new attempts or repeat integration; delayed reports from superseded attempts require reconciliation before use.

Reuse botmux's session status, chat history and report wake-ups for observability. End the current turn when waiting for peers; receive their reports in the same parent session. Follow the existing blocker policy for bounded checks instead of continuous polling or empty acknowledgment loops. Keep issue/candidate/test evidence in persistent project artifacts; chat cards are progress views, not the only record.

## Interrupted or uncertain delivery

A timeout does not prove dispatch failed. Check the identity block, recipient activity and current Git state before resending. Resume the recorded assignment when it still owns the worktree. Before replacement, verify that the previous writer and its write-producing child processes have stopped, preserve its work, and update the existing checkpoint to name the replacement and superseded session/root. Use only the replacement route thereafter; late messages from the superseded route require reconciliation, not automatic resumption. Stopping processes requires existing authority. If cessation or ownership is unknown, leave the affected assignment blocked rather than starting a competing writer.

After a parent restart or context loss, read the existing checkpoint and run record, reconcile botmux session/topic evidence with current Git state, then resume. Recover unfinished attempts before accepting new reports. Botmux process/session persistence does not by itself prove task recovery or restore missing test evidence.

## First-use acceptance

Within the approved pilot, demonstrate a small Issue's dispatch → verified worktree → implementation → independent review → serial integration → original-parent report. Then cover parallel worktrees, a blocked/misdirected recipient, a duplicate or late report, and an interrupted parent with an outstanding assignment. Check that unmet prerequisites stay blocked and only accepted integration releases the next batch. Record observed evidence in the existing acceptance document/run record; CLI help, successful installation and a simulated walkthrough do not establish this live behavior.

Sources: [multi-bot routing](https://deepcoldy.github.io/botmux/multi-bot), [session model](https://deepcoldy.github.io/botmux/session-model.html), [Skill + CLI interaction](https://deepcoldy.github.io/botmux/skill-cli.html). Command details were inspected on botmux 3.28.0; recheck the installed version rather than treating these notes as a compatibility guarantee.
