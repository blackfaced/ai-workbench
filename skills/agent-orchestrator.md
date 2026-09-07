# Agent Orchestrator Skill

- Type: skill
- Domain: coding
- Source: local
- Status: prototype
- Use when: submitting and observing an already-approved unattended development Contract through the AI Workbench daemon.

## Notes

The bundled interaction Skills are:

- [`run-approved-goal`](../tools/agent-orchestrator/skills/run-approved-goal/), which uses the local `ai-workbench` MCP server and does not own the Run lifecycle;
- [`setup-ai-workbench`](../tools/agent-orchestrator/skills/setup-ai-workbench/), which inspects first and requires explicit confirmation before project-local setup;
- [`ask-ai-workbench`](../tools/agent-orchestrator/skills/ask-ai-workbench/), which only recommends up to two optional Skills for a task;
- [`intake-aiwb-goal`](../tools/agent-orchestrator/skills/intake-aiwb-goal/), which inspects an existing Agent Harness Contract for approval and submission blockers;
- [`refresh-harness-recipes`](../tools/agent-orchestrator/skills/refresh-harness-recipes/), which audits or previews Recipe Catalog changes.

The four project-used interaction Skills (setup, ask, intake, and recipe refresh)
are mirrored under [`.codex/skills`](../.codex/skills/)
so a Codex Agent operating this repository can invoke them without a global
installation.
