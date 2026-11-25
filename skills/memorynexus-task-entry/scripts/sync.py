#!/usr/bin/env python3
"""Resolve one registered task and paired device, then run one pinned refresh."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import uuid

from lookup import lookup, normalized


class SyncError(Exception):
    pass


def check(condition, code):
    if not condition:
        raise SyncError(code)


def canonical_id(value):
    check(type(value) is str and str(uuid.UUID(value)) == value, 'invalid_identity')
    return value


def private_binding(path):
    path = Path(path)
    check(path.is_absolute() and path.resolve() == path, 'invalid_binding')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
              and not info.st_mode & 0o077, 'invalid_binding')
        raw = stream.read(32769)
    check(len(raw) <= 32768, 'invalid_binding')
    return json.loads(raw)


def checked_path(value, code):
    path = Path(value)
    check(path.is_absolute() and path.resolve(strict=True) == path, code)
    info = path.lstat()
    check(info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022, code)
    return path


def file_digest(path, limit, code):
    check(path.is_file() and path.stat().st_size <= limit, code)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_digest(package):
    code = 'invalid_package_pin'
    check(package.is_dir(), code)
    inventory = []
    for entry in sorted(package.rglob('*')):
        checked_path(entry, code)
        if not entry.is_dir():
            inventory.append({'path': entry.relative_to(package).as_posix(),
                              'sha256': file_digest(entry, 8 * 1024 * 1024, code)})
    raw = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def endpoint(ref):
    code = 'invalid_endpoint_pin'
    path = checked_path(ref['path'], code)
    check(file_digest(path, 8 * 1024 * 1024, code) == ref['sha256']
          and os.access(path, os.X_OK), code)
    return str(path)


def call(argv, timeout, code, *, accepted=(0,), data=None):
    try:
        proc = subprocess.run(argv, input=data if data is not None else b'',
                              capture_output=True, timeout=timeout, check=False)
        check(proc.returncode in accepted and len(proc.stdout) <= 262144, code)
        value = json.loads(proc.stdout)
        check(isinstance(value, dict), code)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise SyncError(code) from None
    return value


def runtime(task):
    binding = private_binding(task['binding'])
    check(binding['schema_version'] == 1 and binding['task_id'] == task['task_id'],
          'binding_task_mismatch')
    package = checked_path(binding['package'], 'invalid_package_pin')
    check(package_digest(package) == binding['package_sha256'], 'invalid_package_pin')
    check((package / 'refresh_peer.py').is_file(), 'refresh_unsupported')
    python = str(checked_path(binding['python'], 'invalid_python_pin'))
    read = [python, '-I', '-S', '-B', str(package / 'daily.py'), 'read',
            '--binding', task['binding']]
    return read, [python, '-I', '-S', '-B', str(package / 'refresh_peer.py')], binding['binary']


def bound_progress(read, task_id, binary=None):
    value = call(read, 45, 'binding_unavailable', accepted=(0, 3))
    check(value.get('schema_version') == 1 and value.get('status') in ('ok', 'incomplete'),
          'binding_unavailable')
    context = value['context']
    check(context['task_id'] == task_id, 'binding_task_mismatch')
    progress = context['result'].get('relay_progress')
    if progress is None:
        if binary is not None:
            help_reply = call([binary, 'task', '--help'], 15, 'refresh_unsupported')
            check(help_reply.get('schema_version') == 1 and help_reply.get('status') == 'ok'
                  and help_reply['result'].get('relay_progress') == 1, 'refresh_unsupported')
        raise SyncError('task_not_paired')
    check(progress['task_id'] == task_id, 'binding_task_mismatch')
    return progress


def identity(value):
    return tuple(value[k] for k in ('task_id', 'epoch', 'device', 'peer'))


def relay_status(cmd):
    value = call([cmd, 'status'], 30, 'endpoint_unavailable', data=b'{}')
    check(value.get('schema_version') == 1 and value.get('status') == 'ok',
          'endpoint_unavailable')
    progress = value['result']
    check(value.get('task_id') == progress['task_id'], 'endpoint_identity_mismatch')
    return progress


def summary(direction):
    out = {}
    for field in ('through', 'target', 'pending_count'):
        value = direction.get(field)
        check(value is None or type(value) is int and value >= 0, 'invalid_refresh_result')
        out[field] = value
    check(type(direction.get('covered')) is bool and out['through'] is not None,
          'invalid_refresh_result')
    out['covered'] = direction['covered']
    return out


def completed(value, expected, reversed_pair):
    round_id = canonical_id(value['round'])
    local, peer = value['local'], value['peer']
    check(identity(local) == expected and identity(peer) == reversed_pair
          and local['round'] == peer['round'] == round_id, 'invalid_refresh_result')
    results = {}
    for name, sender, receiver, side in (
        ('outgoing', local, peer, 'local'), ('incoming', peer, local, 'peer'),
    ):
        outgoing, incoming = summary(sender['outgoing']), summary(receiver['incoming'])
        target = outgoing['target']
        bounds = value['targets'][side]
        check(outgoing['covered'] and incoming['covered'] and target is not None
              and incoming['target'] == target and outgoing['through'] >= target
              and incoming['through'] >= target and type(bounds['through']) is int
              and bounds['through'] == target and type(bounds['after']) is int
              and 0 <= bounds['after'] <= target and outgoing['pending_count'] is not None,
              'invalid_refresh_result')
        results[name] = outgoing
    return {'round': round_id, **results}


def candidates(items, name, key, selected):
    target, seen, matches = normalized(name), set(), []
    check(isinstance(items, list) and len(items) <= 1000, 'invalid_device_index')
    if selected is not None:
        canonical_id(selected)
    for item in items:
        item_id = canonical_id(item[key])
        check(item_id not in seen, 'duplicate_identity')
        seen.add(item_id)
        aliases = item.get('aliases', [])
        detail = item.get('description', '')
        check(isinstance(aliases, list) and len(aliases) <= 20
              and isinstance(detail, str) and len(detail) <= 240, 'invalid_device_index')
        keys = [normalized(value) for value in [item['name'], *aliases]]
        if target in keys and (selected is None or selected == item_id):
            matches.append(item)
    return matches


def public_row(item, key):
    return {key: item[key], 'name': item['name'], 'description': item.get('description', '')}


def pending_state(progress):
    return {'round': progress.get('round'), 'outgoing': summary(progress['outgoing']),
            'incoming': summary(progress['incoming'])}


def sync(args):
    try:
        tasks = lookup(args.index, args.task, include_relay=True)['matches']
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SyncError('task_index_unavailable_or_invalid') from None
    if args.task_id is not None:
        selected = canonical_id(args.task_id)
        tasks = [task for task in tasks if task['task_id'] == selected]
    if len(tasks) != 1:
        return {'status': 'choose_task' if tasks else 'task_not_found',
                'matches': [public_row(task, 'task_id') for task in tasks]}
    task = tasks[0]
    relay = task.get('relay')
    check(isinstance(relay, dict), 'pair_not_configured')
    devices = candidates(relay['devices'], args.device, 'device_id', args.device_id)
    if len(devices) != 1:
        return {'status': 'choose_device' if devices else 'device_not_found',
                'task': public_row(task, 'task_id'),
                'matches': [public_row(device, 'device_id') for device in devices]}
    device = devices[0]
    read, refresh, binary = runtime(task)
    progress = bound_progress(read, task['task_id'], binary)
    task_id, epoch, local_id, peer_id = expected = identity(progress)
    check(peer_id == device['device_id'], 'device_not_paired_to_task')
    reversed_pair = (task_id, epoch, peer_id, local_id)
    local = endpoint(relay['local'])
    peer = endpoint(device['endpoint'])
    check(local != peer, 'endpoint_identity_mismatch')
    result = {'task': public_row(task, 'task_id'), 'device': public_row(device, 'device_id'),
              'path': 'unknown', 'subsequent_peer_tail': 'unknown'}
    try:
        check(identity(relay_status(local)) == expected, 'endpoint_identity_mismatch')
        check(identity(relay_status(peer)) == reversed_pair, 'endpoint_identity_mismatch')
        reply = call([*refresh, '--local', local, '--peer', peer], 180, 'refresh_unconfirmed')
        try:
            checked = completed(reply, expected, reversed_pair)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SyncError('invalid_refresh_result') from None
        return {**result, 'status': 'synced', **checked}
    except SyncError as exc:
        if str(exc) == 'endpoint_identity_mismatch':
            raise
        # The upstream helper may exit after a partial write or lost receipt.
        # Its failure does not identify a completed round. Use bound readback
        # for the last verifiable local position, never promote it to success.
        try:
            observed = bound_progress(read, task_id)
            if identity(observed) == expected:
                progress = observed
        except (SyncError, KeyError, TypeError):
            pass
        return {**result, 'status': 'pending', 'code': str(exc),
                'last_observed': pending_state(progress)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--index', type=Path, default=Path.home() / '.local/share/memorynexus/task-index.json')
    parser.add_argument('--task', required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--task-id')
    parser.add_argument('--device-id')
    args = parser.parse_args()
    try:
        value = sync(args)
    except (SyncError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        value = {'status': 'error', 'code': str(exc) if isinstance(exc, SyncError) else 'invalid_sync_configuration'}
    print(json.dumps({'schema_version': 1, **value}, ensure_ascii=False))
    return 2 if value['status'] in ('error', 'pending') else 0


if __name__ == '__main__':
    raise SystemExit(main())
