#!/usr/bin/env python3
"""Approve recognized Python test commands; defer all other decisions."""
import json
import os
import re
import shlex
import sys


def test_invocation(args):
    if args and re.fullmatch(r'PYTHONPATH=[A-Za-z0-9_./:-]+', args[0]):
        args = args[1:]
    if args[:2] == ['uv', 'run']:
        args = args[2:]
        while args and args[0] in {'--offline', '--no-sync', '--frozen', '--no-env-file'}:
            args = args[1:]
    if not args or not re.fullmatch(r'[A-Za-z0-9_./ -]+', args[0]):
        return False
    program = os.path.basename(args[0])
    if program == 'pytest':
        return True
    if not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', program):
        return False
    operands = args[1:]
    while operands and operands[0] in {'-B', '-u', '-I', '-O', '-OO'}:
        operands = operands[1:]
    if operands[:1] == ['-m']:
        return len(operands) >= 2 and operands[1] in {'pytest', 'unittest'}
    if operands[:1] == ['--']:
        operands = operands[1:]
    return (bool(operands) and not operands[0].startswith('-')
            and re.fullmatch(r'test_[^/]*\.py', os.path.basename(operands[0])) is not None)


# Consume only literals, quoted text, and &&. Keep quoted pytest expressions
# together while deferring shell substitutions, redirections and other operators.
SHELL_PART = re.compile(r"""'[^']*'|"[^"\\$`]*"|&&|[a-zA-Z0-9@%_+=:,./~*?\[\] \t-]+""")


def is_test_command(command):
    if not isinstance(command, str) or re.search(r'[\r\n\x00]', command):
        return False
    start = pos = 0
    while pos < len(command):
        part = SHELL_PART.match(command, pos)
        if part is None:
            return False
        if part.group() == '&&':
            if not test_invocation(shlex.split(command[start:pos])):
                return False
            start = part.end()
        pos = part.end()
    return test_invocation(shlex.split(command[start:]))


def main():
    try:
        event = json.load(sys.stdin)
        if event.get('tool_name') != 'Bash' or not is_test_command(event.get('tool_input', {}).get('command')):
            return
    except (ValueError, TypeError, AttributeError):
        return
    json.dump({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
               'permissionDecision': 'allow', 'permissionDecisionReason': 'Recognized Python test command.'}}, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
