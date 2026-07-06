# 0001 - Repository Scope and Structure

## Status

Accepted

## Context

This repository is intended for personal use. It should help record useful AI skills, tool integrations, workflows, and todo items discovered during development and research.

The first known sources include:

- `superpowers`
- `mattpocock/skills`
- `xbtlin/ai-berkshire`
- `ChromeDevTools/chrome-devtools-mcp`

Some entries may belong to specific life or work domains, such as investing. However, the main purpose of this repository is to organize AI collaboration assets, not to become a general personal knowledge base organized by life area.

## Decision

Use `ai-workbench` as the repository name.

Organize the repository by artifact type:

- `skills/` for agent skills and reusable instruction packs.
- `tools/` for MCP servers, plugins, CLIs, browser tools, and integrations.
- `workflows/` for repeatable multi-step processes and domain workflows.
- `todo/` for the owner's personal action queue.
- `decisions/` for ADR-style repository governance decisions.

Do not create top-level directories for life domains, such as `investment/`.

Represent domains inside entry metadata instead:

```md
- Domain: investing
```

Prefer one file per entry, with a `README.md` index in each directory.

Add `AGENTS.md` so future agent sessions preserve these repository rules.

## Consequences

The repository stays focused on AI-assisted work rather than becoming a broad personal archive.

Domain-specific resources, such as `ai-berkshire`, remain discoverable through metadata while still living under their artifact type.

New top-level directories require an ADR update, which prevents the structure from drifting during casual additions.

