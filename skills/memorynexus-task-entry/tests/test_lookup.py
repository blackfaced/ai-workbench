import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/lookup.py'


class TaskLookup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.index = Path(self.temp.name) / 'index.json'
        self.task = {'task_id': str(uuid.uuid4()), 'name': '主题研究任务',
                     'aliases': ['主题研究'], 'binding': '/unavailable/private/binding.json',
                     'description': '隔离查找用例'}

    def run_lookup(self, tasks, name):
        self.index.write_text(json.dumps({'schema_version': 1, 'tasks': tasks}))
        os.chmod(self.index, 0o600)
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT), '--index', str(self.index),
                               '--name', name], capture_output=True, check=False)
        return proc.returncode, json.loads(proc.stdout)

    def test_exact_name_and_alias(self):
        for name in ('主题研究任务', '主题研究'):
            with self.subTest(name=name):
                code, value = self.run_lookup([self.task], name)
                self.assertEqual((code, value['status']), (0, 'matched'))
                self.assertEqual(value['matches'][0]['task_id'], self.task['task_id'])

    def test_normalized_name(self):
        task = dict(self.task, name='Agent Topic')
        self.assertEqual(self.run_lookup([task], 'ＡＧＥＮＴ   topic')[1]['status'], 'matched')

    def test_duplicate_name_or_alias_requires_selection_without_reading_bindings(self):
        for other in (dict(self.task, task_id=str(uuid.uuid4())),
                      dict(self.task, task_id=str(uuid.uuid4()), name='另一任务', aliases=['主题研究任务'])):
            with self.subTest(other=other['name']):
                code, value = self.run_lookup([self.task, other], self.task['name'])
                self.assertEqual((code, value['status']), (0, 'choose'))
                self.assertEqual({v['task_id'] for v in value['matches']},
                                 {self.task['task_id'], other['task_id']})

    def test_unknown_name_never_falls_back(self):
        code, value = self.run_lookup([self.task], '未登记主题')
        self.assertEqual((code, value['status'], value['matches']), (0, 'not_found', []))

    def test_duplicate_identity_is_invalid(self):
        self.assertEqual(self.run_lookup([self.task, self.task], self.task['name'])[0], 2)

    def test_missing_or_nonprivate_index_is_not_empty_success(self):
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT), '--index', str(self.index),
                               '--name', self.task['name']], capture_output=True)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)['status']), (2, 'error'))
        self.run_lookup([self.task], self.task['name'])
        os.chmod(self.index, 0o644)
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT), '--index', str(self.index),
                               '--name', self.task['name']], capture_output=True)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)['status']), (2, 'error'))

    def test_name_is_data_not_shell_code(self):
        marker = Path(self.temp.name) / 'not-created'
        name = 'topic; touch ' + str(marker)
        task = dict(self.task, name=name)
        self.assertEqual(self.run_lookup([task], name)[1]['status'], 'matched')
        self.assertFalse(marker.exists())

    def list_tasks(self):
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT), '--index', str(self.index),
                               '--list'], capture_output=True)
        return proc.returncode, json.loads(proc.stdout)

    def test_list_preserves_duplicate_names_without_opening_or_exposing_bindings(self):
        second = dict(self.task, task_id=str(uuid.uuid4()))
        self.run_lookup([self.task, second], self.task['name'])
        code, value = self.list_tasks()
        self.assertEqual((code, value['status']), (0, 'listed'))
        self.assertEqual(value['tasks'], [
            {k: item[k] for k in ('task_id', 'name', 'description')}
            for item in (self.task, second)])

    def test_list_empty_and_invalid_indexes_are_distinct(self):
        self.run_lookup([], 'unused')
        self.assertEqual(self.list_tasks(), (0, {'schema_version': 1, 'status': 'listed', 'tasks': []}))
        os.chmod(self.index, 0o644)
        code, value = self.list_tasks()
        self.assertEqual((code, value['status']), (2, 'error'))
        self.run_lookup([self.task, self.task], self.task['name'])
        self.assertEqual(self.list_tasks()[0], 2)

    def test_list_and_name_are_mutually_exclusive(self):
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT), '--list', '--name', 'name'],
                              capture_output=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == '__main__':
    unittest.main()
