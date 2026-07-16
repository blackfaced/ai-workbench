# AGENTS.md

This repository is a personal AI development workbench knowledge base.

## Collaboration Rules

- Keep top-level organization by artifact type, not by life domain.
- Put agent skills and reusable instruction packs under `skills/`.
- Put MCP servers, plugins, CLIs, browser tools, and integrations under `tools/`.
- Put repeatable usage patterns and multi-step processes under `workflows/`.
- Put personal action items under `todo/`.
- Record repository governance and structure decisions under `decisions/`.
- Use `Domain:` metadata for fields like `coding`, `investing`, `research`, `learning`, and `ops`.
- Prefer one entry per file plus a directory `README.md` index.
- Do not create new top-level directories without adding or updating an ADR.
- Keep entries concise and practical: when to use, setup notes, evaluation status, and personal observations.
- Treat engineering skills as lightweight and opt-in; do not impose a heavyweight process framework by default.
