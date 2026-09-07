# AI Workbench

Personal workbench for AI-assisted development, research, reusable knowledge, and repeatable agent workflows.

This repository is a workbench, not a public skill registry. It records useful skills, tool integrations, workflows, personal todo items, and the repository decisions that keep the system coherent over time. Executable tools remain self-contained under `tools/`.

## Primary Use

**Install, update, and check a personal development environment from one entry point.**

Bring a machine up to a known baseline, then use the same entry point to inspect drift and apply updates. Preview is the default; nothing is written unless `--apply` is passed.

```sh
bash tools/environment/bootstrap.sh --profile work-mac              # preview (read-only)
bash tools/environment/bootstrap.sh --profile work-mac --apply      # apply
bash tools/environment/bootstrap.sh --profile work-mac --check      # check
```

Profiles: `work-mac` (macOS work laptop), `work-linux` (both Linux dev boxes). `home-mac` is not implemented and not verified — see [0009](decisions/0009-reproducible-development-environments.md).

Details, managed-config rules, backup/restore, and per-machine differences: [tools/environment/](tools/environment/README.md).

The environment entry point requires only `git`, `python3`, and a POSIX shell. It does not depend on `aiwb` or the agent orchestrator.

## Structure

- [tools/environment/](tools/environment/README.md) - environment profiles, install/update/check entry point.
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
