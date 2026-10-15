#!/usr/bin/env python3
"""Synchronous context gate at native worktree materialization / Desktop setup."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import botmux_context as context
import context_io


def failure(registry, cwd, exc):
    key=hashlib.sha256(str(Path(cwd).resolve()).encode()).hexdigest()
    context_io.atomic_write(Path(registry).parent/'failures'/(key+'.json'),json.dumps({'status':'BLOCKED','error_code':'AIWB_CONTEXT_STARTUP_BLOCKED','cwd':str(Path(cwd).resolve()),'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':str(exc)},indent=2)+'\n')


def arm(registry_path, target, entry, options, client):
    registry=context.read_json(registry_path)
    integration=registry.get('native_worktree')
    if not isinstance(integration,dict):raise RuntimeError('native worktree integration is not installed')
    git=Path(integration['git']);shim=Path(integration['shim'])
    if not git.is_absolute() or not git.is_file() or not shim.is_file():raise RuntimeError('native Git entry unavailable')
    context.pinned(shim,integration['shim_sha256'])
    expected=integration.get('versions',{}).get(client)
    observed=context.run([registry['clients'][client],'--version'],target).strip().splitlines()[0]
    if not expected or observed != expected:
        raise RuntimeError('native worktree client version requires revalidation: '+client)
    root=Path(registry_path).parent/'pending';root.mkdir(exist_ok=True,mode=0o700)
    path=root/(uuid.uuid4().hex+'.json')
    context_io.atomic_write(path,json.dumps({'status':'ARMED','source':str(target),'common_dir':context.git(target,'rev-parse','--path-format=absolute','--git-common-dir'),'client':client,'target':None,'pid':os.getpid()},indent=2)+'\n')
    # Scoped to this native process tree. No global Git hook/PATH replacement.
    os.environ['AIWB_NATIVE_WORKTREE_TOKEN']=str(path)
    os.environ['AIWB_NATIVE_WORKTREE_OPTIONS']=json.dumps(options)
    os.environ['PATH']=str(shim.parent)+os.pathsep+os.environ['PATH']


def prepare(registry_path, target, options=None, desktop=False):
    target=Path(target).resolve(strict=True)
    receipt=context.prepare(registry_path,target,receipt_name='native-worktree-startup.json',native_cwd=target,client_options=options)
    if receipt['status']!='PASS':raise RuntimeError('native worktree repository is not registered')
    if desktop:
        registry=context.read_json(registry_path);entry=registry['projects'][receipt['common_dir']]
        binary=registry.get('desktop_client')
        if not binary or not Path(binary).is_absolute():raise RuntimeError('Desktop native client is not registered')
        messages=json.loads(context.run([binary,'debug','prompt-input','Read-only Desktop startup context verification.'],target))
        developer=json.dumps([m for m in messages if m.get('role')=='developer'],ensure_ascii=False)
        user=json.dumps([m for m in messages if m.get('role')=='user'],ensure_ascii=False)
        decl=context.read_json(entry['declaration']);team=(target/'AGENTS.md').read_text().strip()
        checks={'project_instructions':json.dumps(decl['instructions'],ensure_ascii=False)[1:-1] in developer,'rule_pin':entry['pin'] in developer,'team_guidance':json.dumps(team,ensure_ascii=False)[1:-1] in user}
        if not all(checks.values()):raise RuntimeError('Desktop native context loading failed: '+', '.join(k for k,v in checks.items() if not v))
        receipt['checks']['desktop']=checks
    context_io.atomic_write(target/'.ai-workbench/project-context/native-worktree-startup.json',json.dumps(receipt,indent=2)+'\n')
    return receipt


def git_proxy(registry_path,args):
    registry=context.read_json(registry_path);real=registry['native_worktree']['git']
    token=os.environ.get('AIWB_NATIVE_WORKTREE_TOKEN')
    if not token or os.environ.get('AIWB_NATIVE_WORKTREE_PREPARING')=='1':os.execv(real,[real,*args])
    path=Path(token)
    if path.parent.resolve()!= (Path(registry_path).parent/'pending').resolve():raise RuntimeError('invalid native startup token')
    state=context.read_json(path)
    if state['status'] not in ['ARMED','MATERIALIZING']:os.execv(real,[real,*args])
    # Native 0.162/0.210 create via add --no-checkout then --work-tree=. reset.
    creation=next((i for i in range(len(args)-1) if args[i:i+2]==['worktree','add']),None)
    materialize='reset' in args and '--hard' in args
    if creation is not None:
        tail=args[creation+2:]
        # Both verified clients pass the absolute checkout then a commit/ref.
        paths=[Path(x) for x in tail if x.startswith('/')]
        if len(paths)!=1 or '--no-checkout' not in tail:raise RuntimeError('unsupported native worktree creation contract')
        target=paths[0].resolve()
        if target.exists():raise RuntimeError('native checkout target already exists')
        state['target']=str(target);state['status']='MATERIALIZING'
        context_io.atomic_write(path,json.dumps(state,indent=2)+'\n')
    effective=Path.cwd()
    for i,value in enumerate(args[:-1]):
        if value == '-C':effective=(effective/args[i+1]).resolve()
    result=subprocess.run([real,*args])
    if result.returncode:return result.returncode
    if materialize and state.get('target') and effective.resolve()==Path(state['target']).resolve():
        target=Path(state['target'])
        try:
            if context.git(target,'rev-parse','--path-format=absolute','--git-common-dir')!=state['common_dir']:raise RuntimeError('native checkout identity drift')
            os.environ['AIWB_NATIVE_WORKTREE_PREPARING']='1'
            options=json.loads(os.environ.get('AIWB_NATIVE_WORKTREE_OPTIONS','{}'))
            receipt=prepare(registry_path,target,options)
            state.update(status='PASS',verified_at=receipt['verified_at'])
            context_io.atomic_write(path,json.dumps(state,indent=2)+'\n')
        except (RuntimeError,OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
            state.update(status='BLOCKED');context_io.atomic_write(path,json.dumps(state,indent=2)+'\n');failure(registry_path,target,exc);raise
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--registry',required=True);p.add_argument('--desktop',action='store_true');p.add_argument('--git',action='store_true');p.add_argument('--cwd');p.add_argument('args',nargs=argparse.REMAINDER);a=p.parse_args(argv)
    if a.git:return git_proxy(a.registry,a.args[1:] if a.args[:1]==['--'] else a.args)
    if not a.desktop:raise RuntimeError('startup mode required')
    target=Path(a.cwd or os.environ.get('CODEX_WORKTREE_PATH') or Path.cwd()).resolve()
    try:
        source=os.environ.get('CODEX_SOURCE_TREE_PATH')
        if not source or context.git(source,'rev-parse','--path-format=absolute','--git-common-dir')!=context.git(target,'rev-parse','--path-format=absolute','--git-common-dir'):raise RuntimeError('Desktop source/destination identity is unavailable')
        prepare(a.registry,target,desktop=True)
    except (RuntimeError,OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:failure(a.registry,target,exc);raise
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
        sys.stderr.write('AIWB_CONTEXT_STARTUP_BLOCKED: '+str(exc)+'\n');sys.exit(78)
