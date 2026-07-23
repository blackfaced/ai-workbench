---
name: ask-ai-workbench
description: Recommend up to two optional AI Workbench Skills for a task without taking action. Use when the user asks which optional Skill or flow may help.
---

# Ask AI Workbench

Given a concrete repository path and task description, run:

```bash
aiwb skills ask --repo /path/to/repository --task "describe the task"
```

Return the recommendations and their short match reasons. Recommending no Skill
is a normal result.

This is advisory only. Do not invoke any recommended Skill, submit a Goal,
write files, install anything, start a daemon, change permissions, or expand
the task scope unless the user separately asks for that action.
