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

Explain the returned workflow action, discovered optional Skills, command
suggestions, and optional Skill packs. The inspect command is read-only. Treat
both Codex and Claude Code as choices the user may select; do not edit global
Agent configuration.

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

## Optional packs

Offer packs only after inspection and only by explicit user choice. `matt` is
an installable, project-local pack pinned to a reviewed public release;
`anthropic` is reference-only and must not be installed. Ask the user to choose
either a reviewed Matt profile or specific Skills, rather than installing the
collection wholesale. Show the source, revision, target Agent, selected profile
or Skill names, and resulting project paths before applying.

For a reviewed, complete engineering flow after confirmation:

```bash
aiwb setup --repo /path/to/repository --agent-target codex \
  --install-pack matt \
  --pack-profile matt=engineering \
  --apply
```

The `engineering` profile is the reviewed dependency closure of upstream
`ask-matt`, rather than the entire upstream collection. The installer writes
only project-local Agent Skill directories plus its project lock file. Do not
pass global, bypass, or all-Skills options. After a Matt install, tell the user
to invoke `$setup-matt-pocock-skills`; do not run that interactive
configuration Skill automatically.

## Finish

The generated workflow remains a draft until the owner reviews and approves it.
Use `aiwb doctor` only to validate an appropriate reviewed configuration. Setup
does not submit Goals, start a daemon, weaken tests, or grant permissions.
