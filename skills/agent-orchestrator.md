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
- [`ask-ai-workbench`](../tools/agent-orchestrator/skills/ask-ai-workbench/), which only recommends up to two optional Skills for a task.
