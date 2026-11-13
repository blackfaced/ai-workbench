import json
from pathlib import Path
import subprocess
import sys
import unittest

HOOK = Path(__file__).with_name('confirm.py')


def decision(command, tool='Bash'):
    event = {'tool_name': tool, 'tool_input': {'command': command}}
    run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                         text=True, capture_output=True, check=True)
    return json.loads(run.stdout)['hookSpecificOutput']['permissionDecision'] if run.stdout else None


class HookTests(unittest.TestCase):
    def test_discovery_and_chains(self):
        command = "PYTHONPATH=src:scripts .venv/bin/python -m unittest discover -s tests -p 'test_example.py' -v"
        self.assertEqual(decision(command), 'allow')
        self.assertEqual(decision(command + ' && ' + command), 'allow')
        self.assertEqual(decision("python3 -m unittest discover -s tests -p 'test_*.py'"), 'allow')

    def test_defer_other_commands(self):
        base = "python3 -m unittest discover -s tests -p 'test_example.py'"
        for command in [base + ' && git push', base + '; rm -rf build', 'git push',
                        'python3 -c "print(1)"', base + ' $(echo x)', 'ls']:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))
        self.assertIsNone(decision('dir', 'PowerShell'))


if __name__ == '__main__':
    unittest.main()
