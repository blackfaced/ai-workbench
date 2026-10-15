# Skills

Agent skills and reusable instruction packs.

Skills are lightweight and opt-in: use one only when the owner requests it or a
narrow task clearly needs it. They are suggestions, not a mandatory workflow
framework.

## Installation policy

Default to **project-scoped activation**, not installation into every client's user-global discovery directory. AIWB maintains reusable first-party content, templates and source records; the user's workspace manager selects projects, clients and fixed revisions, and owns activation, updates and rollback. Upstream content keeps its original owner. Do not create a second maintained body or a second activation manager here.

For each selected Skill, hand off its source repository, full commit SHA (or an immutable release plus content digest), source path, required companions/resources, license and verification limits. `sources.lock.json` includes historical installation observations and unpinned entries; it is not a ready-to-apply project manifest. Resolve unpinned sources before activation, without relabeling old evidence as current verification.

First-party packages may separate `SKILL.md` body from `clients/<client>.frontmatter.md`. The downstream manager must assemble the selected metadata plus body, preserve relative references and declared resources, and carry client-specific policy files from the same revision. Do not simply link a body-only directory as a complete client package. Read the corresponding component in `tools/environment/profiles/*.json` for resources and `install_with` companions; those profiles describe the legacy installer, not a project's activation scope.

Activate one canonical package through the target client's verified project discovery entry. Select actual repository roots, not a common parent directory; verify new sessions and new worktrees separately. Preserve project rules, reject unmanaged same-name conflicts, and record source/digest, targets, backups and rollback with the existing workspace manager. A link on disk does not prove client discovery or behavior acceptance. Official self-managed or project-entry-less clients remain explicit exceptions, not a reason to activate all Skills globally.

Existing user-global installations stay unchanged until a separately authorized migration has verified project discovery and protected user edits. The [environment tool](../tools/environment/README.md#skill-installation-scope) still supports legacy profile-selected installs; this policy does not change its executable defaults or retire its recovery support.

## Index

- [单 Issue 轻量试用](../workflows/single-issue-trial.md) — 装好后做一个小 Issue，复用项目流程并区分试用与验收。

- [reflect-bug](reflect-bug/SKILL.md) — 分析漏测原因并记录有证据、有适用边界的项目经验教训.
- [review-lessons](review-lessons/SKILL.md) — 核对项目经验的有效性，合并重复项并保留历史证据与来源.
- [handoff-to-dev](handoff-to-dev/SKILL.md) — 核对工作快照与目标环境，把当前任务安全交接到指定开发机.
- [collect-from-dev](collect-from-dev/SKILL.md) — 核对远端候选与测试证据，在独立本地工作树取回开发结果.


- [setup-aiwb](setup-aiwb/SKILL.md) — configure and verify project context for clients and worktrees; derive project error/observability conventions and maintain integration-test guides, including deliver-spec's existing setup path.

- [deliver-spec](deliver-spec/SKILL.md) — plan, implement, review and verify a spec; see its [project activation and usage guide](../workflows/implement-batch.md).
- [test-design](test-design/SKILL.md) — 独立测试设计与质量审查；从需求、旧合同和真实入口补齐断言、数据与证据边界。
- [self-test-report](self-test-report/SKILL.md) — 自测报告编写、更新与证据审查；独立使用或由 deliver-spec 引用，复用同一验收记录。
- [writing-docs](writing-docs/SKILL.md) — 技术文档写作与增量编辑；专用 Skill 复用结构保留、语言与改后核验约定，引用上游 `writing-for-agents`。

- [steelman-grill](steelman-grill/SKILL.md) — managed first-party Skill; requires upstream `grilling`.
- [viral-clip-doctrine](viral-clip-doctrine/SKILL.md) — 抖音投流爆款剪辑的方案层管线（钩子—气口—指派—收敛—包装—合规），不预设执行工具。
- [Source records](sources.lock.json) — includes explicitly unverified upstream entries; not a complete dependency lock.
- [Archify](archify.md) — upstream-owned typed, explorable diagrams; existing local installation.
- [Diagram Design](diagram-design.md) — opt-in trial for additional diagram types and document figures.
- [Anthropic Skills](anthropic-skills.md)
- [mattpocock/skills](matt-pocock-skills.md)
- [Anatomy](anatomy.md) — upstream open skill; explorable 3D cutaway models and narrated explainers; installed to DoubaoWork, discovery pending.

## Distributable instruction packs

- [Engineering principles](engineering-principles/README.md) — canonical generic rules consumed at a fixed commit by downstream; not an automatically invoked Skill.
