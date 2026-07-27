---
name: intake-aiwb-goal
description: Inspect ticket or draft handoff readiness and the cheapest viable path, choosing the interactive Matt flow or an AI Workbench unattended Run. Advisory only.
---

# Intake AI Workbench Goal

Use this Skill only at the handoff from accepted tickets or a draft Contract.
Do not replace `$ask-matt`, grilling, specification, ticket decomposition, TDD,
architecture review, or small interactive implementation.

## Inspect

Require a repository plus exactly one accepted tickets file or Contract draft.
Prefer the shared MCP tool:

- call `aiwb_goal_intake` with `repository` and either `tickets_path` or
  `contract_path`;
- optionally include a short task statement when durability or overnight intent
  is not visible in the artifact.

The equivalent local CLI commands are:

```bash
aiwb goal intake --repo /path/to/project --tickets /path/to/tickets.md
aiwb goal intake --repo /path/to/project --contract /path/to/contract.yaml
```

## Interpret

- `interactive` / `interactive_matt`: use the installed `$ask-matt` router, or
  set up the reviewed Matt engineering profile if it is unavailable.
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
