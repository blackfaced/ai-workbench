# AI Workbench

Personal workbench for AI-assisted development, research, reusable knowledge, and repeatable agent workflows.

This repository is a workbench, not a public skill registry. It records useful skills, tool integrations, workflows, personal todo items, and the repository decisions that keep the system coherent over time. Executable tools remain self-contained under `tools/`.

## Structure

- [skills/](skills/README.md) - agent skills and reusable instruction packs.
- [tools/](tools/README.md) - MCP servers, plugins, CLIs, browser tools, and integrations.
- [workflows/](workflows/README.md) - repeatable multi-step processes and domain workflows.
- [todo/](todo/README.md) - personal action queue for evaluating, installing, and improving entries.
- [decisions/](decisions/README.md) - ADR-style records for repository structure and governance.

## Entry Metadata

Each entry should stay lightweight:

```md
# Name

- Type:
- Domain:
- Source:
- Status:
- Use when:

## Notes
```

Use `Domain:` for fields such as `coding`, `investing`, `research`, `learning`, or `ops`. Do not create new top-level directories for domains unless a decision record says why.
