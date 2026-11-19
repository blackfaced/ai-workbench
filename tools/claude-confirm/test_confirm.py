import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HOOK = Path(__file__).with_name('confirm.py')

def decision(command, tool='Bash'):
    event = {'tool_name': tool, 'tool_input': {'command': command}}
    with tempfile.TemporaryDirectory() as directory:
        run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                             text=True, capture_output=True, check=True,
                             env=dict(os.environ, HOME=directory))
    return json.loads(run.stdout)['hookSpecificOutput']['permissionDecision'] if run.stdout else None

class HookTests(unittest.TestCase):
    def test_branch_and_worktree_creation(self):
        for command in [
            'git branch feature/example', 'git branch feature/example origin/main',
            'git branch --track feature/example origin/main',
            'git -C /tmp -Cexample branch --no-track --create-reflog feature/example HEAD',
            'git switch -c feature/example', 'git switch --create=feature/example origin/main',
            'git switch -qcfeature/example --track=direct origin/main',
            'git checkout -b feature/example', 'git checkout -qbfeature/example origin/main',
            'git worktree add /tmp/new', 'git worktree add /tmp/new existing-branch',
            'git worktree add -b feature/example /tmp/new origin/main',
            'git worktree add -bfeature/example --track /tmp/new origin/main',
            'git worktree add --detach --no-checkout /tmp/new HEAD',
            'git worktree add --lock --reason "temporary checkout" /tmp/new HEAD',
            'git -C /tmp/example -c gc.auto=0 fetch origin main && '
            'git -C /tmp/example worktree add -b fix/example /tmp/new origin/main',
            'git worktree add -b fix/example /tmp/new HEAD 2>&1 | tail -10',
            'git branch fix/example && git branch --list',
            'for name in feature/a feature/b; do git branch "$name"; done',
            "ssh devbox 'git -C /tmp/example worktree add -b fix/example /tmp/new HEAD'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(decision(command), 'allow')

    def test_branch_and_worktree_overrides_defer_without_hook_restrictions(self):
        for command in [
            'git branch --force existing HEAD', 'git branch -f existing HEAD',
            'git branch -D existing', 'git branch -m old new', 'git branch -C old new',
            'git switch -C existing HEAD', 'git switch --force-create existing',
            'git switch -c new --discard-changes', 'git switch -c new --merge',
            'git checkout -B existing HEAD', 'git checkout -b new -f',
            'git checkout -b new --pathspec-from-file=/tmp/paths',
            'git worktree add --force /tmp/new main', 'git worktree add -B existing /tmp/new HEAD',
            'git worktree remove /tmp/new', 'git worktree prune', 'git worktree move /tmp/a /tmp/b',
            'git worktree add -b one -b two /tmp/new', 'git worktree add -b',
            'git worktree add', 'git switch -c', 'git switch -c one -c two',
            'git branch one HEAD extra', 'git worktree add /tmp/new HEAD extra',
            'git -c core.hooksPath=/tmp/hooks worktree add /tmp/new',
            'git worktree add /tmp/new && rm -rf example',
            'git worktree add /tmp/new | sh', 'git branch new > /tmp/result',
        ]:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))

    def test_creation_approval_executes_in_temporary_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, tree = root / 'source', root / 'new worktree'
            repo.mkdir()
            env = dict(os.environ, HOME=directory, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(path, *args):
                return subprocess.run(['git', '-C', str(path), *args], env=env,
                                      capture_output=True, text=True, check=True)
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.name', 'Example User')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            git(repo, 'config', 'core.hooksPath', os.devnull)
            git(repo, 'config', 'commit.gpgSign', 'false')
            (repo / 'sample.txt').write_text('committed\n')
            git(repo, 'add', 'sample.txt')
            git(repo, 'commit', '-qm', 'Example')
            commit = git(repo, 'rev-parse', 'HEAD').stdout
            prefix = 'git -C ' + shlex.quote(str(repo)) + ' '
            for suffix in ['branch created HEAD', 'switch -c switched HEAD',
                           'checkout -b checked HEAD',
                           'worktree add -b linked ' + shlex.quote(str(tree)) + ' HEAD']:
                command = prefix + suffix
                result = invoke(HOOK, command)
                self.assertEqual(result.get('permissionDecision'), 'allow')
                subprocess.run(result.get('updatedInput', {}).get('command', command),
                               shell=True, executable='/bin/bash', env=env,
                               capture_output=True, text=True, check=True)
            for branch in ['created', 'switched', 'checked', 'linked']:
                self.assertEqual(git(repo, 'rev-parse', branch).stdout, commit)
            self.assertEqual(git(repo, 'branch', '--show-current').stdout.strip(), 'checked')
            self.assertEqual(git(tree, 'branch', '--show-current').stdout.strip(), 'linked')
            self.assertEqual((tree / 'sample.txt').read_text(), 'committed\n')

    def test_fetch_with_repository_options_and_composition(self):
        for command in [
            'git fetch', 'git fetch origin feature/example',
            'git -C /tmp/example fetch origin main',
            'git -C /tmp -Cexample -c gc.auto=0 fetch origin main',
            'git -cgc.auto=0 -C /tmp/example fetch --tags origin',
            'git fetch --all --no-tags --verbose',
            'git fetch --depth=1 --deepen 2 --jobs=2 origin main',
            'git fetch --no-auto-maintenance --no-recurse-submodules origin',
            'git -C /tmp/example fetch origin main 2>&1 | tail -20',
            'cd /tmp/example && git fetch origin main && git status --short',
            "for remote in origin upstream; do git fetch \"$remote\"; done",
            "ssh devbox 'git -C /tmp/example -c gc.auto=0 fetch origin main'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(decision(command), 'allow')

    def test_fetch_does_not_approve_overrides_or_unrecognized_chains(self):
        for command in [
            'git fetch --prune', 'git fetch -p', 'git fetch --prune-tags',
            'git fetch --force origin main', 'git fetch -f origin main',
            'git fetch origin +main:refs/heads/main', 'git fetch --update-head-ok',
            'git fetch --upload-pack=/tmp/helper origin', 'git fetch --stdin',
            'git fetch --depth', 'git fetch --depth=-1 origin',
            'git -c core.sshCommand=/tmp/helper fetch origin main',
            'git -c alias.download=fetch download origin main',
            'git --exec-path=/tmp fetch origin main',
            'git fetch origin main && rm -rf example',
            'git fetch origin main && git worktree remove /tmp/new',
            'git fetch origin main | sh', 'git fetch origin main > /tmp/result',
        ]:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))

    def test_fetch_approval_executes_against_local_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            env = dict(os.environ, HOME=directory, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(path, *args):
                return subprocess.run(['git', '-C', str(path), *args], env=env,
                                      capture_output=True, text=True, check=True)
            for repo in (source, target):
                repo.mkdir()
                git(repo, 'init', '-q')
                git(repo, 'config', 'core.hooksPath', os.devnull)
                git(repo, 'config', 'commit.gpgSign', 'false')
            git(source, 'config', 'user.name', 'Example User')
            git(source, 'config', 'user.email', 'test@example.invalid')
            git(source, 'commit', '--allow-empty', '-qm', 'Example')
            git(source, 'branch', 'example')
            git(target, 'remote', 'add', 'origin', str(source))
            command = 'git -C ' + shlex.quote(str(target)) + ' -c gc.auto=0 fetch origin example'
            result = invoke(HOOK, command)
            self.assertEqual(result['permissionDecision'], 'allow')
            executed = result.get('updatedInput', {}).get('command', command)
            subprocess.run(executed, shell=True, executable='/bin/bash', env=env,
                           capture_output=True, text=True, check=True)
            self.assertEqual(git(target, 'rev-parse', 'FETCH_HEAD').stdout,
                             git(source, 'rev-parse', 'example').stdout)

    def test_routine_push_scripts_ssh_and_sensitive_operations(self):
        allowed = ['git push', 'git -C /tmp/example push --force origin main',
                   'python3 script.py', 'bash script.sh', 'node script.js',
                   'uv run --no-sync python script.py',
                   "ssh devbox 'git status --short'", 'ssh devbox git push',
                   "ssh -p 22 devbox 'python3 script.py'"]
        blocked = ['rm -rf example', 'git push --delete origin old',
                   'git push --prune origin', 'git push origin :old',
                   'gh pr merge 1', 'lark-cli im message +send --text hello',
                   "ssh devbox 'rm -rf example'", "ssh devbox 'gh pr merge 1'",
                   "ssh devbox 'lark-cli im message +send --text hello'",
                   'ssh -o ProxyCommand=example devbox git status',
                   "ssh devbox 'git push; rm -rf example'"]
        for command in allowed:
            with self.subTest(command=command):
                self.assertEqual(decision(command), 'allow')
        for command in blocked:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))

    def test_discovery_and_chains(self):
        command = "PYTHONPATH=src:scripts .venv/bin/python -m unittest discover -s tests -p 'test_example.py' -v"
        self.assertEqual(decision(command), 'allow')
        self.assertEqual(decision(command + ' && ' + command), 'allow')
        self.assertEqual(decision("python3 -m unittest discover -s tests -p 'test_*.py'"), 'allow')

    def test_files_runners_and_selectors(self):
        for command in ['python3 test_x.py', '.venv/bin/python tools/tests/test_x.py -v',
                        'python3 -- "/tmp/test_spaced file.py"', 'python -m unittest',
                        'python3 -m unittest -v tests.test_x.Suite', 'python -m unittest discover',
                        'pytest', '.venv/bin/pytest -q tests/test_x.py::Suite::test_one',
                        'python3 -m pytest tests && pytest -q', "PYTHONPATH=src pytest -k 'smoke and (fast or local)'",
                        'uv run --no-sync python -B -m pytest', 'uv run pytest tests']:
            with self.subTest(command=command):
                self.assertEqual(decision(command), 'allow')

    def test_non_test_segments_and_wrappers(self):
        for command in ['python3 -c "import os; os.system(\'git push\')"', 'python3 -m other',
                        'pytest | sh', 'pytest > log', 'pytest & git status',
                        'pytest $(date)', 'pytest ; rm a',
                        'pytest &&', 'python -m pytest_extra', 'python3 -test_x.py']:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))

    def test_defer_other_commands(self):
        base = "python3 -m unittest discover -s tests -p 'test_example.py'"
        for command in [base + '; rm -rf build',
                        'python3 -c "import os; os.system(\'git push\')"', base + ' $(echo x)']:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))
        self.assertIsNone(decision('dir', 'PowerShell'))
        self.assertEqual(decision('ls'), 'allow')
        self.assertEqual(decision('echo pytest'), 'allow')


@unittest.skipUnless(hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'getuid'), 'requires POSIX file checks')
class TimingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = Path(directory.name) / 'state'
        self.log = state / 'ai-workbench' / 'claude-confirm-timing.jsonl'
        self.env = dict(os.environ, HOME=directory.name, XDG_STATE_HOME=str(state))
        self.env.pop('AIWB_CLAUDE_CONFIRM_TIMING', None)

    def invoke_hook(self, command, enabled=None, args=()):
        env = self.env.copy()
        if enabled is not None:
            env['AIWB_CLAUDE_CONFIRM_TIMING'] = enabled
        event = {'tool_name': 'Bash', 'tool_input': {'command': command}}
        return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(event),
                              env=env, text=True, capture_output=True, timeout=5, check=True).stdout

    def test_timing_requires_explicit_opt_in(self):
        stdout = self.invoke_hook('git status --short')
        self.assertEqual(json.loads(stdout)['hookSpecificOutput']['permissionDecision'], 'allow')
        self.assertEqual(self.invoke_hook('git status --short', '0'), stdout)
        self.assertFalse(self.log.parent.exists())

    def test_timing_records_stages_and_preserves_decisions(self):
        command = 'git status --short'
        self.assertEqual(self.invoke_hook(command, '1'), self.invoke_hook(command))
        self.assertEqual(self.invoke_hook('unrecognized-command', '1'), '')
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([row['stage'] for row in rows], [
            'process_start', 'stdin_wait', 'stdin_read', 'result_write_start', 'result_written', 'exit',
            'process_start', 'stdin_wait', 'stdin_read', 'exit',
        ])
        for call in (rows[:6], rows[6:]):
            elapsed = [row['elapsed_ms'] for row in call]
            self.assertEqual(elapsed[0], 0)
            self.assertEqual(elapsed, sorted(elapsed))
            self.assertEqual(len({row['pid'] for row in call}), 1)
            for row in call:
                self.assertEqual(set(row), {'pid', 'ppid', 'stage', 'time_unix_ns', 'elapsed_ms'})
        self.assertEqual(self.log.stat().st_mode & 0o077, 0)

    def test_unavailable_log_preserves_decision(self):
        self.log.parent.mkdir(parents=True)
        target = self.log.with_name('existing.jsonl')
        target.write_text('keep this')
        self.log.symlink_to(target)
        self.assertEqual(self.invoke_hook('git status --short', '1'), self.invoke_hook('git status --short'))
        self.assertEqual(target.read_text(), 'keep this')

    def test_policy_check_does_not_start_timing(self):
        self.assertIn('Read-query policy valid', self.invoke_hook('', '1', args=('--check-policy',)))
        self.assertFalse(self.log.parent.exists())


SPEC = importlib.util.spec_from_file_location('readonly_queries', HOOK)

policy = importlib.util.module_from_spec(SPEC)

SPEC.loader.exec_module(policy)

RULES = [
    {'prefix': ['example-cli', 'catalog', 'entries', 'list'],
     'flags': ['--json', '--refresh', '-j'], 'value_options': ['--jq'], 'max_positionals': 0},
    {'prefix': ['example-cli', 'inventory', 'items', 'list'],
     'flags': ['--json'], 'value_options': ['--group', '--item-ids'], 'max_positionals': 0},
    {'prefix': ['document-cli', 'files', '+fetch'],
     'flags': ['--json'], 'value_options': ['--name', '--limit'], 'max_positionals': 0},
    {'prefix': ['document-cli', 'files', '+search'],
     'flags': ['--json', '--mine'], 'value_options': ['--query'], 'max_positionals': 0},
]

def decide(command):
    return policy.decide(command, RULES)

QUERY = 'example-cli catalog entries list -j'

FILTER = "import json,sys; d=json.load(sys.stdin); print('\\n'.join(x.get('name','') for x in (d.get('data',{}).get('items') or []) if 'alpha' in x.get('name','').lower() or 'beta' in x.get('name','').lower()))"

FILTER_PIPELINE = QUERY + ' 2>&1 | python3 -c "' + FILTER + '"'

def invoke(script, command, mode='acceptEdits', tool='Bash'):
    event = {'tool_name': tool, 'tool_input': {'command': command, 'timeout': 1000},
             'permission_mode': mode, 'cwd': '/tmp', 'hook_event_name': 'PreToolUse'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / '.config/ai-workbench/claude-confirm.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'version': 1, 'queries': RULES}))
        result = subprocess.run([sys.executable, '-B', str(script)],
                                input=json.dumps(event), text=True, capture_output=True,
                                timeout=5, check=True, env=dict(os.environ, HOME=directory))
    return json.loads(result.stdout)['hookSpecificOutput'] if result.stdout else {}

class QueryPermissionTests(unittest.TestCase):
    def test_hook_protocol_only_returns_allow_or_defers_in_all_modes(self):
        commands = [
            ('ls', 'allow'),
            ('git push', 'allow'),
            ('git -C /tmp/example -c gc.auto=0 fetch origin main', 'allow'),
            ("python3 -c 'import yaml; print(yaml.__file__)'", None),
            ("python3 -c 'import yaml; print(yaml.__file__)' 2>&1; "
             "/usr/bin/python3 -c 'import yaml; print(yaml.__file__)' 2>&1", None),
            ('rm -rf example', None),
            ('gh pr merge 1', None),
            ('lark-cli im message +send --text hello', None),
            ('helm upgrade demo ./chart', None),
            ('git -C /tmp/example worktree add -b fix/example /tmp/new HEAD', 'allow'),
            ('git switch -c fix/example', 'allow'),
            ('git branch fix/example', 'allow'),
            ('git checkout -b fix/example', 'allow'),
            ('for b in a b; do rm -rf "$b"; done', None),
            ('unrecognized-command --option', None),
        ]
        for mode in ['default', 'acceptEdits', 'auto', 'bypassPermissions', 'dontAsk']:
            for command, expected in commands:
                with self.subTest(mode=mode, command=command):
                    result = invoke(HOOK, command, mode)
                    self.assertEqual(result.get('permissionDecision'), expected)
                    self.assertNotIn(result.get('permissionDecision'), {'ask', 'deny'})

    def test_helm_template_and_release_inspection_without_deployment(self):
        for command in [
            'helm template demo ./chart --include-crds --values /tmp/values.yaml',
            'helm template ./chart --set image.tag=example | grep kind',
            'helm --namespace demo template demo ./chart --api-versions example/v1',
            'helm list -A -o json | jq .',
            'helm --namespace demo ls --filter example --max 20',
            'helm --kube-context demo status release -n demo -o yaml --show-resources',
            'bash /tmp/example/test.sh && helm template demo ./chart && helm list -n demo',
        ]:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')
        for command in [
            'helm template demo ./chart --output-dir /tmp/rendered',
            'helm template demo ./chart --post-renderer /tmp/script',
            'helm template demo ./chart --dependency-update',
            'helm template demo ./chart --dry-run=server',
            'helm template demo ./chart --enable-dns',
            'helm template demo remote/chart',
            'helm template demo ./chart -f https://example.invalid/values.yaml',
            'helm list -o /tmp/output',
            'helm status release --output-dir /tmp/output',
            'helm --namespace demo install release ./chart',
            'helm --namespace demo upgrade release ./chart',
            'helm --namespace demo uninstall release',
            'helm list && helm uninstall release',
            'helm template demo ./chart && rm -rf /tmp/chart',
        ]:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_helm_lint_in_script_chains_without_approving_deployment(self):
        for command in [
            'helm lint /tmp/example-chart',
            'helm --debug lint --strict --with-subcharts -f /tmp/values.yaml /tmp/example-chart',
            'helm lint . --set image.tag=example --namespace demo',
            'bash /tmp/example/tests/render-contract.sh && helm lint /tmp/example/chart && git -C /tmp/example diff --check',
            'helm lint /tmp/example | grep WARNING',
        ]:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')
        for command in [
            'helm install example /tmp/chart', 'helm upgrade example /tmp/chart',
            'helm --debug upgrade --install example /tmp/chart', 'helm uninstall example',
            'helm lint /tmp/chart && helm upgrade example /tmp/chart',
            'bash /tmp/example/test.sh && helm install example /tmp/chart',
            'helm lint /tmp/chart && rm -rf /tmp/chart',
            'helm lint /tmp/chart --values https://example.invalid/values.yaml',
            'helm lint /tmp/chart --unknown-option',
        ]:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')
        broad = [{'prefix': ['helm'], 'flags': [], 'value_options': [],
                  'max_positionals': 0, 'arguments': '*'}]
        self.assertEqual(policy.decide('helm upgrade example /tmp/chart', broad)[0], 'ask')

    def test_general_command_rule_blocks_delete_merge_and_notifications(self):
        rule = {'prefix': ['example-cli'], 'flags': [], 'value_options': [],
                'max_positionals': 0, 'arguments': '*',
                'deny_words': ['delete', 'remove', 'merge', 'send', 'notify']}
        for command in ['example-cli --json repository list', 'example-cli issue create --title example',
                        'ssh devbox example-cli --json repository list']:
            with self.subTest(command=command):
                self.assertEqual(policy.decide(command, [rule])[0], 'allow')
        for command in ['example-cli item delete 1', 'example-cli item --delete=1',
                        'example-cli mr merge 1', 'example-cli message send hello',
                        "example-cli issue comment create --text '@someone'",
                        'ssh devbox example-cli item delete 1']:
            with self.subTest(command=command):
                self.assertEqual(policy.decide(command, [rule])[0], 'ask')

    def test_file_inspection_and_chains(self):
        commands = [
            "cd /tmp/example-worktree && ls src/components/ 2>&1; echo '=== tests ==='; sed -n '10,20p' tests/ExampleTest.java",
            "cd '/tmp/spaced worktree' && /bin/ls -la src; /usr/bin/sed -n -e '1,$p' README.md",
            "grep -n 'assertFalse' tests/ExampleTest.java",
            "grep -RniE 'assertTrue|assertFalse' src tests | head -n 20",
            "rg --files -g '*.java' src | grep 'Test' | wc -l",
            "rg -n -A3 --glob '*.py' 'def test_' tests | tail -10",
            "cat README.md | sed -n '1,20p'",
            "echo 'git push; $(rm example)' && pwd; true",
            "ls .\ngrep --color=never -e '-pattern' -- README.md\n",
            QUERY + " | grep -i 'alpha' | head -n20",
            "cd /tmp/example && " + QUERY + " | jq '.data'",
            "git -C /tmp/example-worktree ls-files 'src/**/*.py' 'tests/**/*.py'",
            "git -C /tmp -C example --no-pager ls-files -- '*.py' | grep -n 'test_'",
            "git -C/tmp/example ls-files --cached --exclude-standard",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')

    def test_mixed_mutations_and_filter_execution_still_ask(self):
        commands = [
            'grep name README.md && rm -rf /tmp/example', 'ls src\nrm example',
            "ls src | xargs rm", "ls src | sh", 'ls src & git push',
            'ls src; (git push)', 'ls src > /tmp/output',
            'ls src 2>&1> /tmp/output',
            'ls src $(git push)', 'ls `git push`', 'ls <(git push)',
            "sed -i '' -n '1p' README.md", "sed -n '1p;w /tmp/output' README.md",
            "sed -n '1e git push' README.md", "sed -n -f script.sed README.md",
            "sed -n '1p' README.md -e 'e git push'", "sed -n '1p' -i README.md",
            "rg --pre 'git push' text", "rg --pre=script text",
            "rg --hostname-bin script text", "rg --search-zip text",
            "rg -z text", "rg -nz text",
            "git -C /tmp reset --hard",
            "git -C /tmp -c alias.list=push list", "git -c core.fsmonitor=script ls-files",
            "git --exec-path=/tmp ls-files", 'git -C /tmp ls-files > /tmp/list',
            'grep name README.md; unknown-wrapper', 'ls &&', 'ls;;pwd',
            'ls | | head', 'ls |& head',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_chain_python_isolation_preserves_literal_input(self):
        command = "cd ~/example && " + FILTER_PIPELINE + "; echo 'done; no-op'"
        result = invoke(HOOK, command)
        self.assertEqual(result['permissionDecision'], 'allow')
        self.assertEqual(result['updatedInput']['command'], command.replace('python3 -c', 'python3 -I -c'))
        self.assertEqual(decide(result['updatedInput']['command']), ('allow', None))
        for suffix in ['; git push; rm example', ' && rm example', ' | sh']:
            self.assertEqual(decide(command + suffix)[0], 'ask')

    def test_read_commands_disable_executable_helpers(self):
        command = "git -C /tmp/example ls-files '*.py' | rg -n 'test_'"
        allowed, rewritten = decide(command)
        self.assertEqual(allowed, 'allow')
        self.assertEqual(shlex.split(rewritten)[1:1 + len(policy.GIT_GUARDS)], policy.GIT_GUARDS)
        self.assertIn("rg --no-config -n 'test_'", rewritten)
        self.assertEqual(decide(rewritten), ('allow', None))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True)
            marker = root / 'helper-ran'
            helper = root / 'helper.sh'
            helper.write_text('#!/bin/sh\n: > ' + shlex.quote(str(marker)) + '\n')
            helper.chmod(0o700)
            subprocess.run(['git', '-C', directory, 'config', 'core.fsmonitor', str(helper)], check=True)
            _, safe = decide('git -C ' + shlex.quote(directory) + ' ls-files')
            subprocess.run(shlex.split(safe), capture_output=True, check=True)
            self.assertFalse(marker.exists())

    def test_policy_validation_and_missing_policy(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'HOME': directory}):
            self.assertEqual(policy.query_policy(), [])
            path = Path(directory) / '.config/ai-workbench/claude-confirm.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'version': 1, 'queries': RULES}))
            self.assertEqual(policy.query_policy(), RULES)
            invalid = [None, [], {'version': 2, 'queries': []},
                       {'version': 1, 'queries': [{'prefix': ['example-cli']}]},
                       {'version': 1, 'queries': [dict(RULES[0], prefix=['git', 'push'])]},
                       {'version': 1, 'queries': [dict(RULES[0], prefix=['python3'])]},
                       {'version': 1, 'queries': [dict(RULES[0], max_positionals=True)]},
                       {'version': 1, 'queries': [dict(RULES[0], flags=['--json', '--json'])]}]
            for data in invalid:
                with self.subTest(data=data):
                    path.write_text(json.dumps(data))
                    with self.assertRaises(ValueError):
                        policy.query_policy()
            result = subprocess.run([sys.executable, str(HOOK), '--check-policy'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            path.write_text('{broken')
            result = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                                    input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': QUERY}}))
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.returncode, 0)

    def test_read_queries_and_pipelines(self):
        commands = [
            QUERY, 'example-cli --json catalog entries list --refresh',
            '/opt/homebrew/bin/example-cli catalog entries list -j',
            'example-cli inventory items list --item-ids 12,34 --group demo --json',
            'document-cli files +fetch --name example --limit 4',
            "document-cli files +search --query 'some words' --mine --json",
            QUERY + " | jq -r '.data.items[].name'",
            QUERY + " --jq '.data.items | length'",
            QUERY + " | jq --arg needle 'alpha' '.data.items[] | select(.name | contains($needle))'",
            QUERY + " | jq -c '.data' | jq '.items | length'",
            QUERY + " \\\n | jq '.data'", FILTER_PIPELINE,
            QUERY + ' 2>&1 | python3 -c ' + shlex.quote(FILTER),
            QUERY + ' | python3 -I -c ' + shlex.quote(FILTER),
            QUERY + ' | python3 -c ' + shlex.quote('import json,sys\nd=json.loads(sys.stdin.read())\nprint(json.dumps(d,indent=2))'),
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')

    def test_shell_injection_and_dangerous_commands(self):
        commands = [
            '/usr/bin/git -c alias.p=push p', 'git p',
            'git reset --hard HEAD', 'git clean -fdx', 'git branch -D demo',
            'git restore .', 'git checkout -- .', 'git rebase main',
            'sh -c "git push"', 'env X=1 git push', 'command git push',
            'nohup git push', 'timeout 10 git push', 'sudo git push',
            'docker exec app git push',
            '/bin/rm -rf /tmp/example', 'find . -delete',
            'gh pr merge 12', 'gh api repos/a/b -X DELETE',
            'kubectl delete pod demo', 'terraform apply', 'npm run deploy',
            './script',
            "sed -e '1e git push'", "awk 'BEGIN {system(\"git push\")}'",
            'git-send-pack origin main',
            QUERY + '; rm -rf /tmp/example',
            QUERY + ' & git push',
            QUERY + ' | xargs sh -c', QUERY + ' > /tmp/output',
            QUERY + ' 2>/tmp/output', QUERY + ' | tee /tmp/output',
            QUERY + ' $(git push)', QUERY + ' `git push`',
            QUERY + ' | jq ". + $(git push)"', QUERY + ' | jq <(git push)',
            QUERY + ' | jq -f /tmp/filter.jq',
            QUERY + " | jq -L /tmp 'include \"danger\"; .'",
            QUERY + " | jq 'env'", QUERY + " | jq 'inputs'",
            QUERY + ' --output /tmp/output', QUERY + ' --proxy https://example.test',
            'example-cli inventory items create --json',
            'example-cli inventory items list --ids-file /tmp/ids',
            'document-cli files +create --title example',
            'QUERY_BASE_URL=https://example.test ' + QUERY,
            '/tmp/example-cli catalog entries list -j',
            "example-cli catalog entries list -j ''$(git push)",
            QUERY + ' 2>&1> /tmp/out', QUERY + ' |',
            QUERY + ' |& jq .', 'git pu\\\nsh',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_python_escape_attempts(self):
        sources = [
            'import os; os.system("git push")',
            '__import__("os").system("git push")',
            'import subprocess; subprocess.run(["git", "push"])',
            'open("/tmp/output", "w").write("x")',
            'exec("git push")', 'eval("1+1")',
            'import json as other; print(other)',
            'from os import system; system("git push")',
            'print((1).__class__.__mro__)',
            'import sys; print(sys.modules)',
            'import sys; print(sys.stdin.buffer)',
            'import json; json.load = print',
            'import sys; sys = 1',
            'import json; f = json.loads; f("{}")',
            'import json; json.loads("{}", object_hook=print)',
            'print("x", file=open("/tmp/output", "w"))',
            'print = open; print("/tmp/output", "w")',
            'getattr(json, "loads")("{}")',
            'globals()["__builtins__"]',
            'def run():\n return 1\nrun()',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(decide(QUERY + ' | python3 -c ' + shlex.quote(source))[0], 'ask')

    def test_literal_danger_words_are_data(self):
        self.assertEqual(decide("document-cli files +search --query 'git push; rm -rf $(x)' --json")[0], 'allow')
        self.assertEqual(decide(QUERY + " | jq '.data | map(select(.name == \"git push\"))'")[0], 'allow')

    def test_hook_decisions_and_modes(self):
        for mode in ['default', 'acceptEdits', 'auto', 'bypassPermissions']:
            for command, expected in [(FILTER_PIPELINE, 'allow'), ('git push', 'allow'),
                                      ("cd /tmp && ls; sed -n '1,20p' README.md", 'allow'),
                                      ("git -C /tmp/example ls-files '*.py'", 'allow'),
                                      ("grep name README.md; git push", 'allow'),
                                      ('env FOO=x git push', None), ('rm -rf /tmp/example', None),
                                      ('python3 tests/test_example.py', 'allow'),
                                      ('uv run --no-sync python -m pytest -q', 'allow'),
                                      ('PYTHONPATH=src python3 -m unittest discover -s tests', 'allow'),
                                      ('python3 test_x.py && git push', 'allow')]:
                with self.subTest(mode=mode, command=command):
                    decisions = [invoke(p, command, mode).get('permissionDecision') for p in [HOOK]]
                    effective = 'allow' if 'allow' in decisions else None
                    self.assertEqual(effective, expected)

    def test_python_rewrite_isolated_and_preserves_input(self):
        result = invoke(HOOK, FILTER_PIPELINE)
        updated = result['updatedInput']
        self.assertEqual(updated['timeout'], 1000)
        stages = policy.pipeline(updated['command'])
        self.assertEqual(stages[0], ([*shlex.split(QUERY)], True))
        self.assertEqual(stages[1][0], ['python3', '-I', '-c', FILTER])
        self.assertEqual(decide(updated['command']), ('allow', None))
        data = {'data': {'items': [{'name': 'alpha_one'}, {'name': 'beta_two'}, {'name': 'other'}]}}
        with tempfile.TemporaryDirectory() as directory:
            # A cwd json.py must never be imported by the permitted filter.
            Path(directory, 'json.py').write_text('raise RuntimeError("untrusted module")')
            filtered = subprocess.run([sys.executable, '-I', '-c', FILTER],
                                      input=json.dumps(data), cwd=directory,
                                      text=True, capture_output=True, check=True)
        self.assertEqual(filtered.stdout, 'alpha_one\nbeta_two\n')

    def test_powershell_malformed_and_unrelated_tools(self):
        self.assertEqual(invoke(HOOK, 'Remove-Item example', tool='PowerShell'), {})
        self.assertEqual(invoke(HOOK, 'anything', tool='Read'), {})
        for raw in ['{', 'null', '[]', '{"tool_name":"Bash","tool_input":null}']:
            result = subprocess.run([sys.executable, '-B', str(HOOK)], input=raw,
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, '')

class GeneralInspectionTests(unittest.TestCase):
    def test_literal_for_loop_checks_and_rewrites_each_iteration(self):
        commands = [
            'cd /tmp/example && for b in origin/v2 origin/v1; do echo "=== $b ==="; '
            'git show "$b:path/to/config(file).yaml" 2>&1 | grep -nE "alpha|beta"; done',
            'cd ~/example && for b in v2 v1; do git show "$b:README.md" | grep alpha; done',
            r'for rev in v2 v1; do git show $rev:path/to/config\(file\).yaml 2>/dev/null | grep -n alpha; done',
            "for ref in 'v2' \"v1\"; do echo \"${ref}\"; git show \"${ref}:README.md\" | head -3; done",
        ]
        for command in commands:
            with self.subTest(command=command):
                result = invoke(HOOK, command)
                self.assertEqual(result['permissionDecision'], 'allow')
                rewritten = result['updatedInput']['command']
                self.assertEqual(result['updatedInput']['timeout'], 1000)
                self.assertEqual(rewritten.count('--no-ext-diff --no-textconv'), 2)

    def test_literal_for_loop_rejects_dangerous_and_opaque_forms(self):
        commands = [
            'for b in v1 v2; do rm -rf "$b"; done',
            'for b in v1 v2; do git push origin ":$b"; done',
            'for b in v1 v2; do gh pr merge "$b"; done',
            'for b in v1 v2; do lark-cli im message +send --text "$b"; done',
            'for b in v1 v2; do helm upgrade "$b" ./chart; done',
            'for action in get delete; do kubectl "$action" pods; done',
            'for arg in v1 --textconv; do git show "$arg"; done',
            'for b in v1 v2; do echo "$b"; rm file; done',
            'for b in v1 $(echo v2); do echo "$b"; done',
            'for b in v1 *.txt; do echo "$b"; done',
            'for b in v1 "$OTHER"; do echo "$b"; done',
            'for b in v1 v2; do echo "$(rm file)"; done',
            'for b in v1 v2; do echo "$OTHER"; done',
            'for b in v1 v2; do echo "$b"; done; rm file',
            'for PATH in /tmp; do git status; done',
            'for b in v1 v2; do for c in a b; do echo "$c"; done; done',
            'for b in v1 v2; do git show "$b:README.md" > /tmp/result; done',
            'for b in v1 v2; do git show "$b:README.md" | sh; done',
            'for b in v1 v2; do echo "$b";; done',
            'for b in ' + ' '.join('v' + str(i) for i in range(33)) + '; do echo "$b"; done',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_literal_for_loop_applies_local_query_denials_per_value(self):
        rules = [{'prefix': ['example-cli'], 'flags': [], 'value_options': [],
                  'max_positionals': 0, 'arguments': '*',
                  'deny_words': ['delete', 'remove', 'merge', 'send', 'notify']}]
        for values, expected in [('list show', 'allow'), ('list delete', 'ask'),
                                 ('list send', 'ask')]:
            command = 'for verb in ' + values + '; do example-cli item "$verb"; done'
            with self.subTest(values=values):
                self.assertEqual(policy.decide(command, rules)[0], expected)

    def test_literal_for_loop_rewrite_executes_equivalent_read_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, HOME=directory, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(*args):
                return subprocess.run(['git', '-C', directory, *args], env=env,
                                      capture_output=True, text=True, check=True)
            git('init', '-q')
            git('config', 'user.name', 'Example User')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'core.hooksPath', os.devnull)
            git('config', 'commit.gpgSign', 'false')
            (root / 'config(file).yaml').write_text('alpha: value\nbeta: value\n')
            git('add', 'config(file).yaml')
            git('commit', '-qm', 'Example')
            git('branch', 'v1')
            git('branch', 'v2')
            command = ('cd ' + shlex.quote(directory) + ' && for b in v1 v2; do echo "=== $b ==="; '
                       'git show "$b:config(file).yaml" 2>&1 | grep -nE "alpha|beta"; done')
            result = invoke(HOOK, command)
            self.assertEqual(result['permissionDecision'], 'allow')
            original = subprocess.run(command, shell=True, executable='/bin/bash', env=env,
                                      capture_output=True, text=True)
            rewritten = subprocess.run(result['updatedInput']['command'], shell=True,
                                       executable='/bin/bash', env=env, capture_output=True, text=True)
            self.assertEqual((rewritten.returncode, rewritten.stdout, rewritten.stderr),
                             (original.returncode, original.stdout, original.stderr))

    def test_composition_not_specific_paths(self):
        commands = [
            "cd /tmp/example-probe && echo '=== changed commits ==='; git log --oneline v1..v2 -- src/component/ 2>&1 | head -20; echo; echo '=== ancestor ==='; git merge-base --is-ancestor abc123 v2 && echo YES || echo NO",
            "# inspect\n\ncd /tmp/example &&\n git status --short\n\n# report\ngit diff --stat # comment\n",
            "git log --oneline | # filter\n grep fix || true",
            "cat README.md | nl -ba | cut -f 1 | sort -n | uniq -c | tr -d ' '",
            "ls -la *.md | head -20", "cat src/*.py | grep -n TODO",
            "git grep -n -E 'name|value' -- src/ | head -30",
            "git -C /tmp/example branch --show-current", "git branch --contains HEAD",
            "git tag --list 'v*'", 'git remote -v', 'git remote get-url --push origin',
            'git worktree list --porcelain', 'git cat-file -p HEAD',
            "LC_ALL=C git status --short | head -20",
            'git diff-tree --no-commit-id --name-only -r HEAD', 'git blame -L1,20 README.md',
            "jq -r '.name' /tmp/input.json", "jq -n --arg x example '{name:$x}'",
            "python3 -c 'import json; print(json.dumps({\"x\":1}))'",
            "python3 -I -c 'import json; print(json.load(open(\"/tmp/input.json\")))'",
            "cd /tmp/example && pytest -q | tail -20", "python3 test_example.py || true",
            "printf '%s\\n' 'done'", "printf -- '%s' '--flag'",
            "kubectl --context example -n default get pods -o json | jq '.items | length'",
            "kubectl get pods --all-namespaces --watch=false",
            "kubectl logs example --tail=30 | grep ERROR",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')

    def test_dangerous_compositions_and_option_injection(self):
        commands = [
            'ls &&\n# unfinished', "git status | # next\n sh",
            'git branch -f existing', 'git branch -D old', 'git tag new-tag',
            'git remote add origin https://example.invalid', 'git worktree remove /tmp/example',
            'git cat-file --filters HEAD:file', 'git grep --open-files-in-pager=script text',
            'sort -o /tmp/out /tmp/in', 'sort --compress-program=script /tmp/in',
            'uniq /tmp/in /tmp/out', "printf -v PATH '%s' /tmp", "printf -vPATH '%s' /tmp",
            "printf '%n' PATH", "printf '%10n' PATH",
            'rg *', 'git *', 'find *', 'jq *',
            'kubectl delete pod example', 'kubectl apply -f /tmp/example.yaml',
            'kubectl get --raw /api/example/exec', 'kubectl get pods --server=https://example.invalid',
            'kubectl get pods -shttps://example.invalid', 'kubectl get pods --profile=cpu',
            'kubectl get pods --log-file=/tmp/log',
            "python3 -c 'open(\"/tmp/file\", \"w\")'",
            "python3 -c 'mode=\"w\";open(\"/tmp/file\",mode)'",
            "python3 -c 'import subprocess;subprocess.run([\"git\",\"push\"])'",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_query_wildcard_and_options_between_prefix_words(self):
        rules = [dict(RULES[0], arguments='*')]
        for command in [QUERY + ' --limit 50 --new-read-option=value selector',
                        "example-cli --jq '.data' catalog --json entries list --limit=50",
                        "example-cli catalog entries --json list --page-size 100 | head -20"]:
            self.assertEqual(policy.decide(command, rules)[0], 'allow')
        for suffix in [' --output=/tmp/out', ' --yes', ' --exec script', ' --set method=delete',
                       ' --proxy https://example.invalid', ' --body value', '; git push; rm example']:
            self.assertEqual(policy.decide(QUERY + suffix, rules)[0], 'ask')
        self.assertEqual(policy.decide('example-cli catalog entries delete --json', rules)[0], 'ask')
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'HOME': directory}):
            p = Path(directory)/'.config/ai-workbench/claude-confirm.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'version': 1, 'queries': rules}))
            self.assertEqual(policy.query_policy(), rules)
            rules[0]['arguments'] = 'anything'
            p.write_text(json.dumps({'version': 1, 'queries': rules}))
            with self.assertRaises(ValueError): policy.query_policy()

    def test_read_only_python_files_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'example.json'
            path.write_text('{"name":"example"}')
            source = 'import json\nwith open(' + repr(str(path)) + ', encoding="utf-8") as f:\n print(json.load(f)["name"])'
            command = 'python3 -c ' + shlex.quote(source)
            decision_value, rewritten = decide(command)
            self.assertEqual(decision_value, 'allow')
            self.assertIn('python3 -I -c', rewritten)
            result = subprocess.run(shlex.split(rewritten), capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, 'example\n')
            self.assertEqual(path.read_text(), '{"name":"example"}')


class ReviewedScriptTests(unittest.TestCase):
    def test_report_flow_preserves_exit_status_without_shell_eval(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'planner.py'
            script.write_text('import json,sys\nprint(json.dumps({"status":"planned"}))\nsys.exit(7)\n')
            rules = [{'path': str(script), 'sha256': hashlib.sha256(script.read_bytes()).hexdigest(), 'actions': ['plan', 'check']}]
            fd, filename = tempfile.mkstemp(suffix='.json'); os.close(fd)
            report = Path(filename)
            try:
                body = ('import json,os\nd=json.load(open(' + repr(filename) + '))\n'
                        'summary={}\nsummary["status"]=d["status"]\nprint(os.environ["RESULT"],summary["status"])')
                command = ('LC_ALL=C python3 ' + shlex.quote(str(script)) + ' plan --targets example > '
                           + shlex.quote(filename) + '; result=$?; RESULT="$result" python3 - <<\'REPORT\'\n'
                           + body + '\nREPORT')
                allowed, rewritten = policy.decide(command, [], rules)
                self.assertEqual(allowed, 'allow')
                result = subprocess.run(shlex.split(rewritten), capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, '7 planned\n')
                self.assertEqual(json.loads(report.read_text()), {'status': 'planned'})
                for bad in [command.replace(' plan ', ' apply '), command.replace(' plan ', ' plan --apply '),
                            command + '\ngit push', command.replace(body, 'import os;os.system("git push")')]:
                    self.assertEqual(policy.decide(bad, [], rules)[0], 'ask')
                script.write_text('print("changed")')
                self.assertEqual(policy.decide(command, [], rules)[0], 'ask')
            finally:
                report.unlink(missing_ok=True)

    def test_direct_script_calls_and_symlink_report_still_require_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'planner.py'; script.write_text('print("{}")')
            rules = [{'path': str(script), 'sha256': hashlib.sha256(script.read_bytes()).hexdigest(), 'actions': ['plan']}]
            command = 'LC_ALL=C python3 ' + shlex.quote(str(script)) + ' plan | jq .'
            allowed, rewritten = policy.decide(command, [], rules)
            self.assertEqual(allowed, 'allow')
            self.assertIsNone(rewritten)
            self.assertEqual(policy.decide(command, [], [])[0], 'allow')
            fd, filename = tempfile.mkstemp(suffix='.json'); os.close(fd); Path(filename).unlink()
            Path(filename).symlink_to(script)
            try:
                report_command = 'python3 ' + shlex.quote(str(script)) + ' plan > ' + shlex.quote(filename) + '; rc=$?; RESULT="$rc" python3 - <<\'END\'\nprint(1)\nEND'
                self.assertEqual(policy.decide(report_command, [], rules)[0], 'ask')
                self.assertEqual(script.read_text(), 'print("{}")')
            finally:
                Path(filename).unlink()


class FindInspectionTests(unittest.TestCase):
    def test_read_only_predicates_groups_and_pipelines(self):
        commands = [
            "find . -type f -name '*.py'",
            "find src tests -maxdepth 4 -type f -iname '*test*' -print",
            "find . -name .git -prune -o -type f -print",
            r"find . -type f \( -name '*.py' -o -name '*.md' \) ! -path './.git/*'",
            "find . '(' -name '*.py' -o -name '*.md' ')' -not -empty",
            "find -L . -type f -mtime -7 -size +1k -print0",
            "find /tmp -newermt '2026-01-01' -maxdepth 1 -ls",
            "find -E -f . -regex '.*[.]py' -print",
            "find . -name '-delete'", "find . -printf '%p\\n'",
            "cd /tmp/example && find . -type f -name '*.py' 2>/dev/null | grep test | head -n 20",
            "find . -type f; git status --short",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'allow')

    def test_execution_deletion_and_output_actions_still_ask(self):
        commands = [
            r'find . -exec rm {} \;', 'find . -execdir sh {} +',
            "find . -exec sh '{}' '+'", "find . -execdir sh '{}' '+'",
            r'find . -ok rm {} \;', r'find . -okdir sh {} \;',
            'find . -delete', 'find . -name ignored -o -delete',
            'find . -not -delete', 'find . -fprint /tmp/output',
            'find . -fprint0 /tmp/output', "find . -fprintf /tmp/output '%p'",
            'find . -fls /tmp/output', 'find . -rm', 'find . -unknown',
            'find . -files0-from /tmp/list', 'find . | xargs rm',
            'find . > /tmp/output', 'find . 2>/tmp/errors',
            'find . 2>/dev/null.extra',
            'find . 2>/dev/null>/tmp/output', 'find . $(git push)',
            'find . ( -name file )', '! git push', r'\! git push',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], 'ask')

    def test_installed_protocol_and_real_file_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'one.py').write_text('example\n')
            (root / 'two.md').write_text('other\n')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            command = "find " + shlex.quote(directory) + " -type f -name '*.py'"
            for mode in ['acceptEdits', 'bypassPermissions']:
                self.assertEqual(invoke(HOOK, command, mode)['permissionDecision'], 'allow')
                self.assertEqual(invoke(HOOK, command + ' -delete', mode), {})
            result = subprocess.run(shlex.split(command), capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(root / 'one.py'))
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)


class GitInspectionTests(unittest.TestCase):
    def test_shared_inspection_family_with_directories_and_pipelines(self):
        commands = [
            'status', 'status -sb -uall', 'status --porcelain=v1 --untracked-files=all',
            'status --ignore-submodules=all',
            'diff', 'diff --stat --cached', "diff -U5 -M50% HEAD~1 -- '*.py'",
            'diff --name-only main...HEAD', 'diff --no-index /tmp/a /tmp/b',
            'diff --word-diff=plain --diff-filter=AM',
            'log -20 --oneline --graph --decorate --all',
            "log -n 5 --format='%h %s' --author='Example User' --since=2026-01-01",
            'log -g --oneline', 'log --no-walk --pretty=fuller HEAD',
            'show HEAD:README.md', 'show --stat --oneline HEAD^',
            "show --format=format:'%h %s' --name-only HEAD", "show --pretty='' --name-only HEAD", 'show --',
            'ls-files --cached', "ls-tree -rz --name-only HEAD -- 'src/'",
            'rev-parse --show-toplevel', 'rev-parse --verify HEAD',
            "rev-parse --abbrev-ref '@{-1}'", 'rev-list --count HEAD',
            'rev-list --left-right --count main...HEAD', 'show-ref --heads --tags',
            'merge-base HEAD main', 'merge-base --is-ancestor main HEAD',
            'describe --tags --always --dirty', 'shortlog -sn HEAD',
            "shortlog --numbered --group=format:'%aN' HEAD",
        ]
        for command in commands:
            for prefix in ['git ', "git -C '/tmp/example repo' ", 'git -C /tmp -Cexample -P ']:
                for suffix in ['', " | grep -n 'example' | head -n 20"]:
                    with self.subTest(command=prefix + command + suffix):
                        allowed, rewritten = decide(prefix + command + suffix)
                        self.assertEqual(allowed, 'allow')
                        self.assertEqual(decide(rewritten), ('allow', None))
        self.assertEqual(decide('git status --short && git diff --stat; git log -5 --oneline')[0], 'allow')

    def test_risky_actions_options_and_wrappers(self):
        commands = [
            'reset --hard', 'clean -fdx', 'checkout -- .',
            'restore .', 'branch -D example', 'tag -d example', 'rebase main',
            'apply change.patch', 'update-ref refs/heads/main HEAD',
            'diff --output=/tmp/output', 'diff --out=/tmp/output',
            'diff --ext-diff', 'log --textconv -p', 'show --show-signature',
            "log --format='%G?'", 'show --pretty=custom',
            "shortlog --group=format:'%G?' HEAD", "shortlog --format='%G?' HEAD",
            'log --format=custom', 'log -g --ext-diff',
            'diff --submodule=diff', 'log --stdin',
            'status --unknown-option', 'diff --unknown-option', 'status -vv', 'status --verbose',
            'log --diff-merges=remerge',
            'diff --no-no-textconv', 'log --help',
            '-c alias.inspect=push inspect', '-c core.pager=script log',
            '--config-env=core.pager=PROGRAM log', '--exec-path=/tmp log',
            'diff | sh', 'status; git push; rm example', 'log -1 > /tmp/output',
        ]
        for command in commands:
            for prefix in ['git ', 'git -C /tmp/example ']:
                with self.subTest(command=prefix + command):
                    self.assertEqual(decide(prefix + command)[0], 'ask')
        for command in ["sh -c 'git status; git push'", 'env GIT_PAGER=script git log']:
            self.assertEqual(decide(command)[0], 'ask')
        self.assertEqual(decide('git diff -- --output=filename')[0], 'allow')

    def test_rewrite_preserves_paths_formats_and_input_fields(self):
        command = "git -C '/tmp/example repo' log --format='%h; %s' -5 | head -n 3"
        for mode in ['default', 'acceptEdits', 'auto', 'bypassPermissions']:
            out = invoke(HOOK, command, mode)
            self.assertEqual(out['permissionDecision'], 'allow')
            self.assertEqual(out['updatedInput']['timeout'], 1000)
            rewritten = out['updatedInput']['command']
            self.assertIn("-C '/tmp/example repo' log --no-ext-diff --no-textconv --format='%h; %s' -5", rewritten)
            self.assertEqual(decide(rewritten), ('allow', None))
            self.assertEqual(invoke(HOOK, command + '; git push; rm example', mode), {})

    def test_real_git_inspection_does_not_run_configured_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, HOME=directory, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(*args, **kwargs):
                return subprocess.run(['git', '-C', directory, *args], env=env,
                                      capture_output=True, text=True, check=True, **kwargs)
            git('init', '-q')
            git('config', 'user.name', 'Example User')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'core.hooksPath', os.devnull)
            git('config', 'commit.gpgSign', 'false')
            (root / 'sample.txt').write_text('before\n')
            (root / '.gitattributes').write_text('sample.txt diff=probe\n')
            git('add', 'sample.txt', '.gitattributes')
            git('commit', '-qm', 'Example commit')
            original = git('cat-file', 'commit', 'HEAD').stdout
            signed = original.replace('\n\n', '\ngpgsig -----BEGIN PGP SIGNATURE-----\n dummy\n -----END PGP SIGNATURE-----\n\n', 1)
            oid = git('hash-object', '-t', 'commit', '-w', '--stdin', input=signed).stdout.strip()
            git('update-ref', 'HEAD', oid)
            (root / 'sample.txt').write_text('after\n')
            marker = root / 'helper-ran'
            helper = root / 'helper.sh'
            helper.write_text('#!/bin/sh\n: > ' + shlex.quote(str(marker)) + '\n')
            helper.chmod(0o700)
            for key in ['core.fsmonitor', 'core.pager', 'diff.external', 'diff.probe.textconv', 'gpg.program']:
                git('config', key, str(helper))
            git('config', 'log.showSignature', 'true')
            git('config', 'status.verbose', 'true')
            git('config', 'format.pretty', '%G?')
            # Verify the harmless marker is a working detector, then test guards.
            git('log', '-1', '--format=%G?')
            self.assertTrue(marker.exists())
            marker.unlink()
            before_index = (root / '.git/index').read_bytes()
            for action in ['status --short', 'status', 'diff', 'log -1 -p', 'show HEAD', 'ls-files',
                           'grep -n after', 'blame sample.txt', 'diff-tree -r HEAD',
                           'ls-tree HEAD', 'rev-parse HEAD', 'rev-list HEAD',
                           'show-ref --head', 'merge-base HEAD HEAD', 'describe --always', 'shortlog -sn HEAD']:
                with self.subTest(action=action):
                    marker.unlink(missing_ok=True)
                    command = 'git -C ' + shlex.quote(directory) + ' ' + action
                    allowed, rewritten = decide(command)
                    self.assertEqual(allowed, 'allow')
                    result = subprocess.run(shlex.split(rewritten), env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(marker.exists(), action)
            self.assertEqual((root / '.git/index').read_bytes(), before_index)


if __name__ == '__main__':
    unittest.main()
