---
name: setup-ai-workbench
description: Inspect and explicitly configure AI Workbench for one repository. Use when the user asks to onboard a repository, discover optional Skills, or create a draft workflow policy.
---

# Setup AI Workbench

This is a lightweight, one-time repository onboarding Skill. It does not impose
a workflow and never changes files until the user explicitly confirms.

## Inspect first

Require a concrete repository path. Run:

```bash
aiwb setup --repo /path/to/repository
```

In this source checkout, when `aiwb` is not installed on `PATH`, use the
equivalent command from the repository root:

```bash
PYTHONPATH=tools/agent-orchestrator/src python3 -m aiwb setup \
  --repo /path/to/repository
```

Do not install or modify a global CLI configuration unless the user separately
asks for it.

Explain the returned workflow action, discovered optional Skills, and command
suggestions. The inspect command is read-only. Treat both Codex and Claude Code
as choices the user may select; do not edit global Agent configuration.

## Confirm before applying

If the user wants a project-local draft workflow, state exactly what will be
written and ask for explicit confirmation. Only then run:

```bash
aiwb setup --repo /path/to/repository --apply
```

To add reviewed project-local role guidance, include one or more explicit
paths, for example:

```bash
aiwb setup --repo /path/to/repository --apply \
  --role-skill implementer=.agents/skills/focused/SKILL.md
```

The selected Skill must already exist under the repository. Do not download,
run, link, or modify global Skills/configuration on the user's behalf.

To copy one bundled AI Workbench Skill into an explicitly selected
project-local Agent target, show the exact destination and require confirmation
before using `--apply`:

```bash
aiwb setup --repo /path/to/repository --agent-target codex \
  --install-skill ask-ai-workbench --apply
```

This writes only under the repository's `.codex/skills/` or `.claude/skills/`
directory. It never writes to user-global Agent configuration.

## Finish

The generated workflow remains a draft until the owner reviews and approves it.
Use `aiwb doctor` only to validate an appropriate reviewed configuration. Setup
does not submit Goals, start a daemon, weaken tests, or grant permissions.
