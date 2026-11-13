#!/usr/bin/env python3
"""Approve narrowly recognized test discovery; defer all other decisions."""
import json
import os
import re
import shlex
import sys


def is_test_discovery(command):
    if not isinstance(command, str) or re.search(r'[$`\n<>]', command):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()')
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False
    groups = [[]]
    for word in words:
        if word == '&&':
            groups.append([])
        elif word in {';', '&', '|', '||', '|&', '(', ')'}:
            return False
        else:
            groups[-1].append(word)
    for args in groups:
        if args and re.fullmatch(r'PYTHONPATH=[A-Za-z0-9_./:-]+', args[0]):
            args = args[1:]
        if len(args) < 6 or not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', os.path.basename(args[0])):
            return False
        if args[1:4] != ['-m', 'unittest', 'discover']:
            return False
        options = args[4:]
        pattern = None
        while options:
            option = options.pop(0)
            if option in {'-v', '--verbose', '-q', '--quiet'}:
                continue
            if option not in {'-s', '--start-directory', '-t', '--top-level-directory', '-p', '--pattern'} or not options:
                return False
            value = options.pop(0)
            if option in {'-p', '--pattern'}:
                if pattern is not None or not re.fullmatch(r'test_[A-Za-z0-9_.*?\-]*\.py', value):
                    return False
                pattern = value
            elif not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
                return False
        if pattern is None:
            return False
    return bool(groups)


def main():
    try:
        event = json.load(sys.stdin)
        if event.get('tool_name') != 'Bash' or not is_test_discovery(event.get('tool_input', {}).get('command')):
            return
    except (ValueError, TypeError, AttributeError):
        return
    json.dump({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
               'permissionDecision': 'allow', 'permissionDecisionReason': 'Recognized Python unittest discovery.'}}, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
