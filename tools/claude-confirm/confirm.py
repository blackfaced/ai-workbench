#!/usr/bin/env python3
"""Ask before risky or opaque Claude Code shell calls; never auto-approve."""
import json
import os
import re
import shlex
import sys

SAFE_COMMANDS = {'ls', 'pwd', 'which', 'whoami', 'uname', 'date'}
SAFE_LISTINGS = {('ls', '-a'), ('ls', '-l'), ('ls', '-la'), ('ls', '-al')}
SAFE_GIT = {
    ('status',), ('status', '--short'), ('status', '--porcelain'),
    ('diff',), ('diff', '--stat'), ('log', '--oneline'),
    ('rev-parse', '--show-toplevel'),
}
SHELL_META = re.compile(r'[$`\n;&|<>]')


def confirmation_reason(command):
    """Return a reason when a command needs review, otherwise None.

    This intentionally recognizes a small set of simple reads. It is not a
    shell parser or a security boundary for commands executed by other tools.
    """
    if not isinstance(command, str) or not command.strip():
        return 'Cannot inspect the command; please confirm it.'
    if SHELL_META.search(command):
        return 'The command contains shell expansion or compound syntax; please confirm it.'
    try:
        args = shlex.split(command)
    except ValueError:
        return 'Cannot parse the command; please confirm it.'
    if not args:
        return 'Cannot inspect the command; please confirm it.'

    executable = os.path.basename(args[0])
    if executable == 'git':
        if args[0] != 'git':
            return 'An explicit Git executable path needs confirmation.'
        rest = args[1:]
        # -C changes the repository, not the operation. Other global options
        # may execute helpers or redefine Git configuration and require review.
        while len(rest) >= 2 and rest[0] == '-C':
            rest = rest[2:]
        if tuple(rest) in SAFE_GIT:
            return None
        return 'Git operation is not on the small read-only list; please confirm it.'

    # Use bare names only: absolute paths and local executables can be aliases
    # or scripts and are not equivalent to the shell's known command.
    if (args[0] in SAFE_COMMANDS and len(args) == 1) or tuple(args) in SAFE_LISTINGS:
        return None
    return 'The command can execute a script, change state, or is unrecognized; please confirm it.'


def main():
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name')
        if name == 'Bash':
            reason = confirmation_reason(event.get('tool_input', {}).get('command'))
        elif name == 'PowerShell':
            reason = 'PowerShell commands require confirmation.'
        else:
            return
    except (ValueError, TypeError, AttributeError):
        reason = 'Cannot inspect the hook input; please confirm the operation.'
    if reason:
        json.dump({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                   'permissionDecision': 'ask', 'permissionDecisionReason': reason}}, sys.stdout)
        sys.stdout.write('\n')


if __name__ == '__main__':
    main()
