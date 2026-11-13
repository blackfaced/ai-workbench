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
        for command in ['python3 deploy.py', 'python3 -c "print(1)"', 'python3 -m other',
                        'pytest && git push', 'pytest | head', 'pytest > log', 'pytest & git status',
                        'pytest\ngit push', 'pytest $(date)', 'pytest ; rm a', 'echo pytest',
                        'pytest &&', 'python -m pytest_extra', 'python3 -test_x.py']:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))

    def test_defer_other_commands(self):
        base = "python3 -m unittest discover -s tests -p 'test_example.py'"
        for command in [base + ' && git push', base + '; rm -rf build', 'git push',
                        'python3 -c "print(1)"', base + ' $(echo x)', 'ls']:
            with self.subTest(command=command):
                self.assertIsNone(decision(command))
        self.assertIsNone(decision('dir', 'PowerShell'))


if __name__ == '__main__':
    unittest.main()
