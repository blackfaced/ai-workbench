#!/usr/bin/env python3
"""Public CLI installation tests; temporary HOME, local fixed Git objects only."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import shlex
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / 'tools/environment/install_cc_dispatch.py'
SOURCE_FILES = ('LICENSE', 'tools/cc-dispatch/cc-dispatch',
                'tools/cc-dispatch/cc_dispatch.py', 'tools/cc-dispatch/README.md',
                'tools/cc-dispatch/config.example.json', 'skills/cc-dispatch/SKILL.md')


class InstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # CI checks out only the current commit. Build an immutable local source
        # rather than requiring an unrelated historical object or fetching it.
        cls.source_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.source_tmp.cleanup)
        cls.source = Path(cls.source_tmp.name).resolve() / 'source'
        cls.source.mkdir()
        for name in SOURCE_FILES:
            target = cls.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / name, target)
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.com',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.com')
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_OBJECT_DIRECTORY',
                    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG_COUNT'):
            env.pop(key, None)
        subprocess.run(['git', 'init', '--quiet', str(cls.source)], env=env, check=True)
        subprocess.run(['git', '-C', str(cls.source), 'add', '--', *SOURCE_FILES], env=env, check=True)
        subprocess.run(['git', '-C', str(cls.source), '-c', 'commit.gpgsign=false',
                        'commit', '--quiet', '-m', 'local installation fixture'], env=env, check=True)
        cls.pin = subprocess.check_output(['git', '-C', str(cls.source), 'rev-parse', 'HEAD'],
                                          env=env, text=True).strip()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve() / 'home'
        self.home.mkdir()
        self.cwd = Path(self.tmp.name) / 'unrelated'
        self.cwd.mkdir()
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop('CC_DISPATCH_CONFIG', None)
        self.entry = self.home / '.local/bin/cc-dispatch'
        self.skill = self.home / '.claude/skills/cc-dispatch'

    def cli(self, action=None, pin=None):
        pin = self.pin if pin is None else pin
        args = [sys.executable, '-I', str(INSTALLER)]
        if action:
            args.append(action)
        return subprocess.run(args + ['--source', str(self.source), '--commit', pin],
                              cwd=self.cwd, env=self.env, capture_output=True, text=True)

    def upgrade_with_filesystem_event(self, mutation, event='release'):
        """Exercise the CLI with an external edit at a filesystem audit boundary."""
        source = Path(self.tmp.name).resolve() / ('upgrade-source-' + event)
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout',
                        str(self.source), str(source)], check=True)
        tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', self.pin + '^{tree}'], text=True).strip()
        env = dict(self.env, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.com',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.com')
        pin = subprocess.check_output(['git', '-C', str(source), 'commit-tree', tree, '-p', self.pin],
                                      input='isolated upgrade fixture\n', text=True, env=env).strip()
        root = self.home / '.local/share/cc-dispatch/releases' / pin
        state = root.parent / 'installation.json'
        destination = {'release': root, 'entry': self.entry, 'state': state}[event]
        driver = ('import os,sys,runpy\nfrom pathlib import Path\n'
                  'fired=False\n'
                  'def audit(event,args):\n'
                  ' global fired\n'
                  ' if event=="os.rename" and str(args[1])==' + repr(str(destination)) + ' and not fired:\n'
                  '  fired=True\n' + mutation + '\n'
                  'sys.addaudithook(audit)\n'
                  'sys.argv=' + repr([str(INSTALLER), 'apply', '--source', str(source), '--commit', pin]) + '\n'
                  'runpy.run_path(sys.argv[0],run_name="__main__")\n')
        return subprocess.run([sys.executable, '-I', '-c', driver], cwd=self.cwd,
                              env=self.env, capture_output=True, text=True)

    def test_wrapper_edit_after_observation_is_preserved(self):
        self.assertEqual(self.cli('apply').returncode, 0)
        state = self.home / '.local/share/cc-dispatch/releases/installation.json'
        before = state.read_bytes()
        link = os.readlink(self.skill)
        result = self.upgrade_with_filesystem_event(
            '  Path(' + repr(str(self.entry)) + ').write_text("external wrapper edit\\n")')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.entry.read_text(), 'external wrapper edit\n')
        self.assertEqual(os.readlink(self.skill), link)
        self.assertEqual(state.read_bytes(), before)

    def test_link_change_after_observation_and_before_unlink_is_preserved(self):
        for event in ('release', 'entry'):
            with self.subTest(event=event):
                self.assertEqual(self.cli('apply').returncode, 0)
                before = self.entry.read_bytes()
                state = self.home / '.local/share/cc-dispatch/releases/installation.json'
                old_state = state.read_bytes()
                old_link = os.readlink(self.skill)
                mutation = ('  p=Path(' + repr(str(self.skill)) + ')\n'
                            '  p.unlink()\n  p.symlink_to("/external/skill")')
                result = self.upgrade_with_filesystem_event(mutation, event=event)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(os.readlink(self.skill), '/external/skill')
                self.assertEqual(self.entry.read_bytes(), before)
                self.assertEqual(state.read_bytes(), old_state)
                self.skill.unlink()
                self.skill.symlink_to(old_link)

    def test_manifest_edit_after_observation_is_preserved(self):
        self.assertEqual(self.cli('apply').returncode, 0)
        state = self.home / '.local/share/cc-dispatch/releases/installation.json'
        before = self.entry.read_bytes()
        link = os.readlink(self.skill)
        result = self.upgrade_with_filesystem_event(
            '  Path(' + repr(str(state)) + ').write_text("external manifest edit\\n")')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(state.read_text(), 'external manifest edit\n')
        self.assertEqual(self.entry.read_bytes(), before)
        self.assertEqual(os.readlink(self.skill), link)

    def test_failed_activation_compensates_without_overwriting_foreign_edits(self):
        self.assertEqual(self.cli('apply').returncode, 0)
        state = self.home / '.local/share/cc-dispatch/releases/installation.json'
        before = state.read_bytes()
        mutation = ('  Path(' + repr(str(self.entry)) + ').write_text("external wrapper edit\\n")\n'
                    '  p=Path(' + repr(str(self.skill)) + ')\n'
                    '  p.unlink()\n  p.symlink_to("/external/skill")\n'
                    '  raise OSError("injected activation failure")')
        result = self.upgrade_with_filesystem_event(mutation, event='state')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.entry.read_text(), 'external wrapper edit\n')
        self.assertEqual(os.readlink(self.skill), '/external/skill')
        self.assertEqual(state.read_bytes(), before)

    def run_entry(self, *args):
        return subprocess.run([str(self.entry), *args], cwd=self.cwd, env=self.env,
                              capture_output=True, text=True)

    def test_default_plan_is_read_only_and_apply_exposes_global_cli_and_skill(self):
        plan = self.cli()
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual(json.loads(plan.stdout)['action'], 'plan')
        self.assertEqual(list(self.home.iterdir()), [])
        applied = self.cli('apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        release = Path(json.loads(applied.stdout)['root'])
        self.assertEqual(release.name, self.pin)
        self.assertTrue(self.skill.is_symlink())
        self.assertEqual(self.skill.resolve(), release / 'skills/cc-dispatch')
        help_result = self.run_entry('--help')
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('dontAsk', help_result.stdout)
        self.assertEqual(self.cli('check').returncode, 0)
        self.assertFalse((release / 'tools/cc-dispatch/config.json').exists())
        self.assertFalse((self.home / '.claude/dispatch/config.json').exists())
        self.assertIn('Apache License', (release / 'LICENSE').read_text())

    def test_release_directory_drift_is_rejected_before_dispatch(self):
        applied = self.cli('apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        release = Path(json.loads(applied.stdout)['root'])
        (release / 'unexpected').mkdir()
        self.assertNotEqual(self.cli('check').returncode, 0)
        self.assertNotEqual(self.run_entry('--help').returncode, 0)
        self.assertNotEqual(self.cli('apply').returncode, 0)

    def test_non_regular_release_entry_is_rejected(self):
        applied = self.cli('apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        root = Path(json.loads(applied.stdout)['root'])
        os.mkfifo(root / 'unexpected-fifo')
        self.assertNotEqual(self.run_entry('--help').returncode, 0)
        self.assertNotEqual(self.cli('check').returncode, 0)

    def test_second_apply_preserves_managed_files_without_rewriting(self):
        self.assertEqual(self.cli('apply').returncode, 0)
        before = self.entry.stat().st_mtime_ns
        self.assertEqual(self.cli('apply').returncode, 0)
        self.assertEqual(self.entry.stat().st_mtime_ns, before)

    def test_payload_hash_mode_and_license_drift_are_rejected(self):
        applied = self.cli('apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        release = Path(json.loads(applied.stdout)['root'])
        for relative in ('tools/cc-dispatch/cc_dispatch.py', 'LICENSE', 'release.json'):
            with self.subTest(relative=relative):
                target = release / relative
                original = target.read_bytes()
                target.write_bytes(original + b'\nchanged')
                self.assertNotEqual(self.cli('check').returncode, 0)
                self.assertNotEqual(self.run_entry('--help').returncode, 0)
                self.assertNotEqual(self.cli('apply').returncode, 0)
                target.write_bytes(original)
        target = release / 'skills/cc-dispatch/SKILL.md'
        target.chmod(0o755)
        self.assertNotEqual(self.cli('check').returncode, 0)
        self.assertNotEqual(self.run_entry('--help').returncode, 0)

    def test_edited_entry_and_unowned_skill_are_not_overwritten(self):
        self.skill.mkdir(parents=True)
        marker = self.skill / 'SKILL.md'
        marker.write_text('user skill')
        self.assertNotEqual(self.cli('apply').returncode, 0)
        self.assertEqual(marker.read_text(), 'user skill')
        marker.unlink()
        self.skill.rmdir()
        self.assertEqual(self.cli('apply').returncode, 0)
        self.entry.write_text('#!/bin/sh\nexit 42\n')
        self.assertNotEqual(self.cli('apply').returncode, 0)
        self.assertEqual(self.entry.read_text(), '#!/bin/sh\nexit 42\n')

    def test_external_configuration_is_preserved_and_used_from_unrelated_cwd(self):
        config = self.home / '.claude/dispatch/config.json'
        config.parent.mkdir(parents=True)
        content = '{"providers":{"default":{"base_url":"https://gateway.example/api","auth_token":"test-secret-never-print","model":"test-model"}}}'
        config.write_text(content)
        self.assertEqual(self.cli('apply').returncode, 0)
        checked = self.run_entry('check')
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertNotIn('test-secret-never-print', checked.stdout + checked.stderr)
        self.assertEqual(config.read_text(), content)
        self.assertEqual(self.cli('apply').returncode, 0)
        self.assertEqual(config.read_text(), content)

    def test_global_start_keeps_dontask_contract_without_real_session(self):
        config = self.home / '.claude/dispatch/config.json'
        config.parent.mkdir(parents=True)
        config.write_text('{"providers":{"default":{"base_url":"https://gateway.example/api","auth_token":"test-secret","model":"test-model"}}}')
        fake_bin = Path(self.tmp.name).resolve() / 'fake-bin'
        fake_bin.mkdir()
        fake = fake_bin / 'claude'
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        fake.chmod(0o755)
        self.env['PATH'] = str(fake_bin) + os.pathsep + self.env['PATH']
        self.assertEqual(self.cli('apply').returncode, 0)
        result = self.run_entry('start', str(self.cwd), 'test-task', 'read only')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertIn('--permission-mode', args)
        self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
        self.assertNotIn('bypassPermissions', args)
        self.assertNotIn('test-secret', result.stdout + result.stderr)

    def test_mutable_ref_and_missing_local_object_are_rejected_without_writes(self):
        for pin in ('main', self.pin[:7], '0' * 40):
            result = self.cli('apply', pin=pin)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(self.home.iterdir()), [])

    def test_install_uses_git_objects_not_worktree_files_and_never_fetches(self):
        source = Path(self.tmp.name).resolve() / 'source'
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(self.source), str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'remote', 'set-url', 'origin', 'https://invalid.example/no-network'], check=True)
        # A missing worktree payload and ignored credential must not affect export.
        ignored = source / 'tools/cc-dispatch/config.json'
        ignored.parent.mkdir(parents=True)
        ignored.write_text('must never copy')
        # Observe the Git subprocess boundary: reject network commands and lazy fetch.
        bin_dir = Path(self.tmp.name).resolve() / 'bin'
        bin_dir.mkdir()
        audit = bin_dir / 'git-commands'
        real_git = shutil.which('git')
        guard = bin_dir / 'git'
        guard.write_text('#!/bin/sh\n'
                         '[ "$GIT_NO_LAZY_FETCH" = 1 ] || exit 91\n'
                         '[ "$GIT_NO_REPLACE_OBJECTS" = 1 ] || exit 93\n'
                         '[ "${GIT_ALLOW_PROTOCOL-unset}" = "" ] || exit 94\n'
                         'printf "%s\\n" "$*" >> ' + shlex.quote(str(audit)) + '\n'
                         'case "$3" in cat-file|ls-tree) ;; *) exit 92 ;; esac\n'
                         'exec ' + shlex.quote(real_git) + ' "$@"\n')
        guard.chmod(0o755)
        env = dict(self.env, PATH=str(bin_dir) + os.pathsep + self.env['PATH'])
        args = [sys.executable, '-I', str(INSTALLER), 'apply', '--source', str(source), '--commit', self.pin]
        result = subprocess.run(args, cwd=self.cwd, env=env, capture_output=True, text=True)
        self.assertTrue(audit.exists())
        self.assertEqual(result.returncode, 0, result.stderr)
        root = Path(json.loads(result.stdout)['root'])
        self.assertFalse((root / 'tools/cc-dispatch/config.json').exists())
        self.assertEqual(self.run_entry('--help').returncode, 0)


if __name__ == '__main__':
    unittest.main()
