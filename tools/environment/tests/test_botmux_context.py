#!/usr/bin/env python3
"""Real renderer + Git worktrees; fake no-model clients, no machine config."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS=Path(__file__).resolve().parents[1]


class Startup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.repo=self.root/'repo';self.repo.mkdir()
        self.home=self.root/'home';self.home.mkdir()
        self.env=dict(os.environ,HOME=str(self.home),CODEX_HOME=str(self.home/'.codex'),TRAE_HOME=str(self.home/'.trae'),PYTHONDONTWRITEBYTECODE='1')
        self.git(self.repo,'init','-q');self.git(self.repo,'config','user.email','probe@example.invalid');self.git(self.repo,'config','user.name','Probe')
        (self.repo/'AGENTS.md').write_text('Team "quoted" guidance\nsecond line\n');(self.repo/'runtime.txt').write_text('reviewed behavior')
        self.git(self.repo,'add','.');self.git(self.repo,'commit','-qm','fixture')
        (self.repo/'.git/info/exclude').write_text('/.codex/config.toml\n/.trae/traecli.toml\n/.ai-workbench/\n')
        self.wt=self.root/'worktree';self.git(self.repo,'worktree','add','-q','--detach',str(self.wt))
        self.doc=self.repo/'conventions.md';self.doc.write_text('maintained project convention')
        self.decl=self.repo/'declaration.json';self.decl.write_text(json.dumps({'version':1,'instructions':'PROJECT_PRIVATE\nRead '+str(self.doc),'additiveEntry':{'clients':['codex','trae']}}))
        self.installer=self.root/'setup';self.installer.write_text('#!'+sys.executable+'\nimport runpy,sys\nsys.path.insert(0,'+repr(str(TOOLS))+')\nrunpy.run_path('+repr(str(TOOLS/'project_context.py'))+',run_name="__main__")\n');self.installer.chmod(0o755)
        self.native=self.root/'native';self.native.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nimport json,tomllib\np=Path.cwd();d=tomllib.loads((p/".codex/config.toml").read_text())["developer_instructions"]\nprint(json.dumps([{"role":"developer","content":d},{"role":"user","content":(p/"AGENTS.md").read_text()}]))\n');self.native.chmod(0o755)
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        self.registry=self.root/'registry.json';entry={'repo':str(self.repo),'declaration':str(self.decl),'declaration_sha256':sha(self.decl),'pin':'fixture-pin','workenv':'fixture','companions':{str(self.doc):sha(self.doc)},'analysis_revision':subprocess.check_output(['git','-C',str(self.repo),'rev-parse','HEAD'],text=True).strip(),'source_files':{'runtime.txt':sha(self.repo/'runtime.txt'),'not-yet.txt':None},'team_sha256':sha(self.repo/'AGENTS.md')}
        self.registry.write_text(json.dumps({'version':1,'installer':{'path':str(self.installer),'sha256':sha(self.installer)},'clients':{'codex':str(self.native),'trae':str(self.native)},'projects':{str(self.repo/'.git'):entry}}))
    def git(self,root,*args):
        subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def run_gate(self,*args):
        return subprocess.run([sys.executable,str(TOOLS/'botmux_context.py'),'--registry',str(self.registry),*args],env=self.env,text=True,capture_output=True)
    def test_worktree_provision_trust_native_and_repeat(self):
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout);self.assertEqual(result['status'],'PASS');self.assertEqual(result['analysis']['status'],'CURRENT');self.assertTrue(all(all(x.values()) for x in result['checks'].values()))
        paths=[self.wt/'.codex/config.toml',self.wt/'.trae/traecli.toml',self.home/'.codex/config.toml',self.home/'.trae/traecli.toml'];before=[p.read_bytes() for p in paths]
        self.assertIn(str(self.wt),paths[2].read_text());r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(before,[p.read_bytes() for p in paths])
    def test_foreign_native_blocks_before_shell_exec(self):
        p=self.wt/'.codex/config.toml';p.parent.mkdir();p.write_text('developer_instructions="user edits"\n');before=p.read_bytes()
        r=self.run_gate('--shell','/bin/bash','--','-i','-c','touch "$1/SHOULD_NOT_EXIST"','_',str(self.wt),'unused')
        self.assertEqual(r.returncode,78);self.assertFalse((self.wt/'SHOULD_NOT_EXIST').exists());self.assertEqual(p.read_bytes(),before)
    def test_missing_companion_blocks_writes(self):
        self.doc.unlink()
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,78);self.assertFalse((self.wt/'.codex/config.toml').exists())
    def test_changed_working_tree_is_stale_without_blocking(self):
        (self.wt/'runtime.txt').write_text('changed')
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        analysis=json.loads(r.stdout)['analysis'];self.assertEqual(analysis['status'],'STALE')
        self.assertEqual(analysis['differences'][0]['path'],'runtime.txt')
        self.assertIn('AIWB_CONTEXT_ANALYSIS_STALE',r.stderr)
    def test_legacy_or_empty_analysis_is_not_reported_as_current(self):
        registry=json.loads(self.registry.read_text());entry=next(iter(registry['projects'].values()))
        for field in ['analysis_revision','source_files']:
            if field=='analysis_revision':entry.pop(field)
            else:entry[field]={}
            self.registry.write_text(json.dumps(registry))
            r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(r.stdout)['analysis']['status'],'UNVERIFIED')
    def test_older_worktree_keeps_analysis_evidence_and_starts(self):
        (self.wt/'runtime.txt').unlink()
        (self.wt/'not-yet.txt').write_text('branch-specific implementation')
        self.git(self.wt,'add','runtime.txt','not-yet.txt');self.git(self.wt,'commit','-qm','parallel branch')
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout);self.assertEqual(result['analysis']['status'],'UNVERIFIED')
        self.assertEqual(result['analysis']['reason'],'different_revision')
        self.assertEqual(result['analysis']['checked_files'],0)
        self.assertIn('AIWB_CONTEXT_ANALYSIS_UNVERIFIED',r.stderr)
        self.assertFalse((self.wt/'runtime.txt').exists())
        self.assertEqual(len(next(iter(json.loads(self.registry.read_text())['projects'].values()))['source_files']),2)
    def test_tracked_team_guidance_uses_current_worktree(self):
        team=self.wt/'AGENTS.md';team.write_text('This branch has its own team guidance\n')
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout);self.assertTrue(result['team_guidance']['differs_from_registration'])
        self.assertEqual(team.read_text(),'This branch has its own team guidance\n')
        self.assertTrue(all(c['team_guidance'] for c in result['checks'].values()))
    def test_unregistered_repo_does_not_inherit_even_same_origin(self):
        other=self.root/'other';subprocess.run(['git','clone','-q',str(self.repo),str(other)],check=True)
        r=self.run_gate('--check-cwd',str(other));self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['status'],'unregistered');self.assertFalse((other/'.codex').exists())
    def test_bash_argv_is_preserved_after_preflight(self):
        value='space quote " dollar $ backtick `';r=self.run_gate('--shell','/bin/bash','--','-i','-c','printf "%s" "$2" > "$1/argv.txt"','_',str(self.wt),value)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.wt/'argv.txt').read_text(),value)
    def native_companion(self):
        policy=self.root/'native-policy';policy.write_text('skip selected legacy project resources\n')
        data=json.loads(self.registry.read_text());entry=next(iter(data['projects'].values()));entry['native_companions']={'.trae/legacy-state':{'source':str(policy),'sha256':hashlib.sha256(policy.read_bytes()).hexdigest()}}
        self.registry.write_text(json.dumps(data));f=self.repo/'.git/info/exclude';f.write_text(f.read_text()+'/.trae/legacy-state\n');return policy
    def test_native_companion_copied_without_overwriting_foreign_state(self):
        policy=self.native_companion();r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr);target=self.wt/'.trae/legacy-state';self.assertEqual(target.read_bytes(),policy.read_bytes())
        target.write_text('user state');r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,78);self.assertEqual(target.read_text(),'user state')
    def test_native_owned_seed_preserves_existing_per_checkout_state(self):
        self.native_companion();data=json.loads(self.registry.read_text());entry=next(iter(data['projects'].values()))
        entry['native_companions']['.trae/legacy-state']['seed_only']=True;self.registry.write_text(json.dumps(data))
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        target=self.wt/'.trae/legacy-state';target.write_text('native client already migrated this checkout')
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(target.read_text(),'native client already migrated this checkout')
        self.assertFalse(json.loads(r.stdout)['native_companions']['.trae/legacy-state']['created'])
    def test_shell_failure_has_durable_sanitized_reason(self):
        policy=self.native_companion();policy.unlink();r=self.run_gate('--shell','/bin/bash','--','-i','-c','touch "$1/SHOULD_NOT_EXIST"','_',str(self.wt),'unused');self.assertEqual(r.returncode,78)
        record=json.loads(next((self.root/'failures').glob('*.json')).read_text());self.assertEqual(record['error_code'],'AIWB_CONTEXT_STARTUP_BLOCKED');self.assertNotIn('SHOULD_NOT_EXIST',json.dumps(record));self.assertFalse((self.wt/'SHOULD_NOT_EXIST').exists())
    def test_legacy_tool_release_manifest_remains_verifiable(self):
        import importlib.util,shutil
        sys.path.insert(0,str(TOOLS))
        spec=importlib.util.spec_from_file_location('startup_installer',TOOLS/'install_project_context.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        legacy=self.root/'legacy-release';legacy.mkdir();names=set(module.FILES)-{'botmux_context.py','cli_context.py','native_worktree.py'}
        for name in names:shutil.copy2(TOOLS/name,legacy/name)
        (legacy/'release.json').write_text(json.dumps({'files':{name:hashlib.sha256((legacy/name).read_bytes()).hexdigest() for name in names}}))
        self.assertEqual(set(module.verify(legacy)['files']),names)
    def test_unknown_launch_contract_blocks_shell(self):
        r=self.run_gate('--shell','/bin/bash','--','-c','touch SHOULD_NOT_EXIST');self.assertEqual(r.returncode,78)


if __name__=='__main__':unittest.main()
