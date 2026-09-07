# AI Workbench

Maintain a personal development environment from one repository: inspect drift, update tools, and install or restore selected configuration and Skills.

The current verified scope is the **work Mac and two existing Linux development machines, dev8c and dev32c**. Full fresh-machine bootstrap is the intended direction, but Linux initial installation channels for `codex`, `uv`, and `rg` are still incomplete. The home Mac (ChatGPT desktop and Kimi Code) is deferred until it is accessible.

## Use

Requires Git, Python 3.9 or newer, and a POSIX shell. Run from this checkout:

```sh
sh tools/environment/bootstrap.sh --profile work-mac          # read-only preview
sh tools/environment/bootstrap.sh --profile work-mac --apply  # apply eligible changes
sh tools/environment/bootstrap.sh --profile work-mac --check  # check drift and conflicts
```

Use `--profile work-linux` on either Linux machine. Review the plan before applying. Missing verified installation channels and user-modified targets are reported for intervention.

See the [environment guide](tools/environment/README.md) for component ownership, backups, restore, selective updates, and machine-specific limitations.

## Repository map

- [tools/environment/](tools/environment/README.md): maintained profiles and executable environment tooling.
- [skills/](skills/README.md): selected first-party Skills and upstream source records; entries are opt-in.
- [tools/](tools/README.md): environment tooling and optional integration references.
- [workflows/](workflows/README.md): usage guides and optional workflow references.
- [decisions/](decisions/README.md): current scope and historical architecture decisions.
- [CONTEXT.md](CONTEXT.md): environment terminology.

Active work belongs in the [issue tracker](docs/agents/issue-tracker.md). The [old evaluation notes](todo/README.md) are historical, not an active task queue.

Organize entries by artifact type. Use `Domain:` metadata when useful; keep setup notes, ownership, and verification status concise. The presence of a catalog entry does not mean it is installed, verified, or part of the machine baseline.
