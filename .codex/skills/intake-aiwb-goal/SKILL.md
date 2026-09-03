---
name: intake-aiwb-goal
version: 1
description: Inspect one Agent Harness Contract draft and report approval or submission blockers. Advisory only.
---

# Intake AI Workbench Goal

Use this Skill only to inspect an existing Agent Harness Contract draft. Do not
replace planning, specification, TDD, architecture review, or small interactive
implementation.

## Inspect

Require a repository and one Contract draft. Prefer the shared MCP tool:

- call `aiwb_goal_intake` with `repository` and `contract_path`.

The equivalent local CLI commands are:

```bash
aiwb goal intake --repo /path/to/project --contract /path/to/contract.yaml
```

Pass the Contract to the shared interface. Do not reimplement schema validation,
readiness blockers, or approval digest generation in this Skill.

## Interpret

- `blocked`: report every blocker and the exact `next_action`; do not fill in
  acceptance, permissions, provider, resources, Harness, or environment
  decisions yourself.
- `ready_for_approval`: show the execution envelope and ask for one explicit
  human Contract approval.
- `ready_to_submit`: show the execution envelope and ask for explicit
  submission. Do not submit merely because intake is ready.

Keep the provider and model fixed. Never suggest production access, automatic
fallback, permission expansion, test weakening, or a replacement Run.

## Boundary

Intake is read-only. It must not approve a Contract, write files, execute
project commands, create a Run or worktree, start an Agent or Harness, or submit
work. Approval and submission are separate user actions.
