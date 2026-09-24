# Implement Batch

- Type: implementation workflow
- Domain: coding
- Status: experimental; harness execution and recovery require live validation
- Source: [first-party Skill](../skills/implement-batch/SKILL.md)

## Install and invoke

Preview, apply and verify both Skills from this checkout:

```sh
python3 tools/environment/env.py plan --profile work-mac --only implement-batch --only setup-aiwb
python3 tools/environment/env.py apply --profile work-mac --only implement-batch --only setup-aiwb
python3 tools/environment/env.py check --profile work-mac --only implement-batch --only setup-aiwb
```

Use `work-linux` or `home-mac` for the corresponding machines. Installation/discovery does not prove task execution or deploy changes to other hosts. The shared copy serves configured clients; native agent/model support must be checked. An existing session may need to reload the Skill.

> 使用 implement-batch 实施这个 spec。先验证已有实现，展示依赖、首个可运行切片、master/worker/QA 分工、模型、返修预算和权限，统一确认后执行。QA 负责独立 review 和行为验收；需要架构或环境处理时再引入架构师/SRE。允许临时分支本地提交和集成，先不推送、不合 main、不关闭 Issue。

In Codex invoke `$implement-batch`. Upstream `implement` is unchanged.

## Development loop

The [Skill](../skills/implement-batch/SKILL.md#two-feedback-loops) owns the full procedure:

- Inner: master → worker → QA → master, with serial integration and bounded repairs.
- Outer: master → architect → inner loop → SRE → the same master, for planning, operating verification and the next decision. Roles are responsibilities, not mandatory extra bots.
- Start with a usable feedback path; iterate a small behavior slice; accept only with candidate-bound QA/check evidence. WIP previews can be useful before delivery passes. Simulated UI coverage and real integration remain distinct.

`setup-aiwb` maintains the target repository's runnable setup/smoke procedure. Frontends normally use local development; supported backends can use authorized incremental development-Pod updates. Project commands and evidence stay in the owning project, not in AIWB.

The master maintains one [run record](../skills/implement-batch/references/run-record.md), linked to [acceptance cases](../skills/implement-batch/references/spec-acceptance.md) and the recovery checkpoint. Preserve valid evidence across role handoffs; distinguish session completion from accepted work. No daemon, second tracker or automatic telemetry is introduced.

## Optional execution policies

- **Botmux:** explicitly select existing bots, then verify harness/model, dispatch return route and worktree ownership using [the transport guide](../skills/implement-batch/references/botmux.md). Installing botmux does not select this mode. Its first-use pilot must cover delivery and recovery; every dispatched role follows the completion-report contract.
- **Staged review:** explicitly select cheap-first/stronger-final review using [the policy](../skills/implement-batch/references/staged-review.md). Confirm actual models, risk routing and budget; ordinary QA remains the default. Initial approval does not release dependent work.

For a live trial, include a verify-existing child, independent slices and a dependent child. Observe unchanged-plan approval reuse, isolated writers, QA rejecting inadequate behavior evidence, accepted-integration dependency gates and recovery without duplicate writers. Installation tests and document walkthroughs do not prove those runtime behaviors.
