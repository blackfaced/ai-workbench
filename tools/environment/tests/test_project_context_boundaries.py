#!/usr/bin/env python3
"""New project-owned rules, explicit trust, concurrency and install boundaries."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
import project_context as pc
import context_io


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.repo=self.root/'repo';self.repo.mkdir()
        self.home=self.root/'home';self.home.mkdir()
        self.env=dict(os.environ,HOME=str(self.home),CODEX_HOME=str(self.home/'.codex'),PYTHONDONTWRITEBYTECODE='1')
        self.decl=self.repo/'context.json'
        self.decl.write_text(json.dumps({'instructions':'PROJECT_PRIVATE_TEST','additiveEntry':{'clients':['codex']}}))
    def run_pc(self,*extra,repo=None,decl=True):
        args=[sys.executable,str(TOOLS/'project_context.py'),'--repo',str(repo or self.repo)]
        if decl: args+=['--declaration',str(self.decl)]
        return subprocess.run(args+list(extra),env=self.env,capture_output=True,text=True)
    def config(self,repo=None): return (repo or self.repo)/'.codex/config.toml'
    def backups(self): return sorted((self.repo/'.ai-workbench/project-context/backups').iterdir())
    def test_project_owned_not_builtin(self):
        p=self.run_pc('--apply');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        text=self.config().read_text();self.assertIn('PROJECT_PRIVATE_TEST',text)
        self.assertNotIn('LAS',text);self.assertNotIn('Meego',text);self.assertNotIn('m-<id>',text)
    def test_trust_default_off_even_declaration_true(self):
        d=json.loads(self.decl.read_text());d['trust']=True;self.decl.write_text(json.dumps(d))
        self.assertEqual(self.run_pc('--apply').returncode,0)
        self.assertFalse((self.home/'.codex/config.toml').exists())
    def test_unknown_fields_and_false_types_block(self):
        for d in [{'instructions':'x','files':'oops'},{'instructions':'x','trust':'false'}, {'tracker':{'kind':'foo','workItemIdRequired':True}}, {'instructions':'x','additiveEntry':{'files':{'codex':'elsewhere'}}}]:
            self.decl.write_text(json.dumps(d));self.assertNotEqual(self.run_pc('--apply').returncode,0)
        self.assertFalse(self.config().exists())
    def test_literal_delimiter_encoded(self):
        self.decl.write_text(json.dumps({'instructions':"contains ''' and a quotation \""}))
        p=self.run_pc('--apply');self.assertEqual(p.returncode,0,p.stderr)
        import tomllib
        self.assertIn("contains '''",tomllib.loads(self.config().read_text())['developer_instructions'])
    def test_parser_missing_no_write(self):
        with patch.object(pc,'load_toml_parser',return_value=None):
            plan=pc.build_plan(str(self.repo),'project','pin','project',['codex'],[],'rule')
            self.assertTrue(plan['blocked']);self.assertFalse(plan['changes'])
        self.assertFalse(self.config().exists())
    def test_no_duplicate_owned_block_adoption(self):
        self.assertEqual(self.run_pc('--apply').returncode,0)
        text=self.config().read_text();self.config().write_text(text+text)
        self.assertNotEqual(self.run_pc('--apply').returncode,0)
    def test_legacy_no_declaration_retains_owned(self):
        self.decl.write_text(json.dumps({'profiles':{'las-full':'LEGACY_PROJECT_OWNED'}}))
        self.assertEqual(self.run_pc('--profile','las-full','--apply').returncode,0)
        before=self.config().read_bytes()
        self.assertEqual(self.run_pc('--profile','las-full','--check',decl=False).returncode,0)
        self.assertEqual(before,self.config().read_bytes())
    def test_rules_source_pin(self):
        source=self.repo/'rules.txt';source.write_text('rule from project')
        self.decl.write_text(json.dumps({'rulesSource':{'path':'rules.txt','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}))
        self.assertEqual(self.run_pc('--apply').returncode,0)
        source.write_text('changed');self.assertNotEqual(self.run_pc('--apply').returncode,0)
    def test_same_project_concurrent(self):
        cmd=[sys.executable,str(TOOLS/'project_context.py'),'--repo',str(self.repo),'--declaration',str(self.decl),'--apply']
        jobs=[subprocess.Popen(cmd,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(5)]
        for p in jobs:
            out,err=p.communicate(timeout=60);self.assertEqual(p.returncode,0,err+out)
        self.assertEqual(self.config().read_text().count('# setup-aiwb:project-context BEGIN'),1)
        self.assertEqual(self.run_pc('--check').returncode,0)
    def test_different_projects_share_trust(self):
        repos=[self.repo,self.root/'repo2'];repos[1].mkdir()
        jobs=[]
        for r in repos:
            cmd=[sys.executable,str(TOOLS/'project_context.py'),'--repo',str(r),'--declaration',str(self.decl),'--manage-trust','--apply']
            jobs.append(subprocess.Popen(cmd,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        for p in jobs:
            out,err=p.communicate(timeout=60);self.assertEqual(p.returncode,0,err+out)
        import tomllib
        trust=tomllib.loads((self.home/'.codex/config.toml').read_text())['projects']
        for r in repos:self.assertEqual(trust[str(r)]['trust_level'],'trusted')
    def test_explicit_untrusted_preserved(self):
        g=self.home/'.codex/config.toml';g.parent.mkdir();g.write_text('[projects.'+json.dumps(str(self.repo))+']\ntrust_level="untrusted"\n')
        before=g.read_bytes();self.assertNotEqual(self.run_pc('--manage-trust','--apply').returncode,0)
        self.assertEqual(before,g.read_bytes());self.assertFalse(self.config().exists())
    def test_foreign_edit_force_cannot_takeover(self):
        self.assertEqual(self.run_pc('--apply').returncode,0)
        self.config().write_text(self.config().read_text().replace('PROJECT_PRIVATE_TEST','edited'))
        self.assertNotEqual(self.run_pc('--apply','--force').returncode,0)
        self.assertIn('edited',self.config().read_text())
    def test_drift_between_plan_apply(self):
        self.assertEqual(self.run_pc('--apply').returncode,0)
        plan=pc.build_plan(str(self.repo),'project','other-pin','project',['codex'],[],'new-rule')
        cid,_,s=plan['changes'][0];s['cid_key']=cid
        self.config().write_text(self.config().read_text()+'# human\n')
        with self.assertRaisesRegex(RuntimeError,'drift'):pc.execute_change(pc.Ctx(str(self.repo)),s)
        self.assertIn('# human',self.config().read_text())
    def test_restore_update_preserves_crlf_and_outside(self):
        self.config().parent.mkdir();self.config().write_bytes(b'base=true\r\n')
        self.assertEqual(self.run_pc('--apply').returncode,0)
        first=self.config().read_bytes()
        self.decl.write_text(json.dumps({'instructions':'NEW'}));self.assertEqual(self.run_pc('--apply').returncode,0)
        self.config().write_bytes(self.config().read_bytes()+b'# human\r\n')
        p=self.run_pc('--restore',self.backups()[-1].name);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(self.config().read_bytes(),first+b'# human\r\n')
    def test_trust_restore_does_not_clobber_other_projects(self):
        self.assertEqual(self.run_pc('--manage-trust','--apply').returncode,0)
        b=self.backups()[-1].name
        g=self.home/'.codex/config.toml';g.write_text(g.read_text()+'\n[projects."/unrelated"]\ntrust_level="untrusted"\n')
        p=self.run_pc('--restore',b);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('/unrelated',g.read_text());self.assertNotIn(str(self.repo),g.read_text())
    def test_restore_manifest_path_escape_rejected(self):
        self.assertEqual(self.run_pc('--apply').returncode,0)
        b=self.backups()[-1];m=json.loads((b/'manifest.json').read_text());m['entries'][0]['original_path']=str(self.root/'victim.toml')
        (b/'manifest.json').write_text(json.dumps(m));self.assertNotEqual(self.run_pc('--restore',b.name).returncode,0)
        self.assertFalse((self.root/'victim.toml').exists())
    def test_install_upgrade_rollback_immutable_and_edited_entry(self):
        base=self.root/'releases';entry=self.root/'bin/context';installer=TOOLS/'install_project_context.py'
        def run(action,version):
            return subprocess.run([sys.executable,str(installer),action,'--root',str(base),'--entry',str(entry),'--version',version],env=self.env,capture_output=True,text=True)
        for a,v in [('install','test-v1'),('check','test-v1'),('install','test-v2'),('check','test-v2'),('rollback','test-v1'),('check','test-v1')]:
            p=run(a,v);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('test-v1',entry.read_text());self.assertNotIn(str(TOOLS),entry.read_text())
        manifest=base/'test-v1/release.json'
        original=manifest.read_bytes();manifest.write_text('{}')
        p=subprocess.run([str(entry),'--help'],env=self.env,capture_output=True)
        self.assertNotEqual(p.returncode,0)
        manifest.write_bytes(original)
        (base/'test-v1/env.py').write_text('tampered')
        self.assertNotEqual(run('check','test-v1').returncode,0)
        entry.write_text(entry.read_text()+'# user edit\n');self.assertNotEqual(run('rollback','test-v2').returncode,0)
    def test_upgrade_different_payload_and_deleted_source(self):
        import install_project_context as installer
        source=self.root/'source';source.mkdir()
        for name in installer.FILES: shutil.copy2(TOOLS/name,source/name)
        base=self.root/'versions';entry=self.root/'bin/pinned'
        def install(v):
            return subprocess.run([sys.executable,str(source/'install_project_context.py'),'install','--root',str(base),'--entry',str(entry),'--version',v],env=self.env,capture_output=True,text=True)
        self.assertEqual(install('v1').returncode,0)
        with (source/'project_context.py').open('a') as h:h.write('\n# changed candidate payload\n')
        self.assertNotEqual(install('v1').returncode,0)
        self.assertEqual(install('v2').returncode,0)
        one=json.loads((base/'v1/release.json').read_text());two=json.loads((base/'v2/release.json').read_text())
        self.assertNotEqual(one['files']['project_context.py'],two['files']['project_context.py'])
        shutil.rmtree(source)
        self.assertEqual(subprocess.run([str(entry),'--help'],env=self.env,capture_output=True).returncode,0)
        p=subprocess.run([sys.executable,str(base/'v2/install_project_context.py'),'rollback','--root',str(base),'--entry',str(entry),'--version','v1'],env=self.env,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('/v1',entry.read_text())
        self.assertEqual(subprocess.run([str(entry),'--help'],env=self.env,capture_output=True).returncode,0)
    def test_actual_tracked_config_refused(self):
        subprocess.run(['git','init',str(self.repo)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        self.config().parent.mkdir();self.config().write_text('team=true\n')
        subprocess.run(['git','-C',str(self.repo),'add','.codex/config.toml'],check=True)
        self.assertNotEqual(self.run_pc('--apply').returncode,0)
        self.assertEqual(self.config().read_text(),'team=true\n')
    def test_real_git_worktree(self):
        subprocess.run(['git','init',str(self.repo)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        (self.repo/'AGENTS.md').write_text('TEAM_TEST_GUIDANCE')
        subprocess.run(['git','-C',str(self.repo),'add','AGENTS.md'],check=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture'],stdout=subprocess.DEVNULL,check=True)
        wt=self.root/'wt';subprocess.run(['git','-C',str(self.repo),'worktree','add','--detach',str(wt)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        p=self.run_pc('--worktree',str(wt),'--apply');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('PROJECT_PRIVATE_TEST',self.config(wt).read_text());self.assertEqual((wt/'AGENTS.md').read_text(),'TEAM_TEST_GUIDANCE')


if __name__=='__main__':unittest.main(verbosity=2)
