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
