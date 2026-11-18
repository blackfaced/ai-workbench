# Handoff <unique ID>

Keep in the project's approved artifact location. References and sanitized evidence only; never embed secrets. This record identifies a transfer, not a replacement task tracker. The receiving worker returns the result section or links a separate result artifact.

## Request snapshot

- Task/spec/Issue and acceptance boundary; next action and non-goals.
- Source host/repository/worktree/branch; base commit and candidate commits.
- Selected working-tree delta: staged/unstaged if relevant, binary changes, deleted and necessary untracked files; explicit path list and checksums.
- Stable snapshot time/identity; required starting inputs excluded and why.
- Source owner state: paused, continuing separate work, not running, or still editing this task after the captured snapshot. Record the active owner, snapshot boundary and ownership-transfer condition; prepare-only receipt does not transfer execution ownership.
- Destination host/repository/worktree and verified base availability.
- Transfer artifacts/method/checksums; receipt/reconstruction checks.
- Environment/test guide and credential-variable/retrieval references (not values).
- Existing verification evidence with tested candidate and environment.
- Granted scope: prepare/launch, model/permissions, commands, external effects, local commits/integration, publication and cleanup.
- Launch: prepared/not started/started/unverified; actual session/job ID if available.
- Artifact location/retention and exact resume instruction.

## Botmux topic

1. Copy the handoff record to the destination's approved location and verify its absolute path. In the chosen Feishu group, use the @ picker to select the destination bot and start a native topic with this top-level message. Substitute the verified worktree and record paths.

   ```text
   /t /repo "<absolute-destination-repo>"
   读取「<absolute-handoff-record>」，核对当前工作目录与任务单一致后回复「已就绪」。保留这条任务单路径，等我在本话题 @ 你说「继续」后再执行。完成后用继续这一轮的最终回复交还，写明候选提交、记忆记录 ID（如有）和验证结果。
   ```

2. Verify `botmux observe` matches the bot, original message root, thread scope, and actual working directory. After the bot replies ready, pause the source writer. In that topic, select the same bot with the @ picker and send `继续`. The worker reopens the record from the opening turn's path, checks the worktree, and works within the recorded scope. If the path or directory cannot be verified, the worker reports it in the same topic and stops.
3. The worker returns its receipt as the **final response to that Feishu turn**. Botmux routes it to that turn's topic. Confirm the receipt is visible there and the worker's turn is idle with an empty queue before taking back execution. If delivery is missing, check the turn's result and delivery status before retrying.

## Returned result

- Stable remote candidate and return base; selected remaining patch/file checksums.
- Changed scope, tests/commands and exit outcomes, tested versions/environment, evidence references.
- Failed/unverified requirements, open conflicts, residual resources and active processes.
- Imported local branch/worktree and candidate; receipt identity/checksum result.
- Local divergence since request and its handling; integration target/status.
- Local checks actually rerun versus valid reused evidence; acceptance verdict and limits.
- Remaining publication or cleanup work; original artifacts retained until authorized cleanup.
