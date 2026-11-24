#!/usr/bin/env python3
"""Install cc-dispatch from a full local Git commit; plan by default, no network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_io

FILES = ('LICENSE', 'tools/cc-dispatch/cc-dispatch',
         'tools/cc-dispatch/cc_dispatch.py', 'tools/cc-dispatch/README.md',
         'tools/cc-dispatch/config.example.json', 'skills/cc-dispatch/SKILL.md')
OWNER = 'ai-workbench:cc-dispatch'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(source, *args):
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL='')
    # Only local object-reading commands. Missing promisor objects must not fetch.
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG_COUNT'):
        env.pop(key, None)
    result = subprocess.run(['git', '-C', str(source), *args], env=env,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError('fixed source object unavailable locally')
    return result.stdout


def payload(source, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise RuntimeError('commit must be a full immutable SHA')
    if not source.is_dir():
        raise RuntimeError('source must be an existing local Git directory')
    if git(source, 'cat-file', '-t', commit).strip() != b'commit':
        raise RuntimeError('source object must be a commit')
    data, records = {}, {}
    for name in FILES:
        row = git(source, 'ls-tree', commit, '--', name).decode().strip()
        if not row:
            raise RuntimeError('required source file missing: ' + name)
        mode, kind, obj = row.split('\t')[0].split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise RuntimeError('source file must be regular: ' + name)
        data[name] = git(source, 'cat-file', 'blob', obj)
        records[name] = {'sha256': sha(data[name]), 'mode': int(mode[-3:], 8)}
    if b'Apache License' not in data['LICENSE'] or b'Version 2.0' not in data['LICENSE']:
        raise RuntimeError('expected Apache-2.0 license missing')
    manifest = {'owner': OWNER, 'source_commit': commit, 'license': 'Apache-2.0',
                'files': records}
    return data, manifest


def manifest_bytes(manifest):
    return (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()


def verify(root, manifest):
    context_io.guard(root)
    expected = set(FILES) | {'release.json'}
    directories = {str(parent) for name in FILES for parent in Path(name).parents if str(parent) != '.'}
    actual = set()
    actual_directories = set()
    for p in root.rglob('*'):
        context_io.guard(p)
        name = p.relative_to(root).as_posix()
        if p.is_file():
            actual.add(name)
        elif p.is_dir():
            actual_directories.add(name)
    if actual != expected or actual_directories != directories:
        raise RuntimeError('release file set drift')
    if (root / 'release.json').read_bytes() != manifest_bytes(manifest):
        raise RuntimeError('release manifest drift')
    for name, record in manifest['files'].items():
        p = root / name
        if sha(p.read_bytes()) != record['sha256'] or stat.S_IMODE(p.stat().st_mode) != record['mode']:
            raise RuntimeError('installed payload drift: ' + name)


def launcher(root, manifest):
    # Isolated shell entry, then verify all shipped content before running it.
    code = ('import hashlib,json,os,runpy,stat,sys\nfrom pathlib import Path\n'
            'root=Path(' + repr(str(root)) + ')\n'
            'expected=' + repr(manifest) + '\n'
            'try:\n'
            ' for p in [root]+list(root.parents)+list(root.rglob("*")):\n'
            '  if p.is_symlink(): raise RuntimeError("release symlink drift")\n'
            '  if not (p.is_file() or p.is_dir()): raise RuntimeError("non-regular release entry")\n'
            ' names={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}\n'
            ' dirs={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}\n'
            ' wanted={str(p) for n in expected["files"] for p in Path(n).parents if str(p)!="."}\n'
            ' if names!=set(expected["files"])|{"release.json"} or dirs!=wanted: raise RuntimeError("release file set drift")\n'
            ' if hashlib.sha256((root/"release.json").read_bytes()).hexdigest()!=' + repr(sha(manifest_bytes(manifest))) + ': raise RuntimeError("release manifest drift")\n'
            ' for name,r in expected["files"].items():\n'
            '  p=root/name\n'
            '  if hashlib.sha256(p.read_bytes()).hexdigest()!=r["sha256"] or stat.S_IMODE(p.stat().st_mode)!=r["mode"]: raise RuntimeError("installed payload drift: "+name)\n'
            ' sys.argv[0]=str(root/"tools/cc-dispatch/cc_dispatch.py")\n'
            ' runpy.run_path(sys.argv[0],run_name="__main__")\n'
            'except (OSError,ValueError,RuntimeError) as e:\n'
            ' sys.stderr.write(str(e)+"\\n");sys.exit(1)\n')
    import shlex
    return ('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -I -c ' +
            shlex.quote(code) + ' "$@"\n').encode()


def link_target(skill):
    context_io.guard(skill.parent)
    if skill.is_symlink():
        return os.readlink(skill)
    if skill.exists():
        raise RuntimeError('skill is not a managed link')
    return None


def assert_activation(entry, state, skill, snapshot):
    for path, key in ((entry, 'entry'), (state, 'state')):
        expected = sha(snapshot[key]) if snapshot[key] is not None else None
        if context_io.fingerprint(path) != expected:
            raise RuntimeError('activation drifted after observation: ' + str(path))
    if snapshot['entry'] is not None and stat.S_IMODE(entry.stat().st_mode) != 0o755:
        raise RuntimeError('entry mode drifted after observation')
    if link_target(skill) != snapshot['link']:
        raise RuntimeError('skill drifted after observation')


def observe(base, root, entry, skill, manifest):
    state = base / 'installation.json'
    for p in (base, root, entry, state, skill.parent):
        context_io.guard(p)
    snapshot = {'entry': entry.read_bytes() if entry.exists() else None,
                'state': state.read_bytes() if state.exists() else None,
                'link': link_target(skill)}
    ledger = json.loads(snapshot['state']) if snapshot['state'] is not None else None
    if ledger and (ledger.get('owner') != OWNER or ledger.get('entry') != str(entry)
                   or ledger.get('skill') != str(skill)):
        raise RuntimeError('installation ownership mismatch')
    if entry.exists():
        if not ledger or sha(entry.read_bytes()) != ledger['entry_sha256'] or stat.S_IMODE(entry.stat().st_mode) != 0o755:
            raise RuntimeError('entry not owned or edited; refusing takeover')
    elif ledger:
        raise RuntimeError('owned entry missing')
    if skill.is_symlink() or skill.exists():
        if not ledger or not skill.is_symlink() or os.readlink(skill) != ledger['skill_target']:
            raise RuntimeError('skill not owned or edited; refusing takeover')
    elif ledger:
        raise RuntimeError('owned skill missing')
    if ledger:
        old = ledger['manifest']
        oldroot = base / old['source_commit']
        verify(oldroot, old)
        if entry.read_bytes() != launcher(oldroot, old):
            raise RuntimeError('entry identity drift')
        if ledger['skill_target'] != str(oldroot / 'skills/cc-dispatch'):
            raise RuntimeError('skill identity drift')
    if root.exists():
        verify(root, manifest)
    assert_activation(entry, state, skill, snapshot)
    return ledger, snapshot


def apply(base, root, entry, skill, data, manifest, ledger, snapshot):
    if ledger and ledger['manifest'] == manifest:
        return
    if not root.exists():
        base.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=base))
        try:
            for name, content in data.items():
                p = stage / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
                p.chmod(manifest['files'][name]['mode'])
            (stage / 'release.json').write_bytes(manifest_bytes(manifest))
            verify(stage, manifest)
            stage.rename(root)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    state = base / 'installation.json'
    assert_activation(entry, state, skill, snapshot)
    old_entry = snapshot['entry']
    old_state = snapshot['state']
    old_link = snapshot['link']
    wrapper = launcher(root, manifest)
    target = str(root / 'skills/cc-dispatch')
    new = {'owner': OWNER, 'entry': str(entry), 'skill': str(skill),
           'skill_target': target, 'manifest': manifest, 'entry_sha256': sha(wrapper)}
    # Keep the prior owned activation as a recoverable backup on upgrades.
    if ledger and ledger['manifest'] != manifest:
        context_io.atomic_write(base / 'previous-installation.json', old_state)
    written_entry = written_link = removed_link = written_state = False
    new_state = (json.dumps(new, indent=2) + '\n').encode()
    try:
        context_io.atomic_write(entry, wrapper, expected=sha(old_entry) if old_entry is not None else None)
        written_entry = True
        entry.chmod(0o755)
        skill.parent.mkdir(parents=True, exist_ok=True)
        if link_target(skill) != old_link:
            raise RuntimeError('skill drifted before activation')
        if old_link is not None:
            skill.unlink()
            removed_link = True
        skill.symlink_to(target, target_is_directory=True)
        written_link = True
        context_io.atomic_write(state, new_state, expected=sha(old_state) if old_state is not None else None)
        written_state = True
    except Exception:
        # Compensate only values this attempt wrote; leave foreign changes intact.
        for path, before, after, written in ((state, old_state, new_state, written_state),
                                             (entry, old_entry, wrapper, written_entry)):
            try:
                if written and context_io.fingerprint(path) == sha(after):
                    if before is None:
                        path.unlink()
                    else:
                        context_io.atomic_write(path, before, expected=sha(after))
            except (OSError, RuntimeError):
                pass
        try:
            current = link_target(skill)
            if written_link and current == target:
                skill.unlink()
                current = None
            if removed_link and current is None:
                skill.symlink_to(old_link, target_is_directory=True)
        except (OSError, RuntimeError):
            pass
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('plan', 'apply', 'check'), nargs='?', default='plan')
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--commit', required=True)
    a = p.parse_args()
    data, manifest = payload(a.source.absolute(), a.commit)
    base = Path.home() / '.local/share/cc-dispatch/releases'
    root = base / a.commit
    entry = Path.home() / '.local/bin/cc-dispatch'
    skill = Path.home() / '.claude/skills/cc-dispatch'
    if a.action == 'apply':
        with context_io.locks([str(base), str(entry), str(skill)]):
            ledger, snapshot = observe(base, root, entry, skill, manifest)
            apply(base, root, entry, skill, data, manifest, ledger, snapshot)
    else:
        ledger, snapshot = observe(base, root, entry, skill, manifest)
        if a.action == 'check':
            if not ledger or ledger['manifest'] != manifest:
                raise RuntimeError('requested commit is not active')
            verify(root, manifest)
    print(json.dumps({'action': a.action, 'source_commit': a.commit, 'root': str(root),
                      'entry': str(entry), 'skill': str(skill)}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        sys.stderr.write('installation refused: %s\n' % exc)
        sys.exit(1)
