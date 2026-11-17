# Claude Code command confirmation

Domain: coding, ops

The optional Claude hook approves the following test invocations,
including virtual environment executables, `uv run`, a leading `PYTHONPATH` assignment,
and chains joined by `&&` when every segment qualifies.

- `python3 tests/test_example.py` (the filename can be in any directory)
- `python3 -m unittest`, including named tests and discovery
- `pytest` and `python3 -m pytest`, including options and node IDs

It also approves common file inspections and explicitly configured read queries,
including pipelines with text or stdin-only JSON filters. A Git push and direct
invocation of Python, Node or shell script files are approved alone or in chains
whose other stages also pass the hook. Explicit
remote-ref deletion, destructive operations, executable wrappers and unsupported
shell syntax request confirmation, including in bypass-permissions mode. Ordinary
commands outside those categories continue through Claude Code's usual permissions.

## File inspection

Common read options for `ls`, `cat`, `grep`/`rg`, `head`/`tail`, `nl`, `cut`, `tr`,
`sort`, `uniq`, `wc`, stdout-only `printf`, and numeric
`sed -n` line printing are supported.
`cd`, `pwd`, `echo` and `true` can accompany these inspections.
Approved `rg` invocations receive `--no-config`.

`helm lint`, local `helm template`, `helm list`/`ls` and `helm status` are
recognized with common options, including in chains with approved script calls
and Git checks. `list` and `status` query the selected Kubernetes context; a
kubeconfig can itself invoke credential helpers. For `template`, use an explicit
local chart path such as `./chart` or `/tmp/chart`. Remote charts or values URLs,
output directories, post-renderers, dependency updates and unknown options ask.
Other Helm commands, including `install`, `upgrade`, `rollback` and `uninstall`,
also ask. Script contents remain outside the hook's inspection boundary.

`find` supports read-only name, path, type, size, time and ownership predicates,
depth limits, quoted or escaped grouping, negation, pruning and stdout printing.
`-exec`, `-execdir`, `-ok`, `-delete`, file-output actions and unknown predicates
still ask. Trailing `2>/dev/null` may discard errors; redirecting to an ordinary
file still asks.

Commands joined by `&&`, `||`, `;` or newlines are approved only when every command and
pipeline stage is recognized by the hook. Comments,
blank lines and locale prefixes such as `LC_ALL=C` are supported. Literal separators
inside quoted text remain data. Path-prefixed globs such as `src/*.py` work across
repositories; unprefixed globs are limited to commands whose options cannot execute
programs or write output files. Unknown options, `sed` editing or execution, `rg --pre`, write
redirection, background jobs and execution wrappers request confirmation.

Finite `for` loops over up to 32 literal values are also supported, optionally
after an approved `&&` prefix. Values may contain letters, digits, `_`, `.`,
`/`, `:`, `+` and `-`, and may be quoted. The loop body may use `$name` or
`${name}` for its lowercase loop variable. The hook checks every expanded body
and preserves the usual Git inspection guards. Nested loops, dynamic lists,
other variable expansions, comments in the body, and commands following the
loop request confirmation. Each body remains subject to the existing command
rules and their script-content limitations.

```sh
cd /tmp/example && ls src 2>&1; sed -n '10,20p' tests/ExampleTest.java
rg -n 'assertTrue' tests | head -n 20
find . -type f -name '*.py' 2>/dev/null | head -n 20
git -C /tmp/example ls-files 'src/**/*.py'
bash /tmp/example/tests/render-contract.sh && helm lint /tmp/example/chart && git -C /tmp/example diff --check
helm template demo ./chart --include-crds | grep kind
helm list --namespace demo -o json | jq .
for ref in v1 v2; do git show "$ref:README.md" | grep example; done
```

## Git inspection

One shared policy covers `status`, `diff`, `log`, `show`, `ls-files`, `ls-tree`,
`rev-parse`, `rev-list`, `show-ref`, `merge-base`, `describe`, `shortlog`, `grep`,
`diff-tree`, `blame`, and plain `cat-file` reads. It also supports branch/tag
listing, remote URL inspection and `worktree list`; creating or changing those
objects still asks.
It accepts repeated or attached `-C` options, common revision and path arguments,
formatting, search and history limits, and the read-only pipelines and chains above.
New repositories and worktrees need no additional declarations.

Approved invocations disable the pager, optional index writes, filesystem-monitor
helpers, default signature verification and configured custom log formats.
`diff`, `log`, and `show` also receive `--no-ext-diff --no-textconv`.
`diff-tree` receives the same flags; `grep` and `blame` receive `--no-textconv`.
Ordinary formatting such as `--oneline`, `--stat`, `--name-only`, `--format='%h %s'`
and `--porcelain` remains available. These guards affect only this invocation;
repository configuration is unchanged.

Remote-ref deletion, other mutations, aliases, arbitrary `-c` settings, output files, executable
helpers, signature-verifying formats, and unknown options request confirmation.
Verbose `status` (`-v`/`--verbose`) also asks because it can run text conversion
without a disabling option; use a normal status followed by a guarded diff.

```sh
git -C /tmp/example status --short && git -C /tmp/example diff --stat
git -C /tmp/example log -20 --oneline | head -n 10
git -C /tmp/example show HEAD:README.md | sed -n '1,40p'
```

## Read queries and JSON filters

Declare trusted read commands in `~/.config/ai-workbench/claude-confirm.json`.
This is user-owned machine configuration. The environment manager installs the
hook and preserves this file during upgrades and rollback. Keep organization-specific
commands and identifiers in this local file.

```json
{
  "version": 1,
  "queries": [
    {
      "prefix": ["example-cli", "items", "list"],
      "flags": ["--json", "-j"],
      "value_options": ["--limit", "--jq"],
      "max_positionals": 0
    }
  ]
}
```

Each declaration trusts a specific CLI operation and enumerates its flags and
value-taking options. Verify that operation's read behavior before adding it.
Declared flags and value options can occur before, between or after prefix words.
Unknown options ask by default. Set `"arguments": "*"` on a reviewed query to
accept new read arguments and selectors without adding rules for every spelling.
The command prefix stays exact; execution, output-file, mutation, credential and
connection-override options still ask unless explicitly declared. This trusts
the CLI operation's read behavior, not an entire executable or a verb appearing
somewhere in a command.
Execution wrappers and Git cannot be declared as query programs.

A local declaration may use a one-word prefix with `"arguments": "*"` and a
`"deny_words"` array to trust a CLI broadly while asking on literal action words.
For example, a generic declaration might deny `delete`, `remove`, `merge`, `send`,
and `notify`. Message/comment operations containing `@` also ask. Option checks
still apply. This is a text-based policy, not a complete classification of a CLI:
aliases, flags, API calls and scripts can hide side effects. Review the actual
CLI before adding a broad rule, and keep the declaration in local policy.

```json
{"prefix": ["example-cli"], "flags": [], "value_options": [],
 "max_positionals": 0, "arguments": "*",
 "deny_words": ["delete", "remove", "merge", "send", "notify"]}
```

The generic Kubernetes reader similarly accepts resource and selector variations
for `get`, `describe`, `logs`, `api-resources`, `api-versions` and `version`.
Mutation verbs, raw API paths, connection overrides and profiling/log-file writes
still ask. Remote reads rely on the user's existing kubeconfig and authentication.

Supported pipelines start with a declared query or file inspection and contain
recognized read-only text commands, `jq` or inline Python JSON filters. Standalone
`jq` and Python JSON inspection are supported, including read-only input files.
Literal arguments, quoted text, line continuations and a
trailing `2>&1` or `2>/dev/null` per stage are supported. `jq` filters cannot load
executable filter files or modules. Python filters may import `json`, `sys` and
`os`, read stdin, environment values and files opened in `r`/`rt`/`rb` mode, select
and format data, and print results. The hook adds Python `-I` through `updatedInput`
to exclude cwd and `PYTHONPATH` imports. Other imports, file writes, subprocesses,
dynamic execution and unrecognized filters ask for confirmation.

```sh
example-cli items list --json | jq -r '.data[].name'
example-cli items list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["data"]))'
python3 ~/.local/share/ai-workbench/hooks/claude-confirm.py --check-policy
```

A missing policy enables no query approvals. Invalid policy data requests
confirmation and `--check-policy` exits nonzero. Environment `check` verifies the
installed script and registration; run the policy check separately after editing it.

## Reviewed planning scripts

An optional `scripts` array in the local policy registers self-contained Python
scripts by absolute `path` (glob patterns allowed), reviewed `sha256`, and `actions`
chosen from `plan`, `check`, `status`, or `inspect`. Matching paths alone do not
establish trust for the report flow: a changed digest asks again. Action arguments
are flexible, while apply/force and configuration-override switches ask for that
flow. Source-specific paths,
digests and machine names belong only in local policy.

The hook recognizes a report flow consisting of a registered action, a temporary
JSON output, a captured exit status, and a quoted Python summary heredoc. It rewrites
that flow to direct argv execution with isolated Python, preserving the status and
locale. Output must be a direct child of the system/user temporary directory;
existing symlinks, hard links and files owned by another user are refused. The
summary must pass the same read-only Python checks. Other heredocs continue to
ask. Direct script-file invocations are approved separately and do not require a
digest; their contents are not inspected. The script's dependencies and configured read transports remain
part of the reviewed trust boundary.

The environment manager preserves local policy on rollback. If rolling back to a
hook version that predates `arguments` or `scripts`, restore the corresponding
policy backup too; old versions reject unfamiliar policy fields.

## Attended and unattended use

Use `acceptEdits` during development. For an unattended run, use
`claude --permission-mode dontAsk`: allowed operations run, while operations that
would need approval are denied. Ask Claude to record denied operations and continue
independent work rather than retrying or bypassing the restriction. `auto` still
honors this hook's explicit confirmation requests. See the client's
[permission modes](https://code.claude.com/docs/en/permission-modes) for current behavior.

## Scope and limits

- Test code and Python import paths can execute arbitrary code. Enabling this
  hook trusts the selected tests, runners, options, and plugins; it does not inspect their contents.
- Direct script files and SSH remote scripts can perform arbitrary actions,
  including deletion, merging and sending messages. The hook cannot guarantee
  confirmation for actions hidden inside them. Inline scripts, heredocs and
  unsupported shell wrappers remain subject to the existing checks.
- Direct SSH commands with basic connection options are inspected using the same
  rules as local commands. The hook cannot inspect SSH config, local proxy helpers,
  remote shell initialization, aliases or the contents of remote scripts.
- The Bash hook is registered for Bash and PowerShell only. The separate
  `claude-mcp-confirm` component below checks direct MCP calls.
- Dangerous-command detection covers common spellings and wrappers. Executables
  and aliases can hide behavior that command text does not reveal. Keep explicit
  permission rules and repository protections where needed.
- Shell substitutions, write redirection, chains containing an unrecognized or
  unapproved command, and PowerShell request confirmation. Test-only `&&` chains
  retain their test approval.

## Opt in

Run the offline tests first:

```sh
python3 -m unittest discover -s tools/claude-confirm -p 'test_*.py'
```

Review the hook, then use the AIWB environment manager's explicit opt-in
component. The generic `claude-hooks` profile is selected explicitly and has no machine-specific configuration:

```sh
python3 tools/environment/env.py plan --profile claude-hooks --only claude-confirm
python3 tools/environment/env.py apply --profile claude-hooks --only claude-confirm
python3 tools/environment/env.py check --profile claude-hooks --only claude-confirm
```

The component preserves other settings and hooks and records a backup for
guarded rollback. Existing hooks can also prompt; the manager does not remove
or adopt them. The environment manager checks ownership before updates and supports guarded rollback. Restart Claude Code or reload its hooks,
inspect `/hooks`, and verify a test command, a configured query pipeline, an
ordinary push decision and a deletion confirmation. Installation checks do not prove interactive client behavior.

## MCP message confirmation

The separate opt-in `claude-mcp-confirm` component registers a `PreToolUse`
matcher for `mcp__.*`, using a distinct script and ownership record. It asks for
recognizable message creation, replies and sends, and for common text, HTML,
JSON or structured mentions in write operations. It leaves other calls to the
client's existing permission rules. It does not send or read any messages.

```sh
python3 tools/environment/env.py plan --profile claude-hooks --only claude-mcp-confirm
python3 tools/environment/env.py apply --profile claude-hooks --only claude-mcp-confirm
python3 tools/environment/env.py check --profile claude-hooks --only claude-mcp-confirm
python3 tools/environment/env.py restore --backup <apply-backup> --dry-run
```

Tool names and payloads differ across MCP servers. The decision is based on
visible names and input fields, so an opaque custom tool, indirect call, encoded
content or nonstandard mention can evade detection; read operations can also be
misclassified. Scripts and shell commands are outside this MCP hook. Ask rules
from this hook may be denied instead of prompted in `dontAsk` mode. See
[Claude Code hook matching](https://code.claude.com/docs/en/hooks#match-mcp-tools).
