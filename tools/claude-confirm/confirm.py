#!/usr/bin/env python3
"""Approve trusted tests and configured read queries; defer all other calls."""
import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile


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


ASK_PROGRAMS = {
    '.', '!', 'Rscript', 'awk', 'bash', 'builtin', 'bun', 'busybox', 'chgrp', 'chmod', 'chown',
    'command', 'cp', 'curl', 'dash', 'dd', 'deno', 'diskutil', 'doas', 'docker', 'env',
    'eval', 'exec', 'expect', 'find', 'fish', 'gawk', 'gh', 'git-receive-pack',
    'git-send-pack', 'git-shell', 'glab', 'gtimeout', 'hub', 'install', 'jq', 'just',
    'kill', 'killall', 'ksh', 'kubectl', 'launchctl', 'lua', 'luajit', 'make', 'mawk',
    'mkfs', 'mv', 'nawk', 'nc', 'nice', 'node', 'nodejs', 'nohup', 'npm', 'npx',
    'osascript', 'parallel', 'perl', 'php', 'pip', 'pip3', 'pkill', 'pnpm', 'podman',
    'pulumi', 'reboot', 'rm', 'rmdir', 'rsync', 'ruby', 'scp', 'sed', 'setsid', 'sftp',
    'sh', 'shred', 'shutdown', 'socat', 'source', 'ssh', 'su', 'sudo', 'sudoedit',
    'systemctl', 'tclsh', 'tee', 'terraform', 'time', 'timeout', 'tofu', 'truncate',
    'unlink', 'uv', 'watch', 'wget', 'xargs', 'yarn', 'zsh',
}

WORD = re.compile(r'''(?:'[^']*'|"(?:[^"\\$`]|\\[^\r\n$`])*"|\\[()!]|[A-Za-z0-9_@%+=:,./~^!*?\[\]-])+''')
READ_REDIRECTIONS = ('2>&1', '2>/dev/null')
READ_PROGRAMS = {'cat', 'cd', 'cut', 'echo', 'egrep', 'fgrep', 'find', 'grep', 'head',
                 'jq', 'ls', 'nl', 'printf', 'pwd', 'rg', 'sed', 'sort', 'tail', 'tr',
                 'true', 'uniq', 'wc'}

def program_name(value):
    if '/' not in value:
        return value
    if os.path.dirname(value) in {'/usr/bin', '/bin', '/opt/homebrew/bin', '/usr/local/bin'}:
        return os.path.basename(value)
    return ''

def pipeline(command):
    if not isinstance(command, str) or len(command) > 32000 or '\x00' in command:
        raise ValueError('Invalid shell input')
    stages = [([], False)]
    pos = 0
    while pos < len(command):
        if command[pos] in ' \t\n':
            pos += 1
            continue
        if command.startswith('\\\n', pos):
            pos += 2
            continue
        args, redirected = stages[-1]
        redirection = next((r for r in READ_REDIRECTIONS if command.startswith(r, pos)), None)
        if redirection:
            end = pos + len(redirection)
            if not args or redirected or (end < len(command) and command[end] not in ' \t|'):
                raise ValueError('Unsupported redirection')
            stages[-1] = (args, True)
            pos = end
            continue
        if command[pos] == '|':
            if not args:
                raise ValueError('Empty pipeline stage')
            stages.append(([], False))
            pos += 1
            continue
        match = WORD.match(command, pos)
        if match is None or redirected:
            raise ValueError('Unsupported shell syntax')
        raw = match.group()
        word = shlex.split(raw)[0]
        unquoted = re.sub(r''' '[^']*' | "(?:[^"\\]|\\.)*" ''', '', raw, flags=re.X)
        if re.search(r'[*?\[]', unquoted):
            # A glob must not choose the executable or expand into executable/
            # output flags. Path-prefixed globs cannot introduce option words.
            prefix = re.split(r'[*?\[]', word, maxsplit=1)[0]
            pure_options = {'ls', 'cat', 'head', 'tail', 'wc', 'grep', 'egrep', 'fgrep', 'nl', 'cut', 'echo'}
            if not args or (program_name(args[0]) not in pure_options
                            and (prefix.startswith('-') or '/' not in prefix)):
                raise ValueError('Ambiguous shell glob')
        args.append(word)
        pos = match.end()
        if pos < len(command) and command[pos] not in ' \t\n|':
            raise ValueError('Unsupported word boundary')
    if not stages[-1][0]:
        raise ValueError('Empty command')
    return stages


def without_comments(command):
    if not isinstance(command, str):
        raise ValueError('Invalid shell input')
    result = []
    pos = 0
    while pos < len(command):
        match = WORD.match(command, pos)
        if match:
            result.append(match.group())
            pos = match.end()
        elif command[pos] == '#' and (pos == 0 or command[pos - 1] in ' \t\n;|&'):
            end = command.find('\n', pos)
            pos = len(command) if end == -1 else end
        else:
            result.append(command[pos])
            pos += 1
    return ''.join(result).strip()


def shell_parts(command, separators=('&&', '||', ';', '\n')):
    """Split only outside literal words; unsupported shell syntax fails closed."""
    if not isinstance(command, str) or len(command) > 32000 or '\x00' in command:
        raise ValueError('Invalid shell input')
    parts = []
    start = pos = 0
    while pos < len(command):
        separator = next((s for s in separators if command.startswith(s, pos)), None)
        if separator:
            part = command[start:pos]
            if separator == '\n' and part.rstrip().endswith('|'):
                pos += 1
                continue
            if not part.strip():
                if separator == '\n':
                    pos += 1
                    start = pos
                    continue
                raise ValueError('Empty command')
            parts.append((part, separator))
            pos += len(separator)
            start = pos
        elif any(command.startswith(r, pos) for r in READ_REDIRECTIONS):
            pos += len(next(r for r in READ_REDIRECTIONS if command.startswith(r, pos)))
        elif command.startswith('\\\n', pos):
            pos += 2
        elif command[pos] in ' \t|\n':
            pos += 1
        else:
            match = WORD.match(command, pos)
            if match is None:
                raise ValueError('Unsupported shell syntax')
            pos = match.end()
    if command[start:].strip():
        parts.append((command[start:], ''))
    elif not parts or parts[-1][1] not in {';', '\n'}:
        raise ValueError('Missing command')
    return parts


def read_options(args, flags='', long_flags=(), values=None):
    """Parse known options, including short bundles and attached values."""
    values = values or {}
    operands = []
    i = 0
    while i < len(args):
        word = args[i]
        if word == '--':
            return operands + args[i + 1:]
        if word == '-' or not word.startswith('-'):
            operands.append(word)
        elif word.startswith('--'):
            name, equal, value = word.partition('=')
            if name in long_flags and not equal:
                pass
            elif name in values:
                if not equal:
                    i += 1
                    if i == len(args):
                        return None
                    value = args[i]
                if not values[name](value):
                    return None
            else:
                return None
        else:
            for offset, flag in enumerate(word[1:], 1):
                name = '-' + flag
                if name in values:
                    value = word[offset + 1:]
                    if not value:
                        i += 1
                        if i == len(args):
                            return None
                        value = args[i]
                    if not values[name](value):
                        return None
                    break
                if flag not in flags:
                    return None
        i += 1
    return operands


GIT_INSPECTIONS = {'status', 'diff', 'log', 'show', 'ls-files', 'ls-tree',
                   'rev-parse', 'rev-list', 'show-ref', 'merge-base', 'describe', 'shortlog',
                   'grep', 'diff-tree', 'blame', 'cat-file', 'branch', 'tag', 'remote', 'worktree'}
GIT_GUARDS = ['--no-pager', '--no-optional-locks', '-c', 'core.fsmonitor=false',
              '-c', 'log.showSignature=false', '-c', 'format.pretty=medium',
              '-c', 'diff.submodule=short', '-c', 'status.verbose=false',
              '-c', 'log.diffMerges=separate']
GIT_PATCH_COMMANDS = {'diff', 'log', 'show', 'grep', 'blame', 'diff-tree'}


def git_action(args, allowed_config=()):
    """Locate the action without accepting aliases or arbitrary configuration."""
    i = 1
    while i < len(args):
        word = args[i]
        if word in {'-C', '--git-dir', '--work-tree', '--namespace'} and i + 1 < len(args):
            i += 2
        elif word.startswith('-C') and len(word) > 2:
            i += 1
        elif any(word.startswith(flag + '=') for flag in ('--git-dir', '--work-tree', '--namespace')):
            i += 1
        elif word in {'-P', '--no-pager', '--no-optional-locks', '--literal-pathspecs',
                      '--glob-pathspecs', '--noglob-pathspecs', '--icase-pathspecs', '--no-replace-objects'}:
            i += 1
        elif word == '-c' and i + 1 < len(args) and args[i + 1] in set(allowed_config) | {g for g in GIT_GUARDS if '=' in g}:
            i += 2
        elif word.startswith('-c') and word[2:] in allowed_config:
            i += 1
        else:
            return i
    return i


def git_pretty(value):
    # %G placeholders verify signatures with an external program. Named custom
    # formats can hide them in config; accept built-ins or explicit format text.
    if '%G' in value:
        return False
    return (value in {'', 'oneline', 'short', 'medium', 'full', 'fuller', 'reference',
                      'email', 'mboxrd', 'raw'} or value.startswith(('format:', 'tformat:'))
            or '%' in value)


def git_inspection(args):
    action_index = git_action(args)
    if action_index == len(args) or args[action_index] not in GIT_INSPECTIONS:
        return False
    action, rest = args[action_index], args[action_index + 1:]
    before_paths = rest[:rest.index('--')] if '--' in rest else rest
    # Check execution/output switches independently of option values as Git's
    # optional-argument spellings differ across subcommands. Include abbreviations.
    hazardous = {'--output', '--ext-diff', '--textconv', '--show-signature',
                 '--open-files-in-pager', '--help', '--config-env', '--exec-path'}
    for word in before_paths:
        key = word.partition('=')[0]
        if key.startswith('--') and any(h.startswith(key) for h in hazardous):
            return False
    anything = lambda value: True
    number = lambda value: re.fullmatch(r'\d+', value) is not None
    if action in {'branch', 'tag'}:
        listing = not rest or any(w.split('=', 1)[0] in {'--list', '-l', '--show-current',
            '--contains', '--no-contains', '--merged', '--no-merged', '--points-at'} for w in before_paths)
        operands = read_options(rest, 'larv',
            {'--list', '--all', '--remotes', '--verbose', '--show-current', '--no-column', '--no-color',
             '--contains', '--no-contains', '--merged', '--no-merged', '--points-at'},
            {k: anything for k in ('--sort', '--contains', '--no-contains', '--merged', '--no-merged', '--points-at')}
            | {'--format': lambda value: re.search(r'%\(\*?signature', value) is None})
        return operands is not None and (listing or not operands)
    if action == 'worktree':
        return rest[:1] == ['list'] and read_options(rest[1:], 'vz', {'--porcelain', '--verbose'}) == []
    if action == 'remote':
        if rest[:1] == ['get-url']:
            operands = read_options(rest[1:], long_flags={'--all', '--push'})
            return operands is not None and len(operands) == 1
        return read_options(rest, 'v', {'--verbose'}) == []
    if action == 'cat-file':
        return read_options(rest, 'pets', {'--batch', '--batch-check', '--buffer', '--unordered', '--allow-unknown-type'},
            {'--batch': anything, '--batch-check': anything}) is not None
    if action == 'grep':
        extras = {'--cached', '--untracked', '--no-index', '--exclude-standard',
                  '--no-exclude-standard', '--full-name', '--no-textconv', '--no-ext-diff',
                  '--and', '--or', '--not', '--all-match', '--break'}
        return read_file_command(['grep'] + [word for word in rest if word not in extras])
    if action == 'ls-files':
        return read_options(rest, 'zcdmousikvft',
            {'--cached', '--deleted', '--modified', '--others', '--ignored', '--stage',
             '--unmerged', '--killed', '--directory', '--no-empty-directory',
             '--exclude-standard', '--error-unmatch', '--full-name', '--recurse-submodules',
             '--deduplicate', '--eol', '--sparse'},
            {k: anything for k in ('-x', '-X', '--exclude', '--exclude-from',
                                   '--exclude-per-directory', '--with-tree', '--format')}) is not None
    if action == 'status':
        # Verbose status applies configured textconv drivers and has no
        # --no-textconv switch. Use a separate guarded diff to inspect patches.
        if any(word == '--verbose' or (word.startswith('-') and not word.startswith('--') and 'v' in word)
               for word in before_paths):
            return False
        # These short options take optional attached values, never another command.
        rest = [('--untracked-files=' + word[2:]) if re.fullmatch(r'-u(?:no|normal|all)', word)
                else ('--find-renames=' + word[2:]) if re.fullmatch(r'-M\d+%?', word) else word
                for word in rest]
        options = {'--short', '--branch', '--show-stash', '--ahead-behind', '--no-ahead-behind',
                   '--porcelain', '--long', '--null', '--no-verbose', '--no-renames',
                   '--untracked-files', '--ignored', '--ignore-submodules', '--column',
                   '--no-column', '--find-renames'}
        values = {k: anything for k in ('--porcelain', '--untracked-files', '--ignored',
                                       '--ignore-submodules', '--column', '--find-renames')}
        return read_options(rest, 'sbzuM', options, values) is not None
    # History, revision and patch inspection share the same data-only options.
    # --output, --ext-diff, --textconv, --show-signature and unknown/abbreviated
    # options deliberately have no entry. Everything after -- is a pathspec.
    options = set('''patch no-patch raw patch-with-raw patch-with-stat numstat shortstat
        check summary name-only name-status stat compact-summary binary full-index
        color no-color no-prefix minimal ignore-all-space ignore-space-change
        ignore-space-at-eol ignore-cr-at-eol ignore-blank-lines indent-heuristic
        no-indent-heuristic patience histogram find-renames find-copies break-rewrites
        find-copies-harder no-renames rename-empty follow relative no-relative text
        exit-code quiet no-ext-diff no-textconv cached staged no-index merge-base
        pickaxe-all pickaxe-regex cumulative dirstat dirstat-by-file word-diff
        color-words color-moved abbrev ignore-submodules submodule ita-invisible-in-index
        ita-visible-in-index oneline graph decorate no-decorate all branches tags remotes
        first-parent exclude-first-parent-only no-merges merges reverse date-order ancestry-path
        author-date-order topo-order boundary left-right cherry cherry-pick cherry-mark
        walk-reflogs full-history simplify-merges simplify-by-decoration dense sparse
        remove-empty full-diff no-walk do-walk pretty no-show-signature relative-date
        use-mailmap no-use-mailmap mailmap no-mailmap notes no-notes show-notes source
        regexp-ignore-case extended-regexp fixed-strings perl-regexp all-match invert-grep
        not single-worktree count objects objects-edge disk-usage header parents children
        timestamp bisect bisect-vars bisect-all left-only right-only no-object-names
        verify quiet short symbolic symbolic-full-name abbrev-ref show-toplevel show-prefix
        show-cdup git-dir absolute-git-dir git-common-dir is-inside-work-tree is-inside-git-dir
        is-bare-repository is-shallow-repository show-object-format show-superproject-working-tree
        local-env-vars sq sq-quote default since until end-of-options full-name name-only
        name-status object-only full-tree dereference head heads hash exists exclude-existing
        is-ancestor octopus independent fork-point always long exact-match contains dirty
        broken first-parent exclude untracked objects-edge-aggressive numbered email
        root no-commit-id line-porcelain porcelain incremental score-debug show-stats'''.split())
    options = {'--' + option for option in options}
    valued = '''unified stat stat-width stat-name-width stat-graph-width stat-count
        dirstat dirstat-by-file abbrev src-prefix dst-prefix line-prefix inter-hunk-context
        output-indicator-new output-indicator-old output-indicator-context break-rewrites
        find-renames find-copies ignore-matching-lines diff-algorithm anchored word-diff
        word-diff-regex color-words color-moved color-moved-ws relative ws-error-highlight
        ignore-submodules rotate-to skip-to find-object diff-filter max-count skip since after
        until before author committer grep grep-reflog min-parents max-parents date decorate
        decorate-refs decorate-refs-exclude branches tags remotes glob exclude exclude-hidden
        exclude-promisor-objects filter missing path-format git-path resolve-git-dir prefix
        default short abbrev-ref output-object-format hash format group max-age min-age
        match candidates dirty broken encoding notes show-notes log-size diff-merges contents'''.split()
    values = {'--' + option: anything for option in valued}
    values.update({k: anything for k in ('-S', '-G', '-O', '-I', '-L', '-X')})
    values.update({k: number for k in ('-n', '-U', '-l')})
    if action == 'shortlog':
        values.pop('-n')  # Numeric sorting is a flag here, not log's limit.
    values['--color'] = lambda value: value in {'always', 'never', 'auto'}
    values['--submodule'] = lambda value: value in {'short', 'log'}
    values['--diff-merges'] = lambda value: value in {'off', 'none', 'on', 'first-parent',
        'separate', 'combined', 'dense-combined', '1', 'm', 'c', 'cc'}
    values['--pretty'] = git_pretty
    values['--format'] = anything if action == 'ls-tree' else git_pretty
    values['--group'] = lambda value: (value in {'author', 'committer'} or value.startswith('trailer:')
        or (value.startswith('format:') and git_pretty(value)))
    # Numeric history limits and optional rename thresholds are complete tokens.
    normalized = []
    paths = False
    for word in rest:
        if word == '--':
            paths = True
        if not paths and re.fullmatch(r'-\d+', word) and action in {'log', 'show', 'rev-list', 'shortlog'}:
            word = '--max-count=' + word[1:]
        elif not paths and re.fullmatch(r'-[MCB]\d+(?:%|/\d+%?)?', word):
            word = {'M': '--find-renames=', 'C': '--find-copies=', 'B': '--break-rewrites='}[word[1]] + word[2:]
        normalized.append(word)
    return read_options(normalized, 'puWsazbRDCBMmqrcdtvflFienwg', options, values) is not None


def read_file_command(args):
    name, rest = program_name(args[0]), args[1:]
    anything = lambda value: True
    count = lambda value: re.fullmatch(r'[+-]?\d+', value) is not None
    if name == 'helm':
        return helm_inspection(rest)
    if name == 'find':
        return find_inspection(rest)
    if name == 'echo':
        return True
    if name == 'printf':
        # Bash printf -v assigns variables (including PATH), rather than printing.
        if rest[:1] == ['--']:
            rest = rest[1:]
        return (bool(rest) and not rest[0].startswith('-v')
                and re.search(r'%[-+ #0-9.*]*n', rest[0]) is None)
    if name in {'true', 'pwd'}:
        return read_options(rest, 'LP' if name == 'pwd' else '') == []
    if name == 'cd':
        operands = read_options(rest, 'LP')
        return operands is not None and len(operands) <= 1
    simple = {'ls': 'ABCFGHILOPRSTUW@abcdefghiklmnopqrstuwx1',
              'cat': 'AbEnstTuv', 'wc': 'clmwL'}
    if name in simple:
        return read_options(rest, simple[name]) is not None
    if name in {'nl', 'cut', 'tr'}:
        flags = {'nl': 'p', 'cut': 'nsz', 'tr': 'cdsCt'}[name]
        valued = {'nl': ('-b', '-d', '-f', '-h', '-i', '-l', '-n', '-s', '-v', '-w'),
                  'cut': ('-b', '-c', '-d', '-f', '--bytes', '--characters', '--delimiter', '--fields', '--output-delimiter'),
                  'tr': ()}[name]
        return read_options(rest, flags, {'--complement', '--only-delimited', '--zero-terminated'},
                            {k: anything for k in valued}) is not None
    if name == 'sort':
        return read_options(rest, 'bcdfghiMnRrsuVz',
            {'--unique', '--reverse', '--numeric-sort', '--human-numeric-sort', '--version-sort',
             '--general-numeric-sort', '--ignore-case', '--stable', '--zero-terminated'},
            {k: anything for k in ('-k', '-t', '--key', '--field-separator')}) is not None
    if name == 'uniq':
        operands = read_options(rest, 'cduiz', {'--count', '--repeated', '--unique', '--ignore-case'},
                                {k: anything for k in ('-f', '-s', '-w', '--skip-fields', '--skip-chars', '--check-chars')})
        return operands is not None and len(operands) <= 1  # A second operand is an output file.
    if name == 'jq':
        return json_filter(args, files=True)
    if name in {'head', 'tail'}:
        if rest and re.fullmatch(r'-\d+', rest[0]):
            rest = rest[1:]
        return read_options(rest, 'qv', values={k: count for k in ('-n', '-c', '--lines', '--bytes')}) is not None
    if name in {'grep', 'egrep', 'fgrep', 'rg'}:
        flags = 'EFGPScilnvrRqwxoHhsaIUVzZLbuN'
        if name == 'rg':
            flags = flags.replace('z', '')  # --search-zip can execute decompressors.
        long_flags = {'--files', '--hidden', '--no-ignore', '--no-ignore-vcs', '--no-config',
                      '--line-number', '--no-line-number', '--fixed-strings', '--ignore-case',
                      '--smart-case', '--invert-match', '--count', '--count-matches',
                      '--files-with-matches', '--files-without-match', '--only-matching',
                      '--word-regexp', '--line-regexp', '--recursive', '--no-heading',
                      '--heading', '--with-filename', '--no-filename', '--quiet', '--text',
                      '--null', '--null-data', '--stats'}
        values = {k: anything for k in ('-e', '-f', '-g', '-t', '-T', '--regexp', '--file',
                   '--glob', '--iglob', '--type', '--type-not', '--include', '--exclude',
                   '--exclude-dir', '--exclude-from')}
        values.update({k: count for k in ('-A', '-B', '-C', '-m', '--after-context',
                       '--before-context', '--context', '--max-count', '--max-depth')})
        values['--color'] = lambda value: value in {'always', 'never', 'auto'}
        return read_options(rest, flags, long_flags, values) is not None
    if name == 'sed':
        # Only numeric line/range printing. No script files, editing, reads,
        # writes, substitutions, or sed's shell execution commands.
        if rest[:1] != ['-n']:
            return False
        rest = rest[1:]
        if rest[:1] == ['-e']:
            rest = rest[1:]
        if not rest or not re.fullmatch(r'\s*(?:\d+|\$)(?:,(?:\d+|\$))?p\s*', rest[0]):
            return False
        return read_options(rest[1:]) is not None
    if name == 'git':
        return git_inspection(args)
    if name == 'kubectl':
        return kubectl_inspection(rest)
    return False


def helm_inspection(args):
    """Recognize local rendering and read-only release inspection."""
    i = 0
    prefix = []
    while i < len(args):
        word = args[i]
        key = word.split('=', 1)[0]
        if word == '--debug' or key in {'--namespace', '--kube-context', '--kubeconfig'} and '=' in word:
            prefix.append(word)
            i += 1
        elif word in {'-n', '--namespace', '--kube-context', '--kubeconfig'} and i + 1 < len(args):
            prefix.extend(args[i:i + 2])
            i += 2
        elif word.startswith('-n') and len(word) > 2:
            prefix.append(word)
            i += 1
        else:
            break
    if i >= len(args) or args[i] not in {'lint', 'template', 'list', 'ls', 'status'}:
        return False
    action = args[i]
    rest = prefix + args[i + 1:]
    local = lambda value: bool(value) and value != '-' and '://' not in value
    value = lambda item: bool(item) and not item.startswith('-')
    common_values = {'-n': value, '--namespace': value, '--kube-context': value, '--kubeconfig': local}
    common_flags = {'--help', '--debug'}
    if action in {'lint', 'template'}:
        flags = common_flags | {'--quiet', '--strict', '--with-subcharts', '--skip-schema-validation'} if action == 'lint' else (
            common_flags | {'--include-crds', '--skip-crds', '--skip-tests', '--no-hooks', '--is-upgrade',
                            '--hide-notes', '--render-subchart-notes', '--generate-name'})
        values = {**common_values, '-f': local, '--values': local,
                  '--set-file': lambda item: '=' in item and local(item.split('=', 1)[1]),
                  **{key: value for key in ('--set', '--set-string', '--set-json', '--set-literal', '--kube-version')}}
        if action == 'template':
            values.update({key: value for key in ('-a', '--api-versions', '-s', '--show-only', '--name-template')})
        operands = read_options(rest, 'hg' if action == 'template' else 'h', flags, values)
        if operands is None or not all(local(item) for item in operands):
            return False
        if action == 'template':
            # Avoid repository downloads: require an explicitly local chart.
            return (1 <= len(operands) <= 2 and
                    (operands[-1].startswith(('.', '/', '~')) or
                     ('/' not in operands[-1] and operands[-1].endswith('.tgz'))))
        return True
    output = lambda item: item in {'json', 'yaml', 'table'}
    if action in {'list', 'ls'}:
        operands = read_options(rest, 'aAdrhq',
            common_flags | {'--all', '--all-namespaces', '--date', '--deployed', '--failed', '--no-headers',
                            '--pending', '--reverse', '--short', '--superseded', '--uninstalled', '--uninstalling'},
            {**common_values, '-o': output, '--output': output,
             **{key: value for key in ('-f', '--filter', '-l', '--selector', '-m', '--max', '--offset', '--time-format')}})
        return operands == []
    operands = read_options(rest, 'h', common_flags | {'--show-desc', '--show-resources'},
                            {**common_values, '-o': output, '--output': output, '--revision': value})
    return operands is not None and len(operands) == 1


def find_inspection(args):
    """Read-only find expressions; execution and file-output actions have no entry."""
    i = 0
    while i < len(args) and re.fullmatch(r'-[HLPEXdsx]+', args[i]):
        i += 1
    # Paths precede the expression, including BSD's explicit -f path syntax.
    while i < len(args):
        if args[i] == '-f' and i + 1 < len(args):
            i += 2
        elif not args[i].startswith('-') and args[i] not in {'!', '(', ')', ','}:
            i += 1
        else:
            break
    flags = {'-print', '-print0', '-ls', '-quit', '-prune', '-empty', '-nouser',
             '-nogroup', '-readable', '-writable', '-executable', '-true', '-false',
             '-depth', '-xdev', '-mount', '-noleaf', '-follow', '-daystart',
             '-ignore_readdir_race', '-noignore_readdir_race', '-a', '-and',
             '-o', '-or', '-not', '!', '(', ')', ','}
    valued = {'-name', '-iname', '-path', '-ipath', '-wholename', '-iwholename',
              '-regex', '-iregex', '-regextype', '-type', '-xtype', '-maxdepth',
              '-mindepth', '-mtime', '-mmin', '-atime', '-amin', '-ctime', '-cmin',
              '-newer', '-anewer', '-cnewer', '-size', '-perm', '-user', '-group',
              '-uid', '-gid', '-inum', '-links', '-samefile', '-fstype', '-lname',
              '-ilname', '-printf'}
    while i < len(args):
        word = args[i]
        if word in flags:
            i += 1
        elif (word in valued or re.fullmatch(r'-newer[acmB][acmBt]', word)) and i + 1 < len(args):
            i += 2
        else:
            return False
    return True


def kubectl_inspection(args):
    # Read verbs with wildcard resource names/flags. Never permit raw API paths:
    # some streaming endpoints can execute commands even through an HTTP GET.
    valued = {'--context', '--namespace', '-n', '--kubeconfig', '--request-timeout', '-v'}
    flags = {'--all-namespaces', '-A'}
    i = 0
    while i < len(args) and args[i].startswith('-'):
        key, equal, _ = args[i].partition('=')
        if key in valued:
            i += 1 if equal else 2
        elif key in flags and not equal:
            i += 1
        else:
            return False
    if i >= len(args) or args[i] not in {'get', 'describe', 'logs', 'api-resources', 'api-versions', 'version'}:
        return False
    blocked = {'--raw', '--server', '--token', '--username', '--password', '--client-key',
               '--client-certificate', '--certificate-authority', '--profile', '--profile-output',
               '--log-file', '--log-dir', '--logtostderr', '-s'}
    return not any(word.split('=', 1)[0] in blocked or word.startswith('-s')
                   for word in args[i + 1:])


def locale_prefix(args):
    offset = 0
    while offset < len(args) and re.fullmatch(r'(?:LC_ALL|LANG|LC_CTYPE)=[A-Za-z0-9_.@-]+', args[offset]):
        offset += 1
    return offset


def read_pipeline(command, rules, scripts=()):
    stages = pipeline(command)
    first = stages[0][0][locale_prefix(stages[0][0]):]
    # A broad user-defined CLI rule must not accidentally approve a deployment.
    if first and program_name(first[0]) == 'helm' and not helm_inspection(first[1:]):
        return False, None
    if not first or not (read_query(first, rules) or read_file_command(first)
            or json_filter(first) or test_invocation(first) or trusted_script(stages[0][0], scripts)
            or routine_command(shlex.join(first))):
        return False, None
    if any(not (json_filter(args[locale_prefix(args):]) or read_file_command(args[locale_prefix(args):]))
           for args, _ in stages[1:] if args[locale_prefix(args):]):
        return False, None
    if any(not args[locale_prefix(args):] for args, _ in stages):
        return False, None
    # Insert isolation without re-quoting paths or changing shell semantics.
    rewritten = []
    changed = False
    for (part, separator), (args, _) in zip(shell_parts(command, ('|',)), stages):
        offset = locale_prefix(args)
        args = args[offset:]
        name = program_name(args[0])
        addition = ''
        if (re.fullmatch(r'python(?:3(?:\.\d+)?)?', name) and args[1:2] != ['-I']
                and not test_invocation(args) and not routine_command(shlex.join(args))):
            addition = ' -I'
        elif name == 'rg' and args[1:2] != ['--no-config']:
            addition = ' --no-config'
        elif name == 'git' and git_inspection(args) and args[1:1 + len(GIT_GUARDS)] != GIT_GUARDS:
            addition = ' ' + ' '.join(GIT_GUARDS)
        edits = []
        tokens = list(WORD.finditer(part))
        if addition:
            edits.append((tokens[offset].end(), addition))
        if name == 'git':
            action_index = git_action(args)
            guards = ['--no-textconv'] if args[action_index] in {'grep', 'blame'} else ['--no-ext-diff', '--no-textconv']
            if (args[action_index] in GIT_PATCH_COMMANDS
                    and args[action_index + 1:action_index + 1 + len(guards)] != guards):
                edits.append((tokens[offset + action_index].end(), ' ' + ' '.join(guards)))
        for end, insertion in sorted(edits, reverse=True):
            part = part[:end] + insertion + part[end:]
            changed = True
        rewritten.append(part + separator)
    return True, ''.join(rewritten) if changed else None

def jq_expression(expression):
    # jq has no shell execution primitive, but modules and extra input sources
    # are excluded. Reject even string literals containing these identifiers.
    return not re.search(r'\b(?:include|import|module|input|inputs|env|ENV|input_filename)\b', expression)

PURE_BUILTINS = {'print', 'len', 'str', 'int', 'float', 'bool', 'list', 'dict',
                 'tuple', 'set', 'sorted', 'enumerate', 'range', 'any', 'all',
                 'sum', 'min', 'max', 'abs', 'round', 'isinstance', 'open'}

DATA_METHODS = {'get', 'items', 'keys', 'values', 'lower', 'upper', 'strip',
                'lstrip', 'rstrip', 'startswith', 'endswith', 'split', 'join',
                'replace', 'count', 'index', 'read', 'readline', 'readlines'}

AST_TYPES = (ast.Module, ast.Import, ast.alias, ast.Assign, ast.Expr, ast.Call,
             ast.Name, ast.Load, ast.Store, ast.Attribute, ast.Constant,
             ast.Subscript, ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.Set,
             ast.ListComp, ast.GeneratorExp, ast.DictComp, ast.SetComp,
             ast.comprehension, ast.For, ast.If, ast.IfExp, ast.Compare,
             ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.And, ast.Or, ast.Not,
             ast.UAdd, ast.USub, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
             ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In,
             ast.NotIn, ast.Is, ast.IsNot, ast.keyword, ast.JoinedStr,
             ast.FormattedValue, ast.With, ast.withitem)

def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''

def python_filter(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, AST_TYPES):
            return False
        if isinstance(node, ast.Import) and any(a.name not in {'json', 'sys', 'os'} or a.asname for a in node.names):
            return False
        if isinstance(node, ast.Name):
            if node.id.startswith('_'):
                return False
            if isinstance(node.ctx, ast.Store) and node.id in PURE_BUILTINS | {'json', 'sys', 'os'}:
                return False
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return False
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and dotted(node.value).split('.')[0] in {'json', 'sys', 'os'}:
            return False
        if isinstance(node, ast.Attribute) and node.attr not in DATA_METHODS | {'load', 'loads', 'dumps', 'stdin', 'environ'}:
            return False
        if not isinstance(node, ast.Call):
            continue
        keywords = {k.arg for k in node.keywords}
        if None in keywords:
            return False
        name = dotted(node.func)
        if name == 'open':
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'mode'), ast.Constant('r'))
            if (not 1 <= len(node.args) <= 2 or keywords - {'mode', 'encoding', 'errors', 'newline'}
                    or not isinstance(mode, ast.Constant) or mode.value not in {'r', 'rt', 'rb'}):
                return False
        elif name == 'json.load':
            if len(node.args) != 1 or keywords:
                return False
        elif name == 'json.loads':
            if len(node.args) != 1 or keywords:
                return False
        elif name == 'json.dumps':
            if len(node.args) != 1 or keywords - {'indent', 'sort_keys', 'ensure_ascii', 'separators'}:
                return False
        elif name == 'sys.stdin.read':
            if node.args or keywords:
                return False
        elif isinstance(node.func, ast.Name):
            if name not in PURE_BUILTINS or (name == 'print' and keywords - {'sep', 'end'}):
                return False
        elif isinstance(node.func, ast.Attribute) and node.func.attr in DATA_METHODS:
            pass
        else:
            return False
    return True

def json_filter(args, files=False):
    name = program_name(args[0])
    rest = args[1:]
    if re.fullmatch(r'python(?:3(?:\.\d+)?)?', name):
        if rest[:1] == ['-I']:
            rest = rest[1:]
        return len(rest) == 2 and rest[0] == '-c' and python_filter(rest[1])
    if name != 'jq':
        return False
    while rest and rest[0].startswith('-'):
        flag = rest.pop(0)
        if flag in {'--raw-output', '--compact-output', '--exit-status', '--sort-keys', '--slurp', '--monochrome-output', '--null-input', '--raw-input', '--join-output'} or re.fullmatch(r'-[rceSMasnRj]+', flag):
            continue
        if flag in ({'--arg', '--argjson', '--rawfile', '--slurpfile'} if files else {'--arg', '--argjson'}) and len(rest) >= 2:
            rest = rest[2:]
            continue
        return False
    if files and '--' in rest:
        boundary = rest.index('--')
        return boundary == 1 and jq_expression(rest[0])
    return bool(rest) and jq_expression(rest[0]) and (len(rest) == 1 or (files and all(not a.startswith('-') for a in rest[1:])))


def query_policy():
    """Load user-owned CLI declarations; no executable code is loaded."""
    path = Path.home() / '.config/ai-workbench/claude-confirm.json'
    if not path.exists():
        return []
    if path.stat().st_size > 65536:
        raise ValueError('Read-query policy is too large')
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or set(data) not in ({'version', 'queries'}, {'version', 'queries', 'scripts'})
            or data['version'] != 1):
        raise ValueError('Expected a version 1 read-query policy')
    scripts = data.get('scripts', [])
    if not isinstance(scripts, list):
        raise ValueError('scripts must be a list')
    for script in scripts:
        if (not isinstance(script, dict) or set(script) != {'path', 'sha256', 'actions'}
                or not isinstance(script['path'], str) or not Path(script['path']).is_absolute()
                or not isinstance(script['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', script['sha256'])
                or not isinstance(script['actions'], list) or not script['actions']
                or any(a not in {'plan', 'check', 'status', 'inspect'} for a in script['actions'])):
            raise ValueError('Invalid reviewed script declaration')
    rules = data['queries']
    if not isinstance(rules, list):
        raise ValueError('queries must be a list')
    for rule in rules:
        required = {'prefix', 'flags', 'value_options', 'max_positionals'}
        if (not isinstance(rule, dict) or not required <= set(rule)
                or set(rule) - required - {'arguments', 'deny_words'}):
            raise ValueError('Invalid query declaration')
        if 'arguments' in rule and rule['arguments'] != '*':
            raise ValueError('arguments must be the literal wildcard *')
        for key in ('prefix', 'flags', 'value_options'):
            if not isinstance(rule[key], list) or not all(isinstance(s, str) and s for s in rule[key]):
                raise ValueError('Expected lists of literal words')
        prefix = rule['prefix']
        if 'deny_words' in rule and (rule.get('arguments') != '*' or not isinstance(rule['deny_words'], list)
                or not rule['deny_words'] or any(not isinstance(w, str) or not re.fullmatch(r'[A-Za-z0-9_+-]+', w)
                                                 for w in rule['deny_words'])):
            raise ValueError('deny_words must list literal command words for a wildcard query')
        if not prefix or not all(re.fullmatch(r'[A-Za-z0-9_+.-]+', s) for s in prefix):
            raise ValueError('Expected a literal command prefix')
        if prefix[0] in ASK_PROGRAMS | READ_PROGRAMS | {'git'} or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', prefix[0]):
            raise ValueError('Execution wrappers cannot be declared read-only')
        options = rule['flags'] + rule['value_options']
        if any(not re.fullmatch(r'--?[A-Za-z][A-Za-z0-9-]*', s) for s in options) or len(options) != len(set(options)):
            raise ValueError('Options must be unique flag names')
        if type(rule['max_positionals']) is not int or not 0 <= rule['max_positionals'] <= 10:
            raise ValueError('Invalid positional argument bound')
    return rules


def script_policy():
    path = Path.home() / '.config/ai-workbench/claude-confirm.json'
    return json.loads(path.read_text()).get('scripts', []) if path.exists() else []


def trusted_script(args, scripts):
    environment = {}
    while args and re.fullmatch(r'(?:LC_ALL|LANG|LC_CTYPE)=[A-Za-z0-9_.@-]+', args[0]):
        key, value = args[0].split('=', 1)
        environment[key] = value
        args = args[1:]
    if not args or not re.fullmatch(r'python(?:3(?:\.\d+)?)?', program_name(args[0])):
        return None
    args = args[1:]
    if args[:1] == ['-I']:
        args = args[1:]
    if len(args) < 2 or not Path(args[0]).is_absolute():
        return None
    path = Path(args[0]).resolve()
    for rule in scripts:
        patterns = {rule['path']}
        if not re.search(r'[*?\[]', rule['path']):
            patterns.add(str(Path(rule['path']).resolve()))
        if not any(fnmatch.fnmatchcase(candidate, pattern) for candidate in {str(path), args[0]}
                   for pattern in patterns) or args[1] not in rule['actions']:
            continue
        if any(a.split('=', 1)[0] in {'--apply', '--force', '--execute', '--config', '--namespace'} for a in args[2:]):
            return None
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != rule['sha256']:
            return None
        return {'argv': [str(path), *args[1:]], 'sha256': rule['sha256'], 'env': environment}
    return None


REPORT_CHAIN = re.compile(r'''\A\s*(?P<producer>[^;\n<>]+?)\s*>\s*(?P<output>[^;\n]+?)\s*;\s*
    (?P<rc>[A-Za-z_][A-Za-z0-9_]*)=\$\?\s*;\s*
    (?P<env>[A-Za-z_][A-Za-z0-9_]*)="\$(?P=rc)"\s+
    (?P<python>[A-Za-z0-9_./-]+)\s+-\s+<<\s*'(?P<tag>[A-Za-z_][A-Za-z0-9_]*)'\s*\n
    (?P<body>[\s\S]*?)\n(?P=tag)\s*\Z''', re.X)


def report_chain(command, scripts):
    """Recognize a reviewed plan -> temporary JSON -> read-only summary flow."""
    match = REPORT_CHAIN.fullmatch(command) if isinstance(command, str) else None
    if not match or match['tag'] in match['body'].splitlines():
        return None
    if not re.fullmatch(r'python(?:3(?:\.\d+)?)?', program_name(match['python'])) or not python_filter(match['body']):
        return None
    producer = pipeline(match['producer'])
    if len(producer) != 1 or producer[0][1]:
        return None
    approved = trusted_script(producer[0][0], scripts)
    output = shlex.split(match['output'])
    if not approved or len(output) != 1 or not WORD.fullmatch(match['output'].strip()):
        return None
    path = Path(output[0])
    if not path.is_absolute() or path.suffix != '.json':
        return None
    parent = path.parent.resolve()
    if parent not in {Path('/tmp').resolve(), Path(tempfile.gettempdir()).resolve()}:
        return None
    target = parent / path.name
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            return None
    spec = dict(approved, output=str(target), body=match['body'], rc_env=match['env'])
    # Execute argv directly, bind the exit status, and create the report without
    # following symlinks or truncating an unowned/hard-linked file. No shell eval.
    driver = '''import hashlib,json,os,stat,subprocess,sys
s=json.loads(SPEC)
assert hashlib.sha256(open(s['argv'][0],'rb').read()).hexdigest()==s['sha256'], 'Reviewed script changed'
env=dict(os.environ,**s['env'])
fd=os.open(s['output'],os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
info=os.fstat(fd)
assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1, 'Unsafe report target'
os.ftruncate(fd,0)
with os.fdopen(fd,'w') as report:
 result=subprocess.run([sys.executable,'-I',*s['argv']],stdout=report,env=env)
env[s['rc_env']]=str(result.returncode if result.returncode>=0 else 128-result.returncode)
sys.exit(subprocess.run([sys.executable,'-I','-c',s['body']],stdin=subprocess.DEVNULL,env=env).returncode)
'''.replace('SPEC', repr(json.dumps(spec)))
    return shlex.join([sys.executable, '-I', '-c', driver])


def read_query(args, rules):
    words = [program_name(args[0])] + args[1:]
    for rule in rules:
        prefix = rule['prefix']
        flags = set(rule['flags'])
        valued = set(rule['value_options'])
        if words[0] != prefix[0]:
            continue
        i = 1
        before = []
        matched = True
        for expected in prefix[1:]:
            while i < len(words) and words[i].split('=', 1)[0] in flags | valued:
                key, equal, _ = words[i].partition('=')
                before.append(words[i])
                i += 1
                if key in valued and not equal:
                    if i == len(words):
                        matched = False
                        break
                    before.append(words[i])
                    i += 1
            if not matched or i == len(words) or words[i] != expected:
                matched = False
                break
            i += 1
        if not matched:
            continue
        rest = before + words[i:]
        wildcard = rule.get('arguments') == '*'
        if wildcard:
            denied = {w.lower().lstrip('+') for w in rule.get('deny_words', [])}
            literal_words = [w.lower().split('=', 1)[0].lstrip('-+') for w in rest]
            if denied.intersection(literal_words):
                return False
            # Mentions in comment or message operations can notify a person.
            if (any(w in {'comment', 'comments', 'message', 'messages', 'reply', 'replies'}
                    for w in literal_words) and any('@' in w for w in rest)):
                return False
            blocked = {'--output', '--out', '--output-file', '--write', '--write-back',
                       '--in-place', '--exec', '--command', '--shell', '--pre', '--yes',
                       '--force', '--method', '--http-method', '--request', '--params',
                       '--set', '--data', '--body', '-o', '-i', '-y', '-X', '-P'}
            blocked |= {'--url', '--base-url', '--endpoint', '--proxy', '--api-url',
                        '--token', '--access-token', '--api-key', '--auth-token', '--authorization',
                        '--edit', '--delete', '--remove', '--update', '--patch', '--apply', '--execute',
                        '--run', '--deploy', '--submit', '--commit', '--push', '--replace'}
            for word in rest:
                if word == '--':
                    break
                key = word.split('=', 1)[0]
                if key not in flags | valued and (key in blocked or
                        (key.startswith('--') and any(b.startswith(key) for b in blocked))):
                    return False
        positions = rule['max_positionals']
        i = 0
        while i < len(rest):
            key, equal, value = rest[i].partition('=')
            if key in flags and not equal:
                i += 1
                continue
            if key in valued:
                if not equal:
                    i += 1
                    if i == len(rest):
                        return False
                    value = rest[i]
                if value.startswith('-') and not re.fullmatch(r'-\d+', value):
                    return False
                if key in {'--jq', '-q'} and not jq_expression(value):
                    return False
            elif wildcard:
                pass
            elif not rest[i].startswith('-') and positions:
                positions -= 1
            else:
                return False
            i += 1
        return True
    return False


def git_fetch(args):
    """Recognize ordinary fetches, leaving overrides to the client's permissions."""
    index = git_action(args, {'gc.auto=0'})
    if index >= len(args) or args[index] != 'fetch':
        return False
    positive = lambda value: bool(re.fullmatch(r'[1-9][0-9]*', value))
    operands = read_options(args[index + 1:], 'vqant46', {
        '--all', '--append', '--atomic', '--tags', '--no-tags', '--verbose', '--quiet',
        '--progress', '--dry-run', '--ipv4', '--ipv6', '--unshallow',
        '--no-recurse-submodules', '--no-auto-maintenance', '--no-auto-gc',
    }, {'--depth': positive, '--deepen': positive, '--jobs': positive, '-j': positive})
    return operands is not None and all(value and not value.startswith(('-', '+')) for value in operands)


def routine_command(command):
    """Approve an ordinary fetch, push or direct script invocation, not shell wrappers.

    Script contents are not inspected. A script can perform any operation.
    """
    try:
        parts = shell_parts(command)
        if len(parts) != 1 or parts[0][1]:
            return False
        stages = pipeline(parts[0][0])
        if len(stages) != 1 or stages[0][1]:
            return False
        args = stages[0][0]
        args = args[locale_prefix(args):]
        if not args:
            return False
        name = program_name(args[0])
        if name == 'git':
            if git_fetch(args):
                return True
            i = git_action(args)
            if i >= len(args) or args[i] != 'push':
                return False
            # Deleting a remote ref remains an explicit destructive operation.
            return not any(a in {'-d', '--delete', '--mirror', '--prune'} or a.startswith('--delete=')
                           or (a.startswith('--') and len(a) > 2 and any(
                               flag.startswith(a.split('=', 1)[0]) for flag in ('--delete', '--mirror', '--prune')))
                           or (a.startswith('-') and not a.startswith('--') and 'd' in a[1:])
                           or (':' in a and a.split(':', 1)[0].lstrip('+') == '')
                           for a in args[i + 1:])
        if args[:2] == ['uv', 'run']:
            args = args[2:]
            while args and args[0] in {'--offline', '--no-sync', '--frozen', '--no-env-file'}:
                args = args[1:]
            if not args:
                return False
            name = program_name(args[0])
        if not (re.fullmatch(r'python(?:3(?:\.\d+)?)?', name)
                or name in {'node', 'nodejs', 'bash', 'sh', 'zsh'}):
            return False
        rest = args[1:]
        if name.startswith('python'):
            while rest and rest[0] in {'-B', '-u', '-I', '-O', '-OO'}:
                rest = rest[1:]
        if rest[:1] == ['--']:
            rest = rest[1:]
        return bool(rest) and not rest[0].startswith('-') and bool(re.search(r'\.(?:py|js|mjs|cjs|sh)$', rest[0]))
    except (ValueError, IndexError):
        return False


def ssh_command(command, rules, scripts):
    """Apply the same decisions to a direct SSH remote shell command."""
    try:
        parts = shell_parts(command)
        if len(parts) != 1 or parts[0][1]:
            return None
        stages = pipeline(parts[0][0])
        if len(stages) != 1 or stages[0][1]:
            return None
        args = stages[0][0]
        if not args or program_name(args[0]) != 'ssh':
            return None
        i = 1
        while i < len(args) and args[i].startswith('-'):
            if args[i] in {'-p', '-l', '-i'} and i + 1 < len(args):
                i += 2
            elif args[i] in {'-T', '-t', '-q', '-n', '-4', '-6'}:
                i += 1
            else:
                return 'ask', None
        if i + 1 >= len(args):
            return 'ask', None
        # ssh joins command arguments with spaces before passing them to the
        # remote shell. Preserve that meaning in the checked remote command.
        prefix, remote = args[:i + 1], ' '.join(args[i + 1:])
        if re.match(r'\s*(?:/usr/bin/|/bin/)?ssh(?:\s|$)', remote):
            return 'ask', None
        decision, updated = decide(remote, rules, scripts, allow_ssh=False)
        if decision != 'allow':
            return 'ask', None
        rewritten = shlex.join(prefix) + ' ' + shlex.quote(updated or remote)
        return 'allow', rewritten
    except (ValueError, IndexError):
        return None


def literal_loop_body(body, variable, value):
    """Replace only this loop variable outside single-quoted shell literals."""
    out = []
    quote = None
    pos = 0
    while pos < len(body):
        char = body[pos]
        if char == "'" and quote != '"':
            quote = None if quote == "'" else "'"
        elif char == '"' and quote != "'":
            quote = None if quote == '"' else '"'
        elif char == '\\' and quote != "'":
            if pos + 1 == len(body):
                raise ValueError('Incomplete escape')
            out.append(body[pos:pos + 2])
            pos += 2
            continue
        elif char == '#' and quote is None:
            raise ValueError('Comments in loop bodies are unsupported')
        elif char == '$' and quote != "'":
            match = re.match(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))', body[pos:])
            if not match or (match.group(1) or match.group(2)) != variable:
                raise ValueError('Unsupported variable expansion')
            out.append(value)
            pos += match.end()
            continue
        out.append(char)
        pos += 1
    if quote:
        raise ValueError('Unclosed quote')
    return ''.join(out)


def literal_for_loop(command, rules, scripts):
    """Rewrite bounded literal loops after checking every expanded iteration."""
    if not isinstance(command, str) or len(command) > 32000 or '\x00' in command:
        return None
    match = re.fullmatch(
        r'\s*(?:(?P<prefix>.*?)\s*&&\s*)?for[ \t]+(?P<var>[a-z][a-z0-9_]{0,31})'
        r'[ \t]+in[ \t]+(?P<items>[^;\n]+?)[ \t]*;[ \t\n]*do[ \t\n]+'
        r'(?P<body>.*?);[ \t\n]*done[ \t]*;?[ \t]*', command, re.S)
    if not match:
        return None
    if match.group('body').rstrip().endswith(';'):
        return 'ask', None
    word = r'''(?:[A-Za-z0-9_./:+-]+|'[A-Za-z0-9_./:+-]+'|"[A-Za-z0-9_./:+-]+")'''
    items = match.group('items')
    if not re.fullmatch(word + r'(?:[ \t]+' + word + r')*', items.strip()):
        return 'ask', None
    values = shlex.split(items)
    if not 1 <= len(values) <= 32:
        return 'ask', None
    prefix = match.group('prefix')
    if prefix:
        decision, updated = decide(prefix, rules, scripts, allow_loop=False)
        if decision != 'allow':
            return 'ask', None
        prefix = (updated or prefix).strip() + ' && '
    else:
        prefix = ''
    branches = []
    try:
        for value in values:
            body = literal_loop_body(match.group('body'), match.group('var'), value)
            decision, updated = decide(body, rules, scripts, allow_loop=False)
            if decision != 'allow':
                return 'ask', None
            branches.append(shlex.quote(value) + ') ' + (updated or body).strip() + ' ;;')
    except (ValueError, IndexError):
        return 'ask', None
    rewritten = (prefix + 'for ' + match.group('var') + ' in ' + items.strip()
                 + '; do case "$' + match.group('var') + '" in '
                 + ' '.join(branches) + ' esac; done')
    return ('allow', rewritten) if len(rewritten) <= 32000 else ('ask', None)


def decide(command, rules, scripts=(), allow_ssh=True, allow_loop=True):
    original = command
    if allow_loop:
        loop = literal_for_loop(command, rules, scripts)
        if loop is not None:
            return loop
    try:
        report = report_chain(command, scripts)
        if report is not None:
            return 'allow', report
        command = without_comments(command)
    except ValueError:
        return 'ask', None
    if allow_ssh:
        ssh = ssh_command(command, rules, scripts)
        if ssh is not None:
            return ssh
    if routine_command(command):
        return 'allow', command if command != original else None
    if is_test_command(command):
        return 'allow', command if command != original else None
    try:
        parts = shell_parts(command)
        checked = [read_pipeline(part, rules, scripts) for part, _ in parts]
        if all(allowed for allowed, _ in checked):
            updated = ''.join((replacement if replacement is not None else part) + separator
                              for (part, separator), (_, replacement) in zip(parts, checked))
            return 'allow', updated if updated != original else None
        if len(parts) > 1 or parts[0][1]:
            return 'ask', None
        stages = pipeline(command)
    except ValueError:
        return 'ask', None
    if len(stages) > 1:
        return 'ask', None
    args = stages[0][0]
    name = program_name(args[0])
    if name == 'git':
        if len(args) > 1 and args[1] in {'add', 'commit', 'fetch'}:
            if not any(a.startswith(('--output', '--ext-diff', '--exec-path', '--amend')) for a in args[2:]):
                return None, None
        return 'ask', None
    query_programs = {rule['prefix'][0] for rule in rules}
    if not name or '=' in args[0] or name in ASK_PROGRAMS | READ_PROGRAMS | query_programs | {'lark-cli', 'helm'} or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', name):
        return 'ask', None
    return None, None


def main():
    if sys.argv[1:] == ['--check-policy']:
        try:
            query_policy()
        except (OSError, ValueError, TypeError):
            print('Invalid read-query policy', file=sys.stderr)
            return 1
        print('Read-query policy valid')
        return 0
    updated = None
    try:
        event = json.load(sys.stdin)
        tool = event.get('tool_name')
        if tool not in {'Bash', 'PowerShell'}:
            return 0
        rules = query_policy()
        decision, updated = decide(event.get('tool_input', {}).get('command'), rules, script_policy()) if tool == 'Bash' else (None, None)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return 0
    # The hook only grants known approvals; Claude handles all other decisions.
    if decision != 'allow':
        return 0
    result = {'hookEventName': 'PreToolUse', 'permissionDecision': decision,
              'permissionDecisionReason': 'Recognized test, read-only inspection, or configured query with filters.'}
    if updated is not None:
        result['updatedInput'] = dict(event['tool_input'], command=updated)
    print(json.dumps({'hookSpecificOutput': result}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
