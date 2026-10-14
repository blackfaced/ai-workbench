#!/usr/bin/env python3
"""Pinned, verified local installs. No project, trust or hook changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import context_io

FILES=('project_context.py','env.py','context_io.py','context_declaration.py','context_restore.py','install_project_context.py')
HERE=Path(__file__).resolve().parent


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(root):
    context_io.guard(root)
    context_io.guard(root/'release.json')
    m=json.loads((root/'release.json').read_text())
    if set(m['files']) != set(FILES): raise RuntimeError('release file set mismatch')
    for name,sha in m['files'].items():
        context_io.guard(root/name)
        if digest(root/name)!=sha: raise RuntimeError('installed payload drift: '+name)
    return m


def launch_text(root, python, release_digest):
    # Stable launcher owns no movable source path; pin all payload hashes.
    return ('#!'+python+'\n'+
        'import hashlib,json,os,runpy,sys\nfrom pathlib import Path\n'+
        'root=Path('+repr(str(root))+')\n'+
        'try:\n manifest=root/"release.json"\n'+
        ' if manifest.is_symlink() or hashlib.sha256(manifest.read_bytes()).hexdigest()!='+repr(release_digest)+': raise RuntimeError("release manifest drift")\n'+
        ' m=json.loads(manifest.read_text())\n'+
        ' for name,sha in m["files"].items():\n'+
        '  p=root/name\n'+
        '  if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha: raise RuntimeError("installed payload drift: "+name)\n'+
        ' sys.path.insert(0,str(root))\n'+
        ' sys.argv[0]=str(root/"project_context.py")\n'+
        ' runpy.run_path(sys.argv[0],run_name="__main__")\n'+
        'except (OSError,ValueError,RuntimeError) as e:\n sys.stderr.write(str(e)+"\\n");sys.exit(1)\n')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['install','check','rollback'])
    p.add_argument('--root',default=str(Path.home()/'.local/share/setup-aiwb-tools/releases'))
    p.add_argument('--entry',default=str(Path.home()/'.local/bin/setup-aiwb-context'))
    p.add_argument('--version',required=True)
    p.add_argument('--python',default=sys.executable)
    a=p.parse_args(argv)
    import re
    if not re.fullmatch(r'[A-Za-z0-9._+-]+',a.version) or a.version in ['.','..']: raise RuntimeError('invalid version')
    base=Path(a.root).absolute();root=base/a.version;entry=Path(a.entry).absolute()
    state=base/'installation.json'
    context_io.guard(base);context_io.guard(entry);context_io.guard(root);context_io.guard(state)
    with context_io.locks([str(base),str(entry)]):
        ledger=json.loads(state.read_text()) if state.exists() else {'entry':str(entry),'versions':{},'active':None}
        if ledger['entry']!=str(entry): raise RuntimeError('entry identity differs from installation ledger')
        if entry.exists() and (not ledger.get('entry_sha256') or digest(entry)!=ledger['entry_sha256']):
            raise RuntimeError('entry not owned or edited; refusing takeover')
        if a.action=='install':
            payload={n:digest(HERE/n) for n in FILES}
            if root.exists():
                m=verify(root)
                if m['files']!=payload: raise RuntimeError('immutable version collision; choose new version')
                if a.version in ledger['versions'] and m != ledger['versions'][a.version]:
                    raise RuntimeError('immutable release metadata drift')
            else:
                base.mkdir(parents=True,exist_ok=True)
                stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=base))
                try:
                    for n in FILES: shutil.copy2(HERE/n,stage/n)
                    m={'version':a.version,'files':payload,'python':os.path.realpath(a.python),'source_commit':None,'source_dirty':None}
                    q=subprocess.run(['git','-C',str(HERE),'rev-parse','HEAD'],capture_output=True,text=True)
                    if q.returncode==0:
                        m['source_commit']=q.stdout.strip()
                        status=subprocess.run(['git','-C',str(HERE),'status','--porcelain'],capture_output=True,text=True,check=True)
                        m['source_dirty']=bool(status.stdout.strip())
                    (stage/'release.json').write_text(json.dumps(m,indent=2)+'\n')
                    subprocess.run([a.python,str(stage/'project_context.py'),'--help'],stdout=subprocess.DEVNULL,check=True)
                    q=subprocess.run([a.python,'-c','import tomllib'],capture_output=True)
                    if q.returncode!=0:
                        subprocess.run([a.python,'-c','import tomli'],check=True)
                    verify(stage)
                    stage.rename(root)
                finally:
                    if stage.exists(): shutil.rmtree(stage)
            ledger['versions'][a.version]=m
        else:
            m=verify(root)
            if a.version not in ledger['versions']: raise RuntimeError('release not registered in installation ledger')
            if m != ledger['versions'][a.version]: raise RuntimeError('release manifest differs from registered identity')
        if a.action=='check':
            if ledger['active']!=a.version: raise RuntimeError('version installed but not active')
            print(json.dumps({'version':a.version,'root':str(root),'entry':str(entry),'verified':True}));return 0
        before_entry=entry.read_bytes() if entry.exists() else None
        before_state=state.read_bytes() if state.exists() else None
        ledger['previous']=ledger['active'];ledger['active']=a.version
        launcher=launch_text(root,m['python'],digest(root/'release.json'))
        ledger['entry_sha256']=hashlib.sha256(launcher.encode()).hexdigest()
        try:
            context_io.atomic_write(entry,launcher)
            entry.chmod(0o755)
            context_io.atomic_write(state,json.dumps(ledger,indent=2)+'\n')
            subprocess.run([str(entry),'--help'],stdout=subprocess.DEVNULL,check=True)
        except Exception:
            if before_entry is not None: context_io.atomic_write(entry,before_entry)
            elif entry.exists(): entry.unlink()
            if before_state is not None: context_io.atomic_write(state,before_state)
            elif state.exists(): state.unlink()
            raise
        print(json.dumps({'version':a.version,'root':str(root),'entry':str(entry),'action':a.action}))
        return 0


if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,OSError,ValueError,subprocess.CalledProcessError) as e:
        sys.stderr.write('installation refused: %s\n'%e);sys.exit(1)
