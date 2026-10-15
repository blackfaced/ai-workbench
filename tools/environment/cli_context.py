#!/usr/bin/env python3
"""Prepare registered existing checkouts before a direct native CLI launch."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import botmux_context as context
import context_io

# Explicit installed-CLI argument contracts. Options following a prompt or --
# are prompt data. Never persist argv or evaluate shell text.
VALUES = set('config enable disable remote remote-auth-token-env image model local-provider profile sandbox add-dir ask-for-approval permission-mode disabled-tool session-id shell-tool-timeout allowed-tool disallowed-tool worktree-base worktree-mode thread-source cyber-access-program output-schema color output-last-message base commit title'.split())
SHORT = {'c':'config','i':'image','m':'model','p':'profile','s':'sandbox','a':'ask-for-approval','o':'output-last-message','C':'cd'}
FLAGS = set('strict-config oss approve-for-me dangerously-bypass-approvals-and-sandbox dangerously-bypass-hook-trust search no-alt-screen no-daemon skip-git-repo-check ephemeral ignore-user-config ignore-rules json uncommitted'.split())
BYPASS = set('agents dashboard login logout update doctor mcp plugin channel backend completion app app-server remote-control acp sandbox apply a queue archive delete migrate-rollouts unarchive migrate worktree-apply exec-server features models help resume fork'.split())


def launch_options(args, cwd, client="codex", native_requests=None):
    directory = str(cwd)
    diagnostic = []
    unsafe = []
    stage = 'root'
    i = 0
    while i < len(args):
        token = args[i]
        if token == '--': break
        if token in ['-h','--help','-V','-v','--version']:
            return directory, diagnostic, [], True
        if not token.startswith('-') or token == '-':
            if stage in ['root','exec'] and token in BYPASS:
                return directory, diagnostic, [], True
            if stage == 'root' and token in ['exec','e','review','debug']:
                stage = 'exec' if token in ['exec','e'] else token
                i += 1
                continue
            if stage == 'debug' and token == 'prompt-input':
                stage = 'prompt-input'; i += 1; continue
            if stage == 'debug': return directory, diagnostic, [], True
            break  # first prompt/positional: remaining text is never options
        name, sep, attached = token.partition('=')
        if name.startswith('--'):
            option = name[2:]
        elif len(name) >= 2 and name[1] in SHORT:
            option = SHORT[name[1]]
            if len(name) > 2:
                attached = name[2:] + (sep + attached if sep else '')
                sep = '='
        elif name == '-y': option = 'dangerously-bypass-approvals-and-sandbox'
        elif name.startswith('-w'):
            option = 'worktree'
        else:
            unsafe.append('unsupported CLI option'); i += 1; continue
        if option in ['remote','resume','acp']:
            unsafe.append('client-created worktree/remote/resume startup requires a separate native integration; use git worktree add then launch from that checkout')
        if option == 'worktree':
            if native_requests is not None: native_requests.append(True)
            if client == 'codex' and name != '--worktree':
                unsafe.append('Codex native worktree option is --worktree')
            i += 1
            if client == 'trae' and not sep and i < len(args) and not args[i].startswith('-') and args[i] not in BYPASS | {'exec','e','review','debug'}:
                i += 1
            continue
        if option in ['ignore-user-config','ignore-rules']:
            unsafe.append('context-disabling startup option requires manual verification')
        if option == 'cd' or option in VALUES:
            if sep:
                value = attached
            else:
                i += 1
                if i == len(args): raise RuntimeError('missing CLI option value')
                value = args[i]
            if option == 'worktree-mode' and value != 'git':
                unsafe.append('native context gate currently requires --worktree-mode git')
            if option == 'cd':
                directory = str(Path(cwd) / value)
            elif option in ['config','profile','enable','disable']:
                diagnostic.extend(['--'+option, value])
            if option == 'image' and not sep:
                while i+1 < len(args) and not args[i+1].startswith('-'): i += 1
        elif option not in FLAGS and option not in ['acp','resume']:
            unsafe.append('unsupported CLI option')
        i += 1
    return directory, diagnostic, unsafe, False


def registered_target(registry, cwd):
    """Subdirectories use their checkout root; identity is never name/origin."""
    p = subprocess.run(['git','-C',str(cwd),'rev-parse','--show-toplevel','--path-format=absolute','--git-common-dir'], capture_output=True, text=True, timeout=20)
    if p.returncode:
        return None
    root, common = p.stdout.strip().splitlines()
    entry = registry['projects'].get(str(Path(common).resolve()))
    return (Path(root).resolve(), entry) if entry is not None else None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', required=True)
    p.add_argument('--client', choices=['codex','trae'], required=True)
    p.add_argument('args', nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    args = a.args[1:] if a.args[:1] == ['--'] else a.args
    registry = context.read_json(a.registry)
    native = registry['clients'][a.client]
    if not Path(native).is_absolute() or Path(native).resolve() == Path(sys.argv[0]).resolve():
        raise RuntimeError('invalid native client entry')
    cwd = Path.cwd()
    native_requests = []
    directory, diagnostic, unsafe, bypass = launch_options(args, cwd, a.client, native_requests)
    selected = Path(directory).resolve()
    registration = None if bypass else registered_target(registry, selected)
    defaults = {}
    try:
        if registration is not None:
            target, entry = registration
            configured = entry.get('client_defaults', {})
            if not isinstance(configured, dict):
                raise RuntimeError('invalid project client defaults')
            for client, settings in configured.items():
                if client not in ['codex','trae'] or not isinstance(settings, dict) or set(settings) != {'project_doc_max_bytes'}:
                    raise RuntimeError('unsupported project client defaults')
                budget = settings['project_doc_max_bytes']
                if type(budget) is not int or not 32768 <= budget <= 1048576:
                    raise RuntimeError('invalid project document budget')
                defaults[client] = ['-c','project_doc_max_bytes='+str(budget)]
            if unsafe: raise RuntimeError(unsafe[0])
            if native_requests and not registry.get('native_worktree'):
                raise RuntimeError('native worktree integration is not installed')
            for variable, suffix in [('CODEX_HOME','.codex'),('TRAE_HOME','.trae')]:
                if os.environ.get(variable) and Path(os.environ[variable]).resolve() != (Path.home()/suffix).resolve():
                    raise RuntimeError('custom native home requires separate setup: '+variable)
            # Real native paths in registry prevent the shared no-model checks
            # from reentering these wrappers. Native retains original argv/cwd.
            context.prepare(a.registry, target, receipt_name='cli-startup.json',
                            native_cwd=selected, client_options={client: defaults.get(client, []) + (diagnostic if client == a.client else []) for client in registry['clients']})
            if native_requests:
                import native_worktree
                native_worktree.arm(a.registry,target,entry,{client:defaults.get(client,[])+(diagnostic if client==a.client else []) for client in registry['clients']},a.client)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        record = {'status':'BLOCKED', 'error_code':'AIWB_CONTEXT_STARTUP_BLOCKED',
                  'cwd':str(selected), 'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'reason':str(exc)}
        key = hashlib.sha256(str(selected).encode()).hexdigest()
        context_io.atomic_write(Path(a.registry).parent/'failures'/(key+'.json'), json.dumps(record,indent=2)+'\n')
        raise
    native_mode = ['--worktree-mode','git'] if registration is not None and native_requests and a.client == 'trae' else []
    os.execv(native, [native, *defaults.get(a.client, []), *native_mode, *args])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write('AIWB_CONTEXT_STARTUP_BLOCKED: '+str(exc)+'\n')
        sys.exit(78)
