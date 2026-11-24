import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1]/'managed_preflight.py'
spec = importlib.util.spec_from_file_location('managed_preflight',SCRIPT)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
SECRET = 'PRIVATE_SECRET_SENTINEL_DO_NOT_RETURN'


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.source = self.root/'source.json'
        self.source.write_text(json.dumps({'key_id':'id','token':SECRET}))
        self.profile = {'version':1,'sources':[{'id':'service','type':'json','path':'source.json',
            'fields':[{'name':'id','keys':['key_id']},{'name':'token','keys':['token'],'secret':True}]}]}

    def run_cli(self, profile=None, env=None):
        path = self.root/'profile.json'; path.write_text(json.dumps(self.profile if profile is None else profile))
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable,'-B',str(SCRIPT),'--profile',str(path)],
            env=env,capture_output=True,text=True,timeout=5)
        after = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertNotIn(SECRET,result.stdout+result.stderr)
        return result.returncode,json.loads(result.stdout)

    def test_present_is_not_authentication_or_session_proof(self):
        code,result = self.run_cli()
        self.assertEqual((code,result['status']),(0,'present'))
        self.assertFalse(result['authentication_verified'])
        self.assertFalse(result['native_session_verified'])
        self.assertEqual(result['question_sources'],[])
        self.assertEqual(result['side_effects'],[])

    def test_missing_secret_recovery_decides_one_question(self):
        self.source.write_text(json.dumps({'key_id':'id'}))
        for recovery,action in [('available','use_managed_recovery'),('unavailable','ask_user'),('unverified','resolve_evidence')]:
            with self.subTest(recovery=recovery):
                self.profile['sources'][0]['recovery']=recovery
                code,result=self.run_cli()
                self.assertEqual((code,result['status']),(2,'missing'))
                self.assertEqual(result['sources'][0]['action'],action)
                self.assertEqual(result['question_sources'],['service'] if action=='ask_user' else [])

    def test_missing_identifier_does_not_request_secret(self):
        self.source.write_text(json.dumps({'token':SECRET}))
        self.profile['sources'][0]['recovery']='unavailable'
        _,result=self.run_cli()
        self.assertEqual(result['sources'][0]['action'],'discover_identifiers')
        self.assertEqual(result['question_sources'],[])

    def test_missing_file_is_not_invalid_authentication(self):
        self.source.unlink()
        _,result=self.run_cli()
        self.assertEqual(result['status'],'missing')
        self.assertEqual(result['sources'][0]['supplied_authentication'],'unverified')

    def test_unreadable_json_shapes_never_echo_values(self):
        for data in ['{'+SECRET,'["'+SECRET+'"]','"'+SECRET+'"','['*1100]:
            with self.subTest(data=data[:1]):
                self.source.write_text(data)
                code,result=self.run_cli()
                self.assertEqual((code,result['status']),(2,'unverified'))
                self.assertEqual(result['question_sources'],[])

    def test_permission_failure_is_unverified_not_credential_question(self):
        with patch.object(module,'read_json',side_effect=PermissionError(SECRET)):
            result=module.preflight(self.profile,base=self.root,environ={})
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['question_sources'],[])
        self.assertNotIn(SECRET,json.dumps(result))

    def test_environment_is_current_process_only(self):
        source=self.profile['sources'][0]
        source.update(type='environment',fields=[{'name':'token','keys':['EXAMPLE_PREFLIGHT_TOKEN'],'secret':True}])
        source.pop('path')
        env=dict(os.environ,EXAMPLE_PREFLIGHT_TOKEN=SECRET)
        self.assertEqual(self.run_cli(env=env)[1]['status'],'present')
        env.pop('EXAMPLE_PREFLIGHT_TOKEN')
        self.assertEqual(self.run_cli(env=env)[1]['status'],'missing')

    def test_supplied_invalid_authentication_requires_reference_and_recovery(self):
        source=self.profile['sources'][0];source.update(authentication='invalid',recovery='unavailable')
        self.assertEqual(self.run_cli()[1]['reason'],'profile_unavailable_or_invalid')
        source['authentication_evidence_ref']='private-observation'
        code,result=self.run_cli()
        self.assertEqual(code,2);self.assertEqual(result['status'],'present')
        self.assertEqual(result['question_sources'],['service'])
        self.assertFalse(result['authentication_verified'])
        source['recovery']='available'
        self.assertEqual(self.run_cli()[1]['sources'][0]['action'],'use_managed_recovery')

    def test_duplicate_source_or_invalid_fields_fail_closed(self):
        cases=[]
        duplicate=copy.deepcopy(self.profile);duplicate['sources']*=2;cases.append(duplicate)
        for value in ([],True,{'version':True,'sources':self.profile['sources']}):cases.append(value)
        for profile in cases:
            code,result=self.run_cli(profile)
            self.assertEqual((code,result['status']),(2,'unverified'))
            self.assertEqual(result['question_sources'],[])

    def test_special_and_oversize_files_are_bounded(self):
        self.source.write_bytes(b'x'*(module.MAX_BYTES+1))
        self.assertEqual(self.run_cli()[1]['status'],'unverified')
        self.source.unlink();self.source.mkdir()
        self.assertEqual(self.run_cli()[1]['status'],'unverified')

    def test_explicit_compatibility_alias_and_empty_value(self):
        alias=self.root/'alias.json';alias.symlink_to(self.source)
        self.profile['sources'][0]['path']='alias.json'
        self.assertEqual(self.run_cli()[1]['status'],'present')
        for value in (None,'',[],{}):
            self.source.write_text(json.dumps({'key_id':'id','token':value}))
            self.assertEqual(self.run_cli()[1]['status'],'missing')


if __name__ == '__main__': unittest.main()
