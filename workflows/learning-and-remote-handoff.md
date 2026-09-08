# Project learning and remote handoff

- Domain: coding, ops
- Status: experimental; instruction/installation validation is separate from real task acceptance.

| Skill | Input | Output |
| --- | --- | --- |
| [reflect-bug](../skills/reflect-bug/SKILL.md) | Escaped bug, version, originating requirement and evidence | Project lesson explaining the detection gap and a concrete prevention |
| [review-lessons](../skills/review-lessons/SKILL.md) | Selected project's existing lesson records | Consolidated active index, canonical records and traceable retired advice |
| [handoff-to-dev](../skills/handoff-to-dev/SKILL.md) | Current task and explicit destination | Verified source snapshot, destination worktree, handoff record and truthful launch status |
| [collect-from-dev](../skills/collect-from-dev/SKILL.md) | Handoff record and remote candidate | Isolated local candidate, verification evidence and integration status |

In Traex, say `使用 reflect-bug skill 反思这个漏测 bug：<report>` or `使用 review-lessons skill 整理当前项目的经验记录`. In Codex use `$reflect-bug` / `$review-lessons`. Reflection records facts and proposed prevention; it does not automatically modify production code or global instructions. `implement-batch` consults relevant project lessons during investigation and case design.

For transfer, say `使用 handoff-to-dev skill 把当前任务交到 <host> 的 <repo>，只准备，不启动` or explicitly authorize starting the confirmed remote client. To return, say `使用 collect-from-dev skill 取回 <handoff record> 的结果，先不合并`. Host names, accounts, models and repository paths come from the target project/user and live inspection, never from generic Skill defaults.

One lesson format and one handoff/result format support each pair. They live with their producing Skill's references; install both members of a pair when using the complete flow. Concrete incidents, secrets, project deployment commands and working patches never become AIWB's knowledge base. No assistant-global memory writes are performed by these Skills.

Install on the work Mac through the existing environment entry point, using `plan` before `apply`:

```sh
python3 tools/environment/env.py apply --profile work-mac --only reflect-bug --only review-lessons --only handoff-to-dev --only collect-from-dev --only implement-batch
```

Use `work-linux` when actually installing on Linux. Registration is not deployment. An installed handoff Skill does not mean a remote session was transferred or launched. Preserve source/local/remote work until the user's existing cleanup authority covers deletion.
