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
        self.registry=self.root/'registry.json';entry={'repo':str(self.repo),'declaration':str(self.decl),'declaration_sha256':sha(self.decl),'pin':'fixture-pin','workenv':'fixture','companions':{str(self.doc):sha(self.doc)},'source_files':{'runtime.txt':sha(self.repo/'runtime.txt'),'not-yet.txt':None},'team_sha256':sha(self.repo/'AGENTS.md')}
        self.registry.write_text(json.dumps({'version':1,'installer':{'path':str(self.installer),'sha256':sha(self.installer)},'clients':{'codex':str(self.native),'trae':str(self.native)},'projects':{str(self.repo/'.git'):entry}}))
    def git(self,root,*args):
        subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def run_gate(self,*args):
        return subprocess.run([sys.executable,str(TOOLS/'botmux_context.py'),'--registry',str(self.registry),*args],env=self.env,text=True,capture_output=True)
    def test_worktree_provision_trust_native_and_repeat(self):
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout);self.assertEqual(result['status'],'PASS');self.assertTrue(all(all(x.values()) for x in result['checks'].values()))
        paths=[self.wt/'.codex/config.toml',self.wt/'.trae/traecli.toml',self.home/'.codex/config.toml',self.home/'.trae/traecli.toml'];before=[p.read_bytes() for p in paths]
        self.assertIn(str(self.wt),paths[2].read_text());r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(before,[p.read_bytes() for p in paths])
    def test_foreign_native_blocks_before_shell_exec(self):
        p=self.wt/'.codex/config.toml';p.parent.mkdir();p.write_text('developer_instructions="user edits"\n');before=p.read_bytes()
        r=self.run_gate('--shell','/bin/bash','--','-i','-c','touch "$1/SHOULD_NOT_EXIST"','_',str(self.wt),'unused')
        self.assertEqual(r.returncode,78);self.assertFalse((self.wt/'SHOULD_NOT_EXIST').exists());self.assertEqual(p.read_bytes(),before)
    def test_missing_companion_and_reviewed_source_drift_block_writes(self):
        for mutation in ['missing','target-source']:
            with self.subTest(mutation=mutation):
                if mutation=='missing':self.doc.unlink()
                else:self.doc.write_text('maintained project convention');(self.wt/'runtime.txt').write_text('changed')
                r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,78);self.assertFalse((self.wt/'.codex/config.toml').exists())
    def test_unregistered_repo_does_not_inherit_even_same_origin(self):
        other=self.root/'other';subprocess.run(['git','clone','-q',str(self.repo),str(other)],check=True)
        r=self.run_gate('--check-cwd',str(other));self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['status'],'unregistered');self.assertFalse((other/'.codex').exists())
    def test_bash_argv_is_preserved_after_preflight(self):
        value='space quote " dollar $ backtick `';r=self.run_gate('--shell','/bin/bash','--','-i','-c','printf "%s" "$2" > "$1/argv.txt"','_',str(self.wt),value)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.wt/'argv.txt').read_text(),value)
    def test_unknown_launch_contract_blocks_shell(self):
        r=self.run_gate('--shell','/bin/bash','--','-c','touch SHOULD_NOT_EXIST');self.assertEqual(r.returncode,78)


if __name__=='__main__':unittest.main()
