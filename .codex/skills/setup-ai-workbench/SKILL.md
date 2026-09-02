---
name: setup-ai-workbench
version: 1
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

For a reviewable Python L0 Project Profile and Harness Plan, use:

```bash
aiwb setup --repo /path/to/repository --planning-mode python-l0
```

This planning path discovers Python targets, purpose tags, existing engineering
tools, pipeline files, bounded local Git history, fallback code structure, and
missing L0 capabilities. It does not execute project commands, query remote
review history, persist a code graph, create a worktree, or modify the target
repository. The equivalent MCP tool is `aiwb_harness_plan`; it always returns
an unapproved Plan.

After reviewing every command candidate, coverage decision, owner decision, and
non-goal, record explicit Plan Approval outside the target repository:

```bash
aiwb setup --repo /path/to/repository --planning-mode python-l0 \
  --approve-plan --approved-by owner \
  --plan-artifact /path/outside/repository/approved-plan.json
```

Plan Approval is durable planning state only. It does not authorize Apply,
execute probes, or create a Candidate.

## Apply an approved Python L0 Plan

Apply requires a second exact approval. Use the approved Plan artifact, a full
base commit SHA, an external state directory, and explicit `--apply-command`
selections. Run `--preview-apply`, review every file digest, dependency,
canonical command, side effect, branch, and worktree, then record
`--approve-apply` to an external `--apply-artifact`. Execute only with
`--execute-apply` and the unchanged arguments.

Do not substitute Plan Approval for Apply Approval. Do not select `adopt` or
`migrate_later` commands before the owner approves their dependencies and
migration. Apply writes only an isolated candidate worktree, never the primary
working tree or target branch. Preserve a failed candidate and its report for
review. `configured_local` is not pipeline verification.

## Verify the exact candidate commit

Once an approved repository flow publishes the configured candidate, use
`aiwb pipeline verify` with the candidate report, GitHub owner/repository,
the approved Harness workflow name, required check names, required artifact
names, and an external state directory. AI Workbench resolves `gh` from `PATH`;
`AIWB_GH_BIN` is an explicit override, not a required setup step.
This is read-only against GitHub. Do not dispatch a workflow, inspect secret
values, change required checks, or accept a green result for another commit.
Report `pipeline_pending`, `verification_failed`, or `verified` exactly as
returned, preserving first failures and explicit retries.

## Confirm before applying

If the user wants a project-local draft workflow, state exactly what will be
written and ask for explicit confirmation. Only then run:

```bash
aiwb setup --repo /path/to/repository --apply
```

To install an explicitly selected bundled or repository-local Harness Extension,
include its Skill name and exact Agent target, for example:

```bash
aiwb setup --repo /path/to/repository --agent-target codex --apply \
  --install-skill ask-ai-workbench
```

Resolve and display the selected Extension before applying it. Do not download,
run, link, or modify global Skills/configuration on the user's behalf.

This writes only under the repository's `.codex/skills/` or `.claude/skills/`
directory. It never writes to user-global Agent configuration.

For an MCP, plugin, hook, or command, select one repository-local descriptor
and its exact Agent target:

```bash
aiwb setup --repo /path/to/repository --agent-target codex --apply \
  --install-extension /path/to/repository/extensions/focused-mcp.yaml
```

The descriptor must name a repository-local executable and an exact native
Harness load/health command under `configuration.harness_probe`. Setup runs the
command without a shell and with a bounded timeout. Apply succeeds only after
that probe confirms the selected Harness can load the Extension; if the probe
is unavailable or rejects it, Setup fails before writing. Do not treat
descriptor metadata or an executable bit alone as proof of availability.

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

The resulting daily flow has two phases:

1. use the installed Matt router and upstream Skills for normal interactive
   engineering;
2. at accepted tickets or a Contract draft, invoke `$intake-aiwb-goal` to
   inspect the cheapest viable path and readiness before any approval or
   submission.

Setup does not create a second specification, ticket, TDD, review, or
implementation workflow.
