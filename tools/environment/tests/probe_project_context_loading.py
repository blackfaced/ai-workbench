#!/usr/bin/env python3
"""No-model native loader probe; sanitized results only, isolated HOME and cwd."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    p=argparse.ArgumentParser();p.add_argument('--entry',required=True)
    p.add_argument('--codex',required=True);p.add_argument('--trae',required=True)
    a=p.parse_args();results=[]
    with tempfile.TemporaryDirectory(prefix='aiwb-client-loading-') as tmp:
        root=Path(tmp).resolve();home=root/'home';home.mkdir()
        (home/'.codex').mkdir();(home/'.trae').mkdir()
        repo=root/'repo';repo.mkdir();other=root/'unrelated';other.mkdir()
        subprocess.run(['git','init',str(repo)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        (repo/'AGENTS.md').write_text('TEAM_CONTEXT_PROBE_ONLY\n')
        subprocess.run(['git','-C',str(repo),'add','AGENTS.md'],check=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture'],stdout=subprocess.DEVNULL,check=True)
        wt=root/'wt';subprocess.run(['git','-C',str(repo),'worktree','add','--detach',str(wt)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        declaration=repo/'context.json';declaration.write_text(json.dumps({'instructions':'PRIVATE_CONTEXT_PROBE_ONLY','additiveEntry':{'clients':['codex','trae']}}))
        e=dict(os.environ,HOME=str(home),CODEX_HOME=str(home/'.codex'),TRAE_HOME=str(home/'.trae'),PYTHONDONTWRITEBYTECODE='1')
        q=subprocess.run([a.entry,'--repo',str(repo),'--worktree',str(wt),'--declaration',str(declaration),'--manage-trust','--apply'],env=e,capture_output=True,text=True,timeout=60)
        if q.returncode: raise RuntimeError('isolated provisioning failed: '+q.stderr)
        for name,client,config in [('codex',a.codex,'.codex/config.toml'),('trae',a.trae,'.trae/traecli.toml')]:
            version=subprocess.run([client,'--version'],env=e,capture_output=True,text=True,timeout=20)
            observations=[]
            for label,cwd,want_team,want_private in [('direct',repo,True,True),('worktree',wt,True,True),('unrelated',other,False,False)]:
                r=subprocess.run([client,'debug','prompt-input','-c','model_provider="openai"','fixture only'],cwd=cwd,env=e,capture_output=True,text=True,timeout=90)
                try: data=json.loads(r.stdout);text=json.dumps(data,ensure_ascii=False)
                except ValueError: text=''
                team='TEAM_CONTEXT_PROBE_ONLY' in text;private='PRIVATE_CONTEXT_PROBE_ONLY' in text
                observations.append({'path':label,'exit_code':r.returncode,'team_present':team,'private_present':private,'passed':r.returncode==0 and team==want_team and private==want_private})
            saved=(repo/config).read_bytes();(repo/config).unlink()
            r=subprocess.run([client,'debug','prompt-input','-c','model_provider="openai"','fixture only'],cwd=repo,env=e,capture_output=True,text=True,timeout=90)
            try:text=json.dumps(json.loads(r.stdout))
            except ValueError:text=''
            observations.append({'path':'missing-private-config','exit_code':r.returncode,'team_present':'TEAM_CONTEXT_PROBE_ONLY' in text,'private_present':'PRIVATE_CONTEXT_PROBE_ONLY' in text,'passed':r.returncode==0 and 'TEAM_CONTEXT_PROBE_ONLY' in text and 'PRIVATE_CONTEXT_PROBE_ONLY' not in text})
            (repo/config).write_bytes(saved)
            results.append({'client':name,'version':version.stdout.strip(),'checks':observations})
    print(json.dumps({'scope':'isolated HOME, direct and real Git worktree; no model call; diagnostic-only model_provider override avoids catalog auth','clients':results},ensure_ascii=False,indent=2))
    return 0 if all(x['passed'] for r in results for x in r['checks']) else 1


if __name__=='__main__':sys.exit(main())
