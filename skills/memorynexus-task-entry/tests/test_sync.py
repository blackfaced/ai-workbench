import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import sync


class TaskSync(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.index = self.root / 'tasks.json'
        self.task_id, self.local_id, self.peer_id, self.epoch, self.round_id = (
            str(uuid.uuid4()) for _ in range(5))
        self.local = self.root / 'local-endpoint'
        self.peer = self.root / 'peer-endpoint'
        for path in (self.local, self.peer):
            path.write_text('#!/bin/sh\nexit 99\n')
            path.chmod(0o700)

        def ref(path):
            return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

        self.device = {'device_id': self.peer_id, 'name': '开发机',
                       'aliases': ['Linux Dev'], 'description': '隔离配对',
                       'endpoint': ref(self.peer)}
        self.task = {'task_id': self.task_id, 'name': '色卡任务', 'aliases': ['色卡'],
                     'binding': str(self.root / 'binding.json'),
                     'relay': {'local': ref(self.local), 'devices': [self.device]}}
        self.args = argparse.Namespace(index=self.index, task='色卡', device='ＬＩＮＵＸ   dev',
                                       task_id=None, device_id=None)
        self.write_index([self.task])
        self.before = self.progress(self.local_id, self.peer_id)
        self.other_before = self.progress(self.peer_id, self.local_id)
        self.read = ['pinned-python', 'daily.py', 'read']
        self.refresh = ['pinned-python', 'refresh_peer.py']
        self.calls = []

    def write_index(self, tasks):
        self.index.write_text(json.dumps({'schema_version': 1, 'tasks': tasks}))
        os.chmod(self.index, 0o600)

    def progress(self, sender, receiver):
        return {'task_id': self.task_id, 'device': sender, 'peer': receiver, 'epoch': self.epoch,
                'outgoing': {'through': 0, 'covered': False, 'pending_count': 1},
                'incoming': {'through': 0, 'covered': False}, 'subsequent_peer_tail': 'unknown'}

    def completed(self):
        def state(before, pending):
            done = {'target': 1, 'covered': True, 'through': 1}
            return {**before, 'round': self.round_id, 'incoming': done,
                    'outgoing': {**done, 'pending_count': pending}}
        return {'round': self.round_id, 'local': state(self.before, 1),
                'peer': state(self.other_before, 0),
                'targets': {'local': {'after': 0, 'through': 1},
                            'peer': {'after': 0, 'through': 1}}}

    def run_sync(self, *, reply=None, peer=None, refresh_fails=False):
        def external(argv, *_, **options):
            self.calls.append(argv)
            if argv == self.read:
                return {'schema_version': 1, 'status': 'ok', 'context': {
                    'task_id': self.task_id, 'result': {'relay_progress': self.before}}}
            if argv in ([str(self.local), 'status'], [str(self.peer), 'status']):
                value = self.before if argv[0] == str(self.local) else peer
                if value == 'offline':
                    raise sync.SyncError('endpoint_unavailable')
                return {'schema_version': 1, 'status': 'ok', 'task_id': self.task_id,
                        'result': value if value is not None else self.other_before}
            self.assertEqual(argv, [*self.refresh, '--local', str(self.local), '--peer', str(self.peer)])
            if refresh_fails:
                raise sync.SyncError('refresh_unconfirmed')
            return self.completed() if reply is None else reply

        with mock.patch.object(sync, 'runtime', return_value=(self.read, self.refresh, 'cli')) as runtime:
            with mock.patch.object(sync, 'call', side_effect=external):
                result = sync.sync(self.args)
            return result, runtime.call_count

    def test_both_receipts_required_and_pending_tail_is_preserved(self):
        result, _ = self.run_sync()
        self.assertEqual(result['status'], 'synced')
        self.assertEqual(result['round'], self.round_id)
        self.assertEqual(result['outgoing']['pending_count'], 1)
        self.assertEqual(result['incoming']['pending_count'], 0)
        self.assertEqual((result['path'], result['subsequent_peer_tail']), ('unknown', 'unknown'))

        broken = self.completed()
        broken['peer']['outgoing']['covered'] = False
        result, _ = self.run_sync(reply=broken)
        self.assertEqual((result['status'], result['code']), ('pending', 'invalid_refresh_result'))
        self.assertNotIn('round', result)

    def test_missing_target_or_conflicting_round_cannot_be_success(self):
        for field in ('target', 'round'):
            with self.subTest(field=field):
                reply = self.completed()
                if field == 'round':
                    reply['peer']['round'] = str(uuid.uuid4())
                else:
                    del reply['peer']['incoming'][field]
                result, _ = self.run_sync(reply=reply)
                self.assertEqual(result['status'], 'pending')

    def test_offline_preflight_preserves_last_observed_position(self):
        result, _ = self.run_sync(peer='offline')
        self.assertEqual((result['status'], result['code']), ('pending', 'endpoint_unavailable'))
        self.assertEqual(result['last_observed']['outgoing']['pending_count'], 1)
        self.assertEqual(result['last_observed']['incoming']['through'], 0)
        self.assertFalse(any(argv[:2] == self.refresh for argv in self.calls))

    def test_failure_after_attempt_does_not_claim_current_round(self):
        result, _ = self.run_sync(refresh_fails=True)
        self.assertEqual((result['status'], result['code']), ('pending', 'refresh_unconfirmed'))
        self.assertIn('last_observed', result)
        self.assertNotIn('round', result)

    def test_wrong_peer_scope_stops_before_refresh(self):
        other = dict(self.other_before, task_id=str(uuid.uuid4()))
        with self.assertRaisesRegex(sync.SyncError, 'endpoint_identity_mismatch'):
            self.run_sync(peer=other)
        self.assertFalse(any(argv[:2] == self.refresh for argv in self.calls))

    def test_device_id_must_match_authoritative_pair_before_any_endpoint(self):
        self.device['device_id'] = str(uuid.uuid4())
        self.write_index([self.task])
        with self.assertRaisesRegex(sync.SyncError, 'device_not_paired_to_task'):
            self.run_sync()
        self.assertEqual(self.calls, [self.read])

    def test_ambiguous_task_and_device_do_not_open_bindings(self):
        other_task = dict(self.task, task_id=str(uuid.uuid4()))
        self.write_index([self.task, other_task])
        result, opened = self.run_sync()
        self.assertEqual((result['status'], opened), ('choose_task', 0))
        self.assertNotIn('binding', result['matches'][0])
        self.args.task_id = self.task_id

        other_device = dict(self.device, device_id=str(uuid.uuid4()))
        self.task['relay']['devices'].append(other_device)
        self.write_index([self.task, other_task])
        result, opened = self.run_sync()
        self.assertEqual((result['status'], opened), ('choose_device', 0))
        self.assertNotIn('endpoint', result['matches'][0])
        self.args.device_id = self.peer_id
        self.assertEqual(self.run_sync()[0]['status'], 'synced')

    def test_unknown_names_and_changed_selections_never_run(self):
        for field, value, status in (
            ('task', '未知任务', 'task_not_found'),
            ('device', '未知设备', 'device_not_found'),
            ('device_id', str(uuid.uuid4()), 'device_not_found'),
        ):
            with self.subTest(field=field):
                previous = getattr(self.args, field)
                setattr(self.args, field, value)
                result, opened = self.run_sync()
                self.assertEqual((result['status'], opened), (status, 0))
                setattr(self.args, field, previous)

    def test_endpoint_pin_change_stops_before_probe(self):
        self.peer.write_text('#!/bin/sh\nexit 98\n')
        with self.assertRaisesRegex(sync.SyncError, 'invalid_endpoint_pin'):
            self.run_sync()
        self.assertEqual(self.calls, [self.read])

    def test_invalid_binding_cannot_run(self):
        path = Path(self.task['binding'])
        path.write_text('{}')
        path.chmod(0o644)
        proc = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'sync.py'), '--index', str(self.index),
                               '--task', '色卡', '--device', '开发机'], capture_output=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)['code'], 'invalid_binding')

    def test_unpinned_package_cannot_run(self):
        directory = self.root / 'package'
        directory.mkdir()
        daily = directory / 'daily.py'
        daily.write_text('raise AssertionError("must not run")\n')
        (directory / 'refresh_peer.py').touch()
        binding = Path(self.task['binding'])
        binding.write_text(json.dumps({'schema_version': 1, 'task_id': self.task_id,
                                       'package': str(directory), 'package_sha256': '0' * 64}))
        binding.chmod(0o600)
        with self.assertRaisesRegex(sync.SyncError, 'invalid_package_pin'):
            sync.runtime(self.task)


if __name__ == '__main__':
    unittest.main()
