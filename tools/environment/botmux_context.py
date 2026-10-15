#!/usr/bin/env python3
"""Prepare explicitly registered Git checkouts before Botmux's local shell exec.

Botmux 3.40.0 bash launch argv: -i -c SCRIPT _ CWD ENV... CLI ARGS...
No prompt text, env values, or CLI arguments are persisted in receipts.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import context_io


def digest(path):
    return context_io.fingerprint(path)


def git(root, *args):
    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                       text=True, timeout=20)
    if r.returncode:
        raise RuntimeError('Git identity check failed')
    return r.stdout.strip()


def read_json(path):
    context_io.guard(path)
    return json.loads(Path(path).read_text())


def pinned(path, sha):
    if not sha or digest(path) != sha:
        raise RuntimeError('registered source drift: ' + str(path))


def run(command, cwd):
    r = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60)
    if r.returncode:
        # Renderer diagnostics can contain private instruction text. Keep them
        # out of both the TUI and receipt; identify the failed phase instead.
        phase = 'native prompt-input' if any(command[i:i+2] == ['debug','prompt-input'] for i in range(len(command)-1)) else ('check' if '--check' in command else 'apply')
        raise RuntimeError('preflight command failed: %s %s (exit %d)' % (Path(command[0]).name, phase, r.returncode))
    return r.stdout


def prepare(registry_path, cwd, *, receipt_name="botmux-startup.json", native_cwd=None, client_options=None):
    registry_hash = digest(registry_path)
    registry = read_json(registry_path)
    if registry.get('version') != 1:
        raise RuntimeError('unsupported startup registry')
    target = Path(cwd).resolve(strict=True)
    # Unregistered directories remain usable by the same bot. Only an exact
    # Git common-dir registration grants project/trust configuration writes.
    try:
        common = str(Path(git(target, 'rev-parse', '--path-format=absolute',
                              '--git-common-dir')).resolve(strict=True))
    except RuntimeError:
        if (target / '.git').exists():
            raise RuntimeError('checkout Git identity is unavailable')
        return {'status': 'unregistered', 'cwd': str(target)}
    entry = registry['projects'].get(common)
    if entry is None:
        return {'status': 'unregistered', 'cwd': str(target)}
    if git(target, 'rev-parse', '--show-toplevel') != str(target):
        raise RuntimeError('registered startup requires the checkout root')
    source = Path(entry['repo'])
    if source.resolve() != source:
        raise RuntimeError('source repository must use its canonical path')
    if str(Path(git(source, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()) != common:
        raise RuntimeError('source repository identity drift')
    declaration = Path(entry['declaration'])
    installer = Path(registry['installer']['path'])
    # Outer lock covers validation + apply + native loading across starts of
    # the same repo. Renderer locks independently protect shared trust files.
    with context_io.locks([str(source / '.ai-workbench/botmux-startup')]):
        pinned(registry_path, registry_hash)
        pinned(installer, registry['installer']['sha256'])
        pinned(declaration, entry['declaration_sha256'])
        for path, sha in entry['companions'].items():
            pinned(Path(path), sha)
        for rel, sha in entry['source_files'].items():
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise RuntimeError('invalid analysis source path')
            for root in {source, target}:
                p = root / rel
                if sha is None:
                    context_io.guard(p)
                    if p.exists():
                        raise RuntimeError('analysis requires refresh: ' + rel)
                elif digest(p) != sha:
                    raise RuntimeError('analysis requires refresh: ' + rel)
        team_hash = digest(target / 'AGENTS.md')
        team = (target / 'AGENTS.md').read_text().strip()
        if not team or team_hash != entry['team_sha256']:
            raise RuntimeError('team guidance requires refresh')
        for client, executable in registry['clients'].items():
            if client not in ['codex', 'trae'] or not Path(executable).is_absolute():
                raise RuntimeError('unsupported client registration')
        if set(registry['clients']) != {'codex', 'trae'}:
            raise RuntimeError('both native clients must be verified')
        # Existing common-dir exclusions are shared by all worktrees. Never
        # add a broad ignore or trust a parent directory at startup.
        for rel in ['.codex/config.toml', '.trae/traecli.toml']:
            if subprocess.run(['git','-C',str(target),'check-ignore','-q',rel]).returncode:
                raise RuntimeError('private native path is not locally excluded')
        copies = []
        for rel, artifact in entry.get('native_companions', {}).items():
            if artifact.get('worktrees_only') is True and target == source:
                continue
            parts = Path(rel).parts
            if len(parts) < 2 or parts[0] not in ['.trae','.codex'] or '..' in parts or rel in ['.codex/config.toml','.trae/traecli.toml']:
                raise RuntimeError('invalid native companion target')
            src, dest = Path(artifact['source']), target / rel
            pinned(src, artifact['sha256'])
            if subprocess.run(['git','-C',str(target),'ls-files','--error-unmatch','--',rel], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                raise RuntimeError('native companion is Git-tracked: ' + rel)
            if subprocess.run(['git','-C',str(target),'check-ignore','-q',rel]).returncode:
                raise RuntimeError('native companion is not locally excluded: ' + rel)
            current = digest(dest)
            if current is not None and current != artifact['sha256']:
                raise RuntimeError('native companion conflict; preserve existing file: ' + rel)
            copies.append((src, dest, current))
        command = [str(installer), '--repo', str(source), '--declaration',
                   str(declaration), '--profile', 'project', '--pin', entry['pin'],
                   '--workenv', entry['workenv']]
        if target != source:
            command += ['--worktree', str(target)]
        # Registry installation is explicit owner authorization for the exact
        # checkout selected by Botmux within this registered Git repository.
        command += ['--manage-trust']
        run(command + ['--apply'], source)
        run(command + ['--check'], source)
        for src, dest, current in copies:
            if current is None:
                context_io.atomic_write(dest, src.read_bytes(), expected=None)
        decl = read_json(declaration)
        checks = {}
        for client, executable in registry['clients'].items():
            raw = run([executable, *(client_options or {}).get(client, []), 'debug', 'prompt-input',
                       'Read-only startup context verification.'], native_cwd or target)
            messages = json.loads(raw)
            developer = json.dumps([x for x in messages if x.get('role') == 'developer'], ensure_ascii=False)
            user = json.dumps([x for x in messages if x.get('role') == 'user'], ensure_ascii=False)
            # JSON encoding changes whitespace and quoting; compare encoded
            # instruction strings rather than a marker supplied by the probe.
            checks[client] = {
                'project_instructions': json.dumps(decl['instructions'], ensure_ascii=False)[1:-1] in developer,
                'rule_pin': entry['pin'] in developer,
                'team_guidance': json.dumps(team, ensure_ascii=False)[1:-1] in user,
            }
            if not all(checks[client].values()):
                raise RuntimeError('native context loading failed: ' + client)
        receipt = {'status':'PASS', 'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'cwd':str(target), 'source':str(source), 'common_dir':common,
                   'target_head':git(target,'rev-parse','HEAD'), 'pin':entry['pin'],
                   'registry_sha256':digest(registry_path), 'declaration_sha256':digest(declaration),
                   'checks':checks, 'native_companions': {str(dest.relative_to(target)): {'sha256':digest(dest), 'source':str(src), 'created':current is None} for src,dest,current in copies}}
        if receipt_name not in ['botmux-startup.json', 'cli-startup.json']:
            raise RuntimeError('unsupported receipt name')
        receipt['native_cwd'] = str(native_cwd or target)
        output = target / '.ai-workbench/project-context' / receipt_name
        context_io.atomic_write(output, json.dumps(receipt, indent=2)+'\n')
        return receipt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', required=True)
    p.add_argument('--check-cwd')
    p.add_argument('--shell')
    p.add_argument('shell_args', nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    if a.check_cwd:
        print(json.dumps(prepare(a.registry, a.check_cwd)))
        return 0
    args = a.shell_args
    if args[:1] == ['--']: args = args[1:]
    # Fail closed on a changed Botmux launch contract. Never run arbitrary
    # incoming shell commands merely to discover a cwd or environment.
    if not a.shell or Path(a.shell).name != 'bash' or args[:2] != ['-i','-c'] or len(args)<6 or args[3]!='_':
        raise RuntimeError('unsupported Botmux bash launch arguments')
    try:
        prepare(a.registry, args[4])
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Tmux can discard a failed pane before its stderr is read. Retain a
        # bounded, owner-local refusal record, never CLI args or prompt/env data.
        try:
            root = Path(a.registry).parent
            context_io.guard(root)
            key = hashlib.sha256(str(Path(args[4]).resolve()).encode()).hexdigest()
            context_io.atomic_write(root/'failures'/(key+'.json'), json.dumps({'status':'BLOCKED', 'error_code':'AIWB_CONTEXT_STARTUP_BLOCKED', 'cwd':str(Path(args[4]).resolve()), 'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'reason':str(exc)}, indent=2)+'\n')
        except (RuntimeError, OSError):
            pass
        raise
    os.execv(a.shell, [a.shell] + args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write('AIWB_CONTEXT_STARTUP_BLOCKED: '+str(exc)+'\n')
        sys.exit(78)
