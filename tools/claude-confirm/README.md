# Claude Code command confirmation

Domain: coding, ops

The optional Bash hook in Claude Code approves the following test invocations,
including virtual environment executables, `uv run`, a leading `PYTHONPATH` assignment,
and chains joined by `&&` when every segment qualifies.

- `python3 tests/test_example.py` (the filename can be in any directory)
- `python3 -m unittest`, including named tests and discovery
- `pytest` and `python3 -m pytest`, including options and node IDs

Other shell operations continue through Claude Code's usual permissions.

## Scope and limits

- Test code and Python import paths can execute arbitrary code. Enabling this
  hook trusts the selected tests, runners, options, and plugins; it does not inspect their contents.
- This is a convenience rule, not a security boundary. Keep explicit permission
  rules and use sandboxing or repository protections where needed.
- Command substitutions, redirection, pipes, multiline commands,
  and PowerShell are not approved by this hook.
- This hook does not ask before pushes or destructive operations; configure
  those separately in Claude Code permissions.

## Opt in

Run the offline tests first:

```sh
python3 -m unittest discover -s tools/claude-confirm -p 'test_*.py'
```

Review the hook, then use the AIWB environment manager's explicit opt-in
component. Choose the profile for the target machine:

```sh
python3 tools/environment/env.py plan --profile work-mac --only claude-confirm
python3 tools/environment/env.py apply --profile work-mac --only claude-confirm
python3 tools/environment/env.py check --profile work-mac --only claude-confirm
```

The component preserves other settings and hooks and records a backup for
guarded rollback. Existing hooks can also prompt; the manager does not remove
or adopt them. See [environment maintenance](../environment/README.md#claude-命令确认-hook)
for conflict handling and rollback. Restart Claude Code or reload its hooks,
inspect `/hooks`, and test a recognized test command and verify other commands use normal
permissions; installation checks do not prove interactive client behavior.
