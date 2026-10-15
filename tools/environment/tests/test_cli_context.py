#!/usr/bin/env python3
"""Direct launches reuse real renderer; isolated HOME and recording native CLI."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from test_botmux_context import Startup, TOOLS
sys.path.insert(0,str(TOOLS))
import cli_context


class Direct(Startup):
    # Inherited tests also exercise the shared implementation after refactoring.
    def setUp(self):
        super().setUp()
        old=self.native.read_text()
        body=old.split('\n',1)[1]
        self.native.write_text('#!'+sys.executable+'\nimport sys,os,json\nfrom pathlib import Path\nif "debug" not in sys.argv:\n Path(os.environ["CLI_RECORD"]).write_text(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd(),"stdin":sys.stdin.read()})); sys.exit(23)\n'+'sys.stdin.read()\n'+body)
        self.env['CLI_RECORD']=str(self.root/'native-record.json')
    def direct(self,*args,cwd=None,input=None):
        return subprocess.run([sys.executable,str(TOOLS/'cli_context.py'),'--registry',str(self.registry),'--client','codex','--',*args],cwd=cwd or self.wt,env=self.env,text=True,capture_output=True,input=input)
    def test_direct_fresh_worktree_before_exec_and_original_arguments(self):
        args=['exec','--model','a model','literal --cd /other $ ` quote "']
        r=self.direct(*args);self.assertEqual(r.returncode,23,r.stderr)
        self.assertEqual(json.loads((self.root/'native-record.json').read_text()),{'args':args,'cwd':str(self.wt),'stdin':''})
        self.assertEqual(json.loads((self.wt/'.ai-workbench/project-context/cli-startup.json').read_text())['status'],'PASS')
    def test_interactive_and_piped_stdin_survive_preflight(self):
        for args in [[],['exec','-']]:
            r=self.direct(*args,input='private piped prompt with $ and `\n')
            self.assertEqual(r.returncode,23,r.stderr)
            self.assertEqual(json.loads((self.root/'native-record.json').read_text())['stdin'],'private piped prompt with $ and `\n')
    def test_excluded_private_guidance_provision_and_conflict(self):
        self.git(self.repo,'rm','--cached','AGENTS.md')
        self.git(self.repo,'commit','-qm','private guidance')
        self.git(self.repo,'worktree','remove',str(self.wt))
        self.git(self.repo,'worktree','add','-q','--detach',str(self.wt),'HEAD')
        excludes=self.repo/'.git/info/exclude';excludes.write_text(excludes.read_text()+'/AGENTS.md\n')
        self.assertFalse((self.wt/'AGENTS.md').exists())
        r=self.direct('exec','prompt');self.assertEqual(r.returncode,78)
        registry=json.loads(self.registry.read_text());next(iter(registry['projects'].values()))['private_team_guidance']=True
        self.registry.write_text(json.dumps(registry))
        r=self.direct('exec','prompt');self.assertEqual(r.returncode,23,r.stderr)
        self.assertEqual((self.wt/'AGENTS.md').read_bytes(),(self.repo/'AGENTS.md').read_bytes())
        (self.wt/'AGENTS.md').write_text('foreign guidance')
        (self.root/'native-record.json').unlink()
        r=self.direct('exec','prompt');self.assertEqual(r.returncode,78)
        self.assertEqual((self.wt/'AGENTS.md').read_text(),'foreign guidance')
        self.assertFalse((self.root/'native-record.json').exists())
    def test_cd_variants_and_prompt_boundary(self):
        for option in [['-C',str(self.wt)],['--cd='+str(self.wt)],['-C'+str(self.wt)]]:
            with self.subTest(option=option):
                r=self.direct(*option,'exec','--json','prompt',cwd=self.root);self.assertEqual(r.returncode,23,r.stderr)
        selected,_,_,_=cli_context.launch_options(['exec','prompt','--cd','/bad'],self.wt)
        self.assertEqual(selected,str(self.wt))
        selected,_,_,_=cli_context.launch_options(['-c','key=--cd','--cd',str(self.wt),'prompt'],self.root)
        self.assertEqual(selected,str(self.wt))
    def test_help_and_update_do_not_apply(self):
        for args in [['--help'],['update'],['exec','--help']]:
            r=self.direct(*args);self.assertEqual(r.returncode,23,r.stderr)
        self.assertFalse((self.wt/'.codex/config.toml').exists())
    def test_unknown_and_internal_worktree_block_only_registered(self):
        for args in [['--worktree'],['-w=name'],['exec','--unknown']]:
            r=self.direct(*args);self.assertEqual(r.returncode,78,r.stderr)
            self.assertFalse((self.root/'native-record.json').exists())
            r=self.direct(*args,cwd=self.root);self.assertEqual(r.returncode,23,r.stderr)
            (self.root/'native-record.json').unlink()
        self.assertFalse((self.wt/'.codex/config.toml').exists())
    def test_conflict_preserved_no_native_exec_durable_failure(self):
        path=self.wt/'.codex/config.toml';path.parent.mkdir();path.write_text('developer_instructions="FOREIGN"\n')
        r=self.direct('exec','private prompt');self.assertEqual(r.returncode,78)
        self.assertFalse((self.root/'native-record.json').exists());self.assertIn('FOREIGN',path.read_text())
        evidence=next((self.root/'failures').glob('*.json')).read_text();self.assertNotIn('private prompt',evidence)
    def test_same_origin_clone_and_non_git_no_setup(self):
        other=self.root/'clone';subprocess.run(['git','clone','-q',str(self.repo),str(other)],check=True)
        for cwd in [other,self.root]:
            r=self.direct('exec','prompt',cwd=cwd);self.assertEqual(r.returncode,23,r.stderr);self.assertFalse((cwd/'.codex').exists())
    def test_subdirectory_prepares_root_without_chdir(self):
        nested=self.wt/'nested';nested.mkdir()
        # Real native loaders discover root config. Fixture only needs to emulate
        # this lookup; no application model is involved.
        s=self.native.read_text().replace('p=Path.cwd();d=', 'p=Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],text=True).strip());d=')
        self.native.write_text(s.replace('import sys,os,json','import sys,os,json,subprocess'))
        r=self.direct('exec','prompt',cwd=nested);self.assertEqual(r.returncode,23,r.stderr)
        self.assertEqual(json.loads((self.root/'native-record.json').read_text())['cwd'],str(nested))


if __name__=='__main__':unittest.main()
