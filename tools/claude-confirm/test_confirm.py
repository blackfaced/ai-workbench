import json
from pathlib import Path
import subprocess
import sys
import unittest


HOOK = Path(__file__).with_name('confirm.py')


def run_hook(event):
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] if result.stdout else None


class ConfirmTests(unittest.TestCase):
    def bash(self, command):
        return run_hook({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_push_and_destructive_variants(self):
        for command in ['git push', 'git -C /tmp/project push origin main',
                        'git -c alias.x=push x', '/usr/bin/git push', '/tmp/unknown/git status',
                        'git reset --hard HEAD', 'git clean -fd', 'rm -rf build']:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 'ask')

    def test_shell_and_opaque_scripts(self):
        for command in ['echo ok && git push', 'echo $(git push)', 'sh -c "git push"',
                        'python3 check.py', 'uv run python check.py', './check.sh',
                        "cat > /tmp/check.py <<'EOF'\nprint(1)\nEOF\npython3 /tmp/check.py",
                        'python3 -c "print(1)"', 'unknown-executable --help']:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 'ask')

    def test_simple_reads_do_not_override_permissions(self):
        for command in ['pwd', 'ls', 'ls -la', 'git status', 'git -C /tmp/project status --short',
                        'git diff', 'git log --oneline']:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_failures_and_other_tools(self):
        self.assertEqual(self.bash('echo "unfinished'), 'ask')
        self.assertEqual(run_hook({'tool_name': 'Bash', 'tool_input': {}}), 'ask')
        self.assertEqual(run_hook({'tool_name': 'PowerShell', 'tool_input': {'command': 'dir'}}), 'ask')
        self.assertIsNone(run_hook({'tool_name': 'Read', 'tool_input': {}}))
        result = subprocess.run([sys.executable, str(HOOK)], input='{', text=True,
                                capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'ask')


if __name__ == '__main__':
    unittest.main()
