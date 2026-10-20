# AI Workbench

Maintain a personal development environment from one repository: inspect drift, update tools, and install or restore selected configuration and Skills.

The current verified scope is maintenance of the **work Mac, home Mac mini, and two existing Linux development machines, dev-a and dev-b**. The [home Mac validation](tools/environment/home-mac-validation.md) covers installed tools and native Skill discovery in Codex CLI, the desktop runtime, and Kimi Code. Full fresh-machine bootstrap remains incomplete, including Linux installation channels for `codex`, `uv`, and `rg`.

## Use

Requires Git, Python 3.9 or newer, and a POSIX shell. Run from this checkout:

AIWB works without an external workspace manager. For new Skill adoption, follow the [project-scoped installation policy](skills/README.md#installation-policy): select fixed source versions and project/client targets directly, or use an existing manager if you have one. For `setup-aiwb`, read its [standalone dependency preparation and check](skills/setup-aiwb/references/matt-project-baseline.md). The commands below describe the existing environment maintenance tool. Unfiltered `--apply` still installs profile-selected Skills into user-global directories; it is not the recommended project activation path. Limit unrelated maintenance to explicitly selected components with `env.py --only` as documented in the environment guide.

```sh
sh tools/environment/bootstrap.sh --profile work-mac          # read-only preview
sh tools/environment/bootstrap.sh --profile work-mac --apply  # apply eligible changes
sh tools/environment/bootstrap.sh --profile work-mac --check  # check drift and conflicts
```

Use `--profile work-linux` on either Linux machine. Review the plan before applying. Missing verified installation channels and user-modified targets are reported for intervention.

On the home Mac use `--profile home-mac`. With multiple Mac profiles, an unrecognized host must select one explicitly; macOS alone does not identify a work machine.

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

## Maintenance

- Prefer one entry per file and keep the corresponding directory `README.md` index up to date.
- Record structural or governance changes in `decisions/` before introducing a new top-level directory.
- Keep notes concise and practical: explain when to use an entry, how it is set up, and its current evaluation status.
- Keep executable integrations self-contained under `tools/`; document reusable usage patterns under `workflows/`.

## License

AI Workbench's maintained environment tooling, first-party Skills and documentation are licensed under [Apache License 2.0](LICENSE), except material carrying its own license or third-party notices.

The [engineering-principles instruction pack](skills/engineering-principles/LICENSE) remains MIT-licensed. Third-party material and linked or externally installed tools/Skills retain their original licenses and attribution; the repository license does not relicense them.
