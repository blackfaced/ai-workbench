#!/usr/bin/env python3
"""Native-style Git creation: pre-config gate, no model and isolated HOME."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_botmux_context as fixtures
TOOLS=fixtures.TOOLS


class Native(fixtures.Startup):
    def setUp(self):
        super().setUp()
        self.target=self.root/'native-checkout'
        shim=self.root/'shim/git';shim.parent.mkdir()
        shim.write_text('#!'+sys.executable+'\nimport sys,runpy\nsys.path.insert(0,'+repr(str(TOOLS))+')\nsys.argv=["native_worktree.py","--registry",'+repr(str(self.registry))+',"--git","--",*sys.argv[1:]]\nrunpy.run_path('+repr(str(TOOLS/'native_worktree.py'))+',run_name="__main__")\n');shim.chmod(0o755)
        registry=json.loads(self.registry.read_text());registry['native_worktree']={'git':'/usr/bin/git','shim':str(shim),'shim_sha256':hashlib.sha256(shim.read_bytes()).hexdigest(),'versions':{'codex':'fixture-native','trae':'fixture-native'}};registry['desktop_client']=str(self.native);self.registry.write_text(json.dumps(registry))
        native=self.native.read_text();self.native.write_text(native.split('\n',1)[0]+'\n'+'''import os,sys,subprocess,json
from pathlib import Path
if '--version' in sys.argv:print('fixture-native');sys.exit(0)
if '--worktree' in sys.argv:
 target=Path('''+repr(str(self.target))+''')
 if os.environ.get('ALLOCATE_EMPTY'):target.mkdir()
 subprocess.run(['git','worktree','add','--detach','--no-checkout',str(target),'HEAD'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['git','-C',str(target),'--work-tree=.','reset','--hard','--no-recurse-submodules','HEAD'],check=True,stdout=subprocess.DEVNULL)
 receipt=json.loads((target/'.ai-workbench/project-context/native-worktree-startup.json').read_text())
 print(json.dumps({'status':receipt['status'],'target':str(target),'first_start_private_loaded':'PROJECT_PRIVATE' in (target/'.codex/config.toml').read_text()}));sys.exit(0)
'''+native.split('\n',1)[1])
    def direct(self,*args):
        return subprocess.run([sys.executable,str(TOOLS/'cli_context.py'),'--registry',str(self.registry),'--client','codex','--',*args],cwd=self.repo,env=self.env,capture_output=True,text=True)
    def test_first_native_materialization_prepares_before_client_config(self):
        r=self.direct('--worktree','exec','prompt');self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(json.loads(r.stdout.strip().splitlines()[-1])['first_start_private_loaded'])
        token=json.loads(next((self.root/'pending').glob('*.json')).read_text());self.assertEqual(token['status'],'PASS');self.assertEqual(token['target'],str(self.target))
    def test_native_preallocated_empty_directory_is_supported(self):
        self.env['ALLOCATE_EMPTY']='1'
        r=self.direct('--worktree','exec','prompt');self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(json.loads(r.stdout.strip().splitlines()[-1])['first_start_private_loaded'])
    def test_desktop_setup_reuses_native_loading_and_identity(self):
        env=dict(self.env,CODEX_SOURCE_TREE_PATH=str(self.repo),CODEX_WORKTREE_PATH=str(self.wt))
        r=subprocess.run([sys.executable,str(TOOLS/'native_worktree.py'),'--registry',str(self.registry),'--desktop'],cwd=self.wt,env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);receipt=json.loads((self.wt/'.ai-workbench/project-context/native-worktree-startup.json').read_text());self.assertTrue(all(receipt['checks']['desktop'].values()))
        env['CODEX_SOURCE_TREE_PATH']=str(self.root);r=subprocess.run([sys.executable,str(TOOLS/'native_worktree.py'),'--registry',str(self.registry),'--desktop'],cwd=self.wt,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,78)

    def register_private_skill(self):
        name = 'example-check'
        package = self.root / 'packages' / name
        package.mkdir(parents=True)
        (package / 'SKILL.md').write_text('---\nname: example-check\ndescription: Check a fixture.\n---\n')
        (package / 'guide.md').write_text('Companion material')
        registry = json.loads(self.registry.read_text())
        entry = next(iter(registry['projects'].values()))
        entry['private_skills'] = {name: {'source': str(package), 'files': {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in package.iterdir()
        }}}
        with (self.repo / '.git/info/exclude').open('a') as excludes:
            excludes.write('/.agents/skills/\n/.claude/skills/\n')
        # Use the real discovery helper and JSON-RPC transport. This fixture
        # client advertises the package only if its worktree entry is readable.
        client = self.root / 'fixture-codex'
        client.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['app-server']:
    for line in sys.stdin:
        request = json.loads(line)
        if request['method'] == 'skills/list':
            root, = request['params']['cwds']
            path = Path(root) / '.agents/skills/example-check/SKILL.md'
            skills = [{'name': 'example-check', 'path': str(path),
                       'enabled': Path(sys.argv[0]).name != 'disabled-client'}] if path.is_file() else []
            print(json.dumps({'id': request['id'], 'result': {'data': [{'cwd': root, 'skills': skills}]}}), flush=True)
            break
else:
    native = ''' + repr(str(self.native)) + '''
    os.execv(native, [native, *sys.argv[1:]])
''')
        client.chmod(0o700)
        registry['clients']['codex'] = registry['desktop_client'] = str(client)
        self.registry.write_text(json.dumps(registry))
        return package

    def run_desktop(self):
        env = dict(self.env, CODEX_SOURCE_TREE_PATH=str(self.repo), CODEX_WORKTREE_PATH=str(self.wt))
        return subprocess.run([sys.executable, str(TOOLS / 'native_worktree.py'), '--desktop',
                               '--registry', str(self.registry)], cwd=self.wt, env=env, text=True, capture_output=True)

    def test_desktop_private_skill_repeated_setup_and_package_drift(self):
        package = self.register_private_skill()
        for _ in range(2):
            result = self.run_desktop()
            self.assertEqual(result.returncode, 0, result.stderr)
            for client in ('.agents', '.claude'):
                link = self.wt / client / 'skills' / package.name
                self.assertTrue(link.is_symlink())
                self.assertEqual((link / 'guide.md').resolve(), package / 'guide.md')
        self.assertEqual(subprocess.check_output(['git', '-C', self.wt, 'status', '--porcelain']), b'')
        (package / 'guide.md').write_text('Changed after registration')
        self.assertEqual(self.run_desktop().returncode, 78)

    def test_private_skill_foreign_entry_preserved_before_setup(self):
        package = self.register_private_skill()
        occupied = self.wt / '.claude/skills' / package.name
        occupied.mkdir(parents=True)
        (occupied / 'SKILL.md').write_text('Branch guidance')
        self.git(self.wt, 'add', '-f', '.claude')
        self.assertEqual(self.run_desktop().returncode, 78)
        self.assertEqual((occupied / 'SKILL.md').read_text(), 'Branch guidance')
        self.assertFalse((self.wt / '.agents').exists())

    def test_desktop_disabled_skill_cannot_publish_pass(self):
        self.register_private_skill()
        registry = json.loads(self.registry.read_text())
        disabled = self.root / 'disabled-client'
        disabled.symlink_to(registry['desktop_client'])
        registry['desktop_client'] = str(disabled)
        self.registry.write_text(json.dumps(registry))
        result = self.run_desktop()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn('absent or ambiguous', result.stderr)
        self.assertFalse((self.wt / '.ai-workbench/project-context/native-worktree-startup.json').exists())
    def test_native_project_settings_owned_idempotent_and_foreign_conflict(self):
        d=json.loads(self.decl.read_text());d['clientSettings']={'codex':{'project_doc_max_bytes':65536},'trae':{'project_doc_max_bytes':65536}};self.decl.write_text(json.dumps(d));reg=json.loads(self.registry.read_text());next(iter(reg['projects'].values()))['declaration_sha256']=hashlib.sha256(self.decl.read_bytes()).hexdigest();self.registry.write_text(json.dumps(reg))
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr)
        p=self.wt/'.codex/config.toml';before=p.read_bytes();self.assertIn('project_doc_max_bytes = 65536',p.read_text())
        r=self.run_gate('--check-cwd',str(self.wt));self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(before,p.read_bytes())
        foreign=self.root/'foreign';self.git(self.repo,'worktree','add','-q','--detach',str(foreign));f=foreign/'.codex/config.toml';f.parent.mkdir();f.write_text('project_doc_max_bytes=1024\n')
        r=self.run_gate('--check-cwd',str(foreign));self.assertEqual(r.returncode,78);self.assertEqual(f.read_text(),'project_doc_max_bytes=1024\n')


if __name__=='__main__':unittest.main()
