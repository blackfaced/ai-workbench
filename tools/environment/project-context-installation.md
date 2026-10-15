# Project context: fixed-version installation and maintenance

This candidate extends [ADR 0013](../../decisions/0013-project-owned-agent-context.md); [ADR 0014](../../decisions/0014-project-context-declaration.md) records the safety and compatibility contract. It never starts an agent loop or installs a worktree hook.

## Install only the tool

From the chosen, reviewed AIWB source revision:

```sh
python3.11 tools/environment/install_project_context.py install --version <immutable-version>
python3.11 tools/environment/install_project_context.py check --version <immutable-version>
```

Default stable entry: `~/.local/bin/setup-aiwb-context`. Releases and the installation ledger live in `~/.local/share/setup-aiwb-tools/releases/`. The entry pins a release manifest, renderer, companion `env.py`, support modules and installer; it does not import a moving checkout. The source commit, dirty flag and payload hashes distinguish a local candidate from a committed release. Installation checks a real TOML parser and entry execution before success. No automatic Python package installation or client update.

For an upgrade use a new immutable version. To select a retained version:

```sh
python3.11 tools/environment/install_project_context.py rollback --version <retained-version>
python3.11 tools/environment/install_project_context.py check --version <retained-version>
```

An edited launcher, manifest or payload is refused. `check` also requires the stable entry to exist, be executable and successfully run `--help` with its pinned interpreter. Old releases are not deleted. This rolls back the tool entry, not applied project configuration, external software or model sessions. The installer is also retained inside each release.

## Project-owned rules

Private native configuration is not Git-tracked. Keep a project-owned declaration at `.aiwb/project-context.json` or pass `--declaration` / `AIWB_PROJECT_DECLARATION`. Example (replace the example policy with the project's actual source):

```json
{
  "version": 1,
  "instructions": "Example project policy: preserve the team's guidance and use this project's tracker.",
  "additiveEntry": {"clients": ["codex", "trae"]}
}
```

Alternatively `rulesSource` supplies a local path and exact SHA-256. Relative paths stay within the project; an explicit absolute source is pinned and inspected, never executed. `profiles` maps selected legacy profile names to project-owned strings. `tracker.kind`, `tracker.idPattern`, `knowledgeSources`, `lazyPolicy` and `pack` are validated project input. Unknown fields, invalid values, missing pins and unsupported native paths fail rather than being ignored. Runtime checks are implemented by the bounded `context_declaration.py` validator; the schema documents the same input contract, not a general JSON-Schema execution engine.

```sh
setup-aiwb-context --repo <project> --declaration <project-declaration>             # plan
setup-aiwb-context --repo <project> --declaration <project-declaration> --apply
setup-aiwb-context --repo <project> --declaration <project-declaration> --check
```

Historical `none`, `owned-full`, `legacy-only`, marker IDs, `--pin`, `--workenv`, `--worktree`, v2 ledgers and backup layout remain recognizable. Existing owned legacy blocks can be checked/retained without a declaration; that confirms ownership/no observed edit, **not** an up-to-date policy source. New provisioning or policy updates need project text. Existing external callers are not automatically switched to the new entry. For the same legacy text/provenance use explicit `--pin` and `--workenv` from its recorded source.

## Trust is an independent permission

Default: no user-level trust mutation, even when a non-none profile or declaration `trust: true` requests it. After the owner authorizes the exact checkout(s), add `--manage-trust`. Existing untrusted values are preserved and block preflight. Do not mark a parent/all-projects trusted. `--no-manage-trust` remains supported. A declaration cannot authorize itself.

## Worktrees, exclusions and restore

Explicitly pass each new `--worktree <path>` before opening its native client; new worktrees do not inherit untracked config. The tool does not auto-scan Git worktrees. Validate real cwd and realpath trust independently. Keep native config and `.ai-workbench/` in the owning repo's local exclusion entries; installation does not change excludes. Git-tracked native files are refused to avoid writing private rules into team content.

Project ledger/backups: `<project>/.ai-workbench/project-context/`. Restore with `setup-aiwb-context --repo <project> --restore <backup-name> [--dry-run]`. It validates snapshot identity, paths, hashes, current managed blocks and trust-table content. New trust snapshots preserve other projects; legacy whole-file snapshots keep their strict whole-file drift guard. `--force` is restore-only and never bypasses apply ownership guards. Before a forced restore changes a target, it saves the current file and component ledger record in a new v2 snapshot and prints its `recovery backup` path. That snapshot can be restored with the same command; `--dry-run` creates no recovery snapshot. Reconcile conflicts before retrying; preserve backup material.

TOML parser required on every write/check. Python 3.11+ supplies `tomllib`; older Python needs an explicitly provisioned `tomli`. No parser means refusal, not a placement-only PASS. Cooperating operations lock by ledger/native/trust resources; ordinary editor races are checked by a pre-replace digest but the final check/rename race cannot be eliminated portably. This is not a transaction across multiple files; an I/O failure can leave a backed-up applied prefix. Plans may create diagnostic lock files only, not project/trust configuration.

## Authorized Botmux startup integration

The installed release also carries `botmux_context.py`. Its opt-in [startup gate](../../skills/setup-aiwb/references/botmux-startup.md) uses Botmux's existing local launch-shell slot to call this renderer before native client exec. Project/trust writes remain limited to registered Git common-dir identities and the exact selected checkout. It does not install a Git hook or create an agent loop.

## Verification

```sh
python3.11 tools/environment/tests/test_project_context_render.py
python3.11 tools/environment/tests/test_project_context_boundaries.py
python3 tools/environment/tests/regression.py
```

Use actual clients' `debug prompt-input` in isolated HOME/repositories for team/private presence, absent-file and unrelated-project negative controls. It is no-model loading evidence, not model behavior acceptance. Keep raw prompt/config contents private; retain sanitized booleans, client identity and candidate payload hashes. Installation lifecycle checks, local client loading, multi-host operating acceptance, harness/Zed auto-creation and Botmux first-task loading are distinct. Existing sessions and hooks stay untouched until their separate authorized verification.
