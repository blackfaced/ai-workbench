# Claude Code command confirmation

Domain: coding, ops

This optional `PreToolUse` hook asks before shell commands that are not on a
small list of simple reads. It catches common push, deletion, compound-command
and script-runner forms without trying to interpret script contents. It never
returns `allow`: a call that it does not flag still follows Claude Code's
normal permission rules. PowerShell calls always ask.

## Scope and limits

- The hook covers Claude Code `Bash` and `PowerShell` tool calls. It does not
  inspect MCP tools, hooks, file tools, or commands run outside Claude Code.
- It is a conservative text check, not a complete shell parser or an OS
  security boundary. Executable shadowing, indirect execution, runtime changes,
  another tool or a failed hook can bypass its intended coverage. Keep explicit
  ask/deny rules and use sandboxing or repository protections for stronger
  boundaries.
- Scripts and compound commands prompt, including tests and read-only probes.
  Project-specific exceptions belong in the target environment and must be
  reviewed separately. This repository ships no project-specific allowlist.
- An `ask` from this hook takes precedence over another hook's `allow`, so an
  existing script exception can start prompting if both hooks are enabled.
  Review this behavior before installing alongside a different guard.
- In non-interactive sessions, an `ask` may be denied instead of prompting.
  Other hooks and explicit rules can also affect the final decision.

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
inspect `/hooks`, and test one safe command and one harmless command that should
prompt; installation checks do not prove interactive client behavior.
