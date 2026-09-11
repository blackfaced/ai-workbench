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

## Returned result

- Stable remote candidate and return base; selected remaining patch/file checksums.
- Changed scope, tests/commands and exit outcomes, tested versions/environment, evidence references.
- Failed/unverified requirements, open conflicts, residual resources and active processes.
- Imported local branch/worktree and candidate; receipt identity/checksum result.
- Local divergence since request and its handling; integration target/status.
- Local checks actually rerun versus valid reused evidence; acceptance verdict and limits.
- Remaining publication or cleanup work; original artifacts retained until authorized cleanup.
