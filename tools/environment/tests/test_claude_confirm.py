"""Isolated lifecycle checks for the opt-in Claude hook component."""
import json
import importlib.util
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from regression import Sandbox, base_profile


class ClaudeConfirmLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aiwb confirm test ')
        self.addCleanup(self.temp.cleanup)
        self.box = Sandbox(self.temp.name)
        source = Path(__file__).resolve().parents[2] / 'claude-confirm' / 'confirm.py'
        copied = Path(self.box.repo) / 'tools/claude-confirm/confirm.py'
        copied.parent.mkdir(parents=True)
        shutil.copy2(source, copied)
        self.settings = Path(self.box.home) / '.claude/settings.json'
        self.script = Path(self.box.home) / '.local/share/ai-workbench/hooks/claude-confirm.py'
        self.component = {'id': 'claude-confirm', 'type': 'claude_confirm', 'opt_in': True,
                          'source': 'tools/claude-confirm/confirm.py',
                          'path': '~/.local/share/ai-workbench/hooks/claude-confirm.py',
                          'settings': '~/.claude/settings.json'}
        self.box.profile(base_profile([self.component], clients={
            'claude': {'hook_files': ['~/.claude/settings.json']}}))

    def run_env(self, verb, *args):
        return self.box.run(verb, '--profile', 'harness', *args)

    def install(self):
        rc, output = self.run_env('apply', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, output)
        return self.box.latest_backup()

    def test_opt_in_first_install_check_and_restore(self):
        rc, out = self.run_env('plan')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('install hook script', out)
        self.assertFalse(self.settings.exists())
        backup = self.install()
        self.assertTrue(self.script.is_file())
        group = json.loads(self.settings.read_text())['hooks']['PreToolUse'][0]
        self.assertEqual(group['matcher'], 'Bash|PowerShell')
        self.assertIn(str(self.script), group['hooks'][0]['command'])
        rc, out = self.run_env('check', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, out)
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, out)
        self.assertIn('无变更', out)
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertFalse(self.script.exists())
        self.assertFalse(self.settings.exists())
        self.assertNotIn('claude-confirm:registration', self.box.state()['components'])

    def test_mcp_component_install_check_and_restore_preserves_bash_hook(self):
        self.install()
        before = json.loads(self.settings.read_text())
        source = Path(__file__).resolve().parents[2] / 'claude-confirm' / 'mcp_confirm.py'
        copied = Path(self.box.repo) / 'tools/claude-confirm/mcp_confirm.py'
        shutil.copy2(source, copied)
        target = Path(self.box.home) / '.local/share/ai-workbench/hooks/claude-mcp-confirm.py'
        profile_path = Path(__file__).resolve().parents[1] / 'profiles/claude-hooks.json'
        portable = json.loads(profile_path.read_text())
        self.assertEqual(portable['os'], 'Any')
        self.assertEqual(portable['components'][0], self.component)
        self.assertEqual(portable['components'][1]['matcher'], 'mcp__.*')
        self.assertTrue(all(item['opt_in'] for item in portable['components']))
        self.box.profile(portable)
        rc, out = self.run_env('apply', '--only', 'claude-mcp-confirm')
        self.assertEqual(rc, 0, out)
        backup = self.box.latest_backup()
        groups = json.loads(self.settings.read_text())['hooks']['PreToolUse']
        self.assertEqual(groups[0], before['hooks']['PreToolUse'][0])
        self.assertEqual(groups[1]['matcher'], 'mcp__.*')
        self.assertTrue(target.is_file())
        for tool, payload, expected in [('mcp__lark__send_message', {'text': 'hello'}, None),
                                        ('mcp__tracker__comment_create', {'body': '@someone'}, None),
                                        ('mcp__tracker__search', {'query': 'hello'}, None)]:
            event = {'tool_name': tool, 'tool_input': payload}
            result = subprocess.run([sys.executable, str(target)], input=json.dumps(event),
                                    text=True, capture_output=True, check=True)
            decision = json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] if result.stdout else None
            self.assertEqual(decision, expected)
        rc, out = self.run_env('check', '--only', 'claude-mcp-confirm')
        self.assertEqual(rc, 0, out)
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(self.settings.read_text()), before)
        self.assertFalse(target.exists())
        self.assertTrue(self.script.exists())

    def test_supported_profiles_declare_the_same_opt_in_component(self):
        profiles = Path(__file__).resolve().parents[1] / 'profiles'
        for name in ('home-mac', 'work-mac', 'work-linux'):
            with self.subTest(profile=name):
                data = json.loads((profiles / (name + '.json')).read_text())
                found = [c for c in data['components'] if c['id'] == 'claude-confirm']
                self.assertEqual(found, [self.component])

    def test_restore_preserves_unrelated_settings_and_hooks(self):
        existing = {'env': {'EXAMPLE': 'keep'}, 'permissions': {'allow': ['Read']},
                    'hooks': {'PreToolUse': [{'matcher': 'Read', 'hooks': [
                        {'type': 'command', 'command': 'existing-hook'}]}]}}
        self.settings.write_text(json.dumps(existing))
        os.chmod(self.settings, 0o600)
        backup = self.install()
        backup_dir = Path(self.box.home) / '.ai-workbench/environment/backups' / backup
        self.assertEqual(backup_dir.stat().st_mode & 0o777, 0o700)
        manifest = json.loads((backup_dir / 'manifest.json').read_text())
        item = next(e for e in manifest['entries'] if e['kind'] == 'json_hook')
        self.assertEqual((backup_dir / item['backup_file']).stat().st_mode & 0o777, 0o600)
        updated = json.loads(self.settings.read_text())
        updated['new_user_setting'] = True
        updated['hooks']['PreToolUse'].append({'matcher': 'Write', 'hooks': []})
        self.settings.write_text(json.dumps(updated))
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        restored = json.loads(self.settings.read_text())
        self.assertEqual(restored['env'], existing['env'])
        self.assertEqual(restored['permissions'], existing['permissions'])
        self.assertTrue(restored['new_user_setting'])
        self.assertEqual(restored['hooks']['PreToolUse'], existing['hooks']['PreToolUse'] +
                         [{'matcher': 'Write', 'hooks': []}])
        self.assertFalse(self.script.exists())

    def test_modified_registration_preserves_script_on_restore(self):
        backup = self.install()
        data = json.loads(self.settings.read_text())
        data['hooks']['PreToolUse'][0]['hooks'][0]['timeout'] = 15
        self.settings.write_text(json.dumps(data))
        rc, out = self.run_env('check', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertNotEqual(rc, 0, out)
        self.assertIn('保留其脚本', out)
        self.assertTrue(self.script.exists())
        self.assertEqual(json.loads(self.settings.read_text())['hooks']['PreToolUse'][0]['hooks'][0]['timeout'], 15)

    def test_changed_command_does_not_remove_script(self):
        backup = self.install()
        data = json.loads(self.settings.read_text())
        data['hooks']['PreToolUse'][0]['hooks'][0]['command'] += ' --changed'
        self.settings.write_text(json.dumps(data))
        rc, out = self.box.run('restore', '--backup', backup, '--force')
        self.assertNotEqual(rc, 0, out)
        self.assertTrue(self.script.exists())
        self.assertIn('--changed', self.settings.read_text())

    def test_settings_symlink_after_install_preserves_registration_and_script(self):
        backup = self.install()
        target = Path(self.box.home) / 'foreign.json'
        target.write_text(self.settings.read_text())
        self.settings.unlink()
        self.settings.symlink_to(target)
        before = target.read_text()
        rc, out = self.box.run('restore', '--backup', backup, '--force')
        self.assertNotEqual(rc, 0, out)
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(target.read_text(), before)
        self.assertTrue(self.script.exists())

    def test_invalid_or_foreign_settings_block_without_installing_script(self):
        self.settings.write_text('{invalid')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.settings.read_text(), '{invalid')
        self.assertFalse(self.script.exists())
        self.settings.write_text('{"hooks": {}, "hooks": {}}')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.script.exists())
        self.settings.write_text('{"value": NaN}')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.script.exists())
        target = Path(self.box.home) / 'foreign.json'
        target.write_text('{}')
        self.settings.unlink()
        self.settings.symlink_to(target)
        rc, out = self.run_env('apply', '--only', 'claude-confirm', '--force')
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(target.read_text(), '{}')
        self.assertFalse(self.script.exists())

    def test_existing_script_is_not_taken_over(self):
        self.script.parent.mkdir(parents=True)
        self.script.write_text('user-owned script')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.script.read_text(), 'user-owned script')
        self.assertFalse(self.settings.exists())

    def test_concurrent_settings_edit_is_not_overwritten(self):
        path = Path(self.box.env_dir) / 'env.py'
        spec = importlib.util.spec_from_file_location('environment_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.settings.write_text('{"theme":"before"}')
        data, raw = module.read_claude_settings(str(self.settings))
        self.settings.write_text('{"theme":"changed"}')
        with self.assertRaises(RuntimeError):
            module.write_claude_settings(str(self.settings), data, raw)
        self.assertEqual(json.loads(self.settings.read_text()), {'theme': 'changed'})

    def test_upgrade_restore_restores_previous_script_ownership(self):
        self.install()
        original = self.script.read_text()
        source = Path(self.box.repo) / 'tools/claude-confirm/confirm.py'
        source.write_text(original + '\n# next version\n')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(self.script.read_text(), original)
        backup = self.box.latest_backup()
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.script.read_text(), original)
        self.assertIn('claude-confirm:script', self.box.state()['components'])
        rc, out = self.run_env('plan', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, out)
        self.assertIn('install hook script', out)
        self.assertNotIn('需要人处理 1 项', out)

    def test_installed_query_policy_survives_restore(self):
        import hashlib
        import shlex
        policy = Path(self.box.home) / '.config/ai-workbench/claude-confirm.json'
        policy.parent.mkdir(parents=True)
        reviewed = Path(self.box.home) / 'planner.py'
        reviewed.write_text('print("{}")')
        policy.write_text(json.dumps({'version': 1, 'queries': [{
            'prefix': ['example-cli', 'items', 'list'], 'flags': ['--json'],
            'value_options': [], 'max_positionals': 0, 'arguments': '*'}],
            'scripts': [{'path': str(reviewed), 'sha256': hashlib.sha256(reviewed.read_bytes()).hexdigest(),
                         'actions': ['plan']}]}))
        before = policy.read_bytes()
        backup = self.install()
        for command, expected in [("example-cli items list --json | jq '.data'", 'allow'),
                                  ("example-cli items list --json --limit 30", 'allow'),
                                  ("example-cli items list --output=/tmp/result", None),
                                  ('python3 ' + shlex.quote(str(reviewed)) + ' plan', 'allow'),
                                  ('python3 ' + shlex.quote(str(reviewed)) + ' apply', 'allow'),
                                  ("cd /tmp/example && ls; sed -n '1,20p' README.md", 'allow'),
                                  ("git -C /tmp/example ls-files '*.py' | grep test", 'allow'),
                                  ("git -C /tmp/example status -sb && git -C /tmp/example diff --stat", 'allow'),
                                  ("git -C /tmp/example log -5 --oneline | head -n 2", 'allow'),
                                  ("git -C /tmp/example show HEAD:README.md | sed -n '1,20p'", 'allow'),
                                  ("git -C /tmp/example diff --output=/tmp/output", None),
                                  ("find . -type f -name '*.py' 2>/dev/null | head -n 20", 'allow'),
                                  ("find . -type f -delete", None),
                                  ("grep name README.md; git push", 'allow'),
                                  ('git push origin main', 'allow'),
                                  ('python3 test_example.py', 'allow')]:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, str(self.script)],
                                        env=dict(os.environ, HOME=self.box.home),
                                        input=json.dumps({'tool_name': 'Bash',
                                                          'tool_input': {'command': command}}),
                                        capture_output=True, text=True, check=True)
                decision = json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] if result.stdout else None
                self.assertEqual(decision, expected)
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertEqual(policy.read_bytes(), before)
        self.assertFalse(self.script.exists())

    def test_unowned_matching_hook_is_not_adopted(self):
        import shlex
        group = {'matcher': 'Bash|PowerShell', 'hooks': [{'type': 'command',
                 'command': 'python3 ' + shlex.quote(str(self.script)), 'timeout': 5}]}
        self.settings.write_text(json.dumps({'hooks': {'PreToolUse': [group]}}))
        original = self.settings.read_text()
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertNotEqual(rc, 0)
        self.assertIn('not owned', out)
        self.assertEqual(self.settings.read_text(), original)
        self.assertFalse(self.script.exists())

    def test_force_takeover_backs_up_and_restores_user_script(self):
        self.script.parent.mkdir(parents=True)
        self.script.write_text('user-owned script')
        rc, out = self.run_env('apply', '--only', 'claude-confirm', '--force')
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(self.script.read_text(), 'user-owned script')
        backup = self.box.latest_backup()
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.script.read_text(), 'user-owned script')

    def test_rollback_of_upgrade_reports_modified_script(self):
        self.install()
        source = Path(self.box.repo) / 'tools/claude-confirm/confirm.py'
        source.write_text(source.read_text() + '\n# updated\n')
        rc, out = self.run_env('apply', '--only', 'claude-confirm')
        self.assertEqual(rc, 0, out)
        backup = self.box.latest_backup()
        self.script.write_text('user changed script after upgrade')
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(self.script.read_text(), 'user changed script after upgrade')
        self.assertTrue(json.loads(self.settings.read_text())['hooks']['PreToolUse'])

    def test_failed_registration_leaves_recoverable_script_backup(self):
        path = Path(self.box.env_dir) / 'env.py'
        spec = importlib.util.spec_from_file_location('environment_failed_registration', path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {'HOME': self.box.home}):
            spec.loader.exec_module(module)
            output = io.StringIO()
            with mock.patch.object(module, 'write_claude_settings', side_effect=RuntimeError('injected failure')):
                with contextlib.redirect_stdout(output):
                    rc = module.main(['apply', '--profile', 'harness', '--only', 'claude-confirm'])
        self.assertNotEqual(rc, 0)
        self.assertIn('可用于检查和回滚的备份', output.getvalue())
        self.assertTrue(self.script.exists())
        self.assertFalse(self.settings.exists())
        backup = self.box.latest_backup()
        rc, out = self.box.run('restore', '--backup', backup)
        self.assertEqual(rc, 0, out)
        self.assertFalse(self.script.exists())
        self.assertFalse(self.settings.exists())


if __name__ == '__main__':
    unittest.main()
