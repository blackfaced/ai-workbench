# Implement Batch

- Type: implementation workflow
- Domain: coding
- Status: experimental; first local trial targets Traex
- Source: [first-party Skill](../skills/implement-batch/SKILL.md)

Install from this checkout on the work Mac:

```sh
python3 tools/environment/env.py plan --profile work-mac --only implement-batch
python3 tools/environment/env.py apply --profile work-mac --only implement-batch
python3 tools/environment/env.py check --profile work-mac --only implement-batch
```

Use `work-linux` on the Linux machines; registration does not mean deployment there has occurred. The installed shared copy serves Codex and Trae discovery. Upstream `implement` is unchanged. Other clients and native subagent availability require independent verification.

In the target repository's Traex conversation, explicitly request:

> 使用 implement-batch skill 实施 spec 父 Issue #100。已有实现先验证；先展示依赖图、批次、实施与集成 agent 的模型让我确认。允许临时分支本地提交和集成，先不推送、不合 main、不关闭 Issue。

In Codex use `$implement-batch`. Exact child models depend on the client's exposed capability: the plan must distinguish verified model selection from unknown/inherited defaults. No silent substitution. Slash-command completion is client-specific. If an existing session cannot find the updated Skill, start a new session and invoke it again.

Before confirmation the parent performs read-only investigation and presents the graph, proposed batches, existing implementations, model/concurrency choices, checks, and authority. After confirmation each implementation child gets its own worktree; one integrator per batch reviews arrivals and integrates serially. Existing implementations go directly to verification. The parent accepts each batch before launching the next from the accepted integration tip, and finally verifies the whole spec.

For a first trial use a small parent with one existing implementation, two independent children, and a child blocked by both. Observe that execution waits for confirmation, finished work is verified rather than rewritten, siblings run in distinct worktrees, the dependent child waits for accepted integration, and batch-wide checks run once per unchanged candidate. A requested unavailable model must be surfaced before dispatch. Discovery/format checks do not prove these behaviors in Traex.

This Skill controls instructions and handoffs. Repository tests and CI provide executable gates; client capabilities provide isolation. It creates no daemon, queue, or additional Issue authority. The original upstream `implement` remains unchanged.

## Repository setup and final integration acceptance

Use `setup-aiwb` in a target repository to establish or refresh its integration-test guide. This is a Skill, not an `aiwb setup` shell command. It inspects existing scripts/deployment definitions, asks only for missing inputs, and records verified versus unverified setup paths. Typical guide locations follow the repository convention, otherwise `docs/testing/integration.md`.

> 使用 setup-aiwb skill 维护当前仓库的集成测试手册，先检查现有环境和命令，只询问缺失项。

`implement-batch` includes this setup when needed. After the execution plan is confirmed, it writes the spec cases before implementation (default `docs/testing/spec-<id>.md`), with parent-criterion coverage, preconditions, steps, expected results, evidence and cleanup. After all batches, a fresh executor using the confirmed low-cost model executes the cases and fills PASS / FAIL / BLOCKED / NOT_RUN, actual results and evidence. The parent owns case expectations and final acceptance. Failed cases route back to implementation and retain failure/retest history.

A frontend guide must verify its actual dev/test command and API routing; a Kubernetes/Helm backend guide must verify the mono-repo/chart entry, isolated test resources, candidate image, readiness and access route. Those examples are not preconfigured deployment instructions. Each repository owns its guide; cross-repository specs link them and identify every tested version.

Install/update both Skills together on this Mac with `python3 tools/environment/env.py apply --profile work-mac --only setup-aiwb --only implement-batch` (preview with `plan`). Linux profiles register the same resources; deployment there is separate. No real LAS deployment or billable API test is performed by installing these Skills.

## Recovery and verification cost

Keep worktrees, complete recovery patches/checkpoints and acceptance evidence in persistent project locations; temporary directories are for reproducible scratch/cache only. Handoffs identify the accepted tip, owned WIP, evidence and blocker resume conditions. Recheck these artifacts after interruption before reusing results.

Workers provide targeted feedback; the integrator owns batch-wide checks and consolidates required review axes; the parent assesses evidence. Reuse valid results for unchanged relevant code/environment instead of restarting the suite at every role boundary. Missing or stale reports, candidate changes affecting coverage and required repository gates justify reruns; record the reason.

For cross-system work, verify the smallest public contract needed by dependent implementation before the first affected batch, within confirmed authority. Complete pagination before inferring absence. This complements final E2E. When an external prerequisite blocks progress, retain checked sources and a concrete resume condition; do not repeat the same investigation without new evidence.
