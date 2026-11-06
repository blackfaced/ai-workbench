#!/usr/bin/env python3
"""Read a local task-name index. Does not open bindings or task ledgers."""
import argparse
import json
import os
from pathlib import Path
import stat
import unicodedata
import uuid


def normalized(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise ValueError('invalid_name')
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def lookup(path, name):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('invalid_index')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('invalid_index_permissions')
    if info.st_size > 262144:
        raise ValueError('oversize_index')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('invalid_index')
    tasks = value.get('tasks')
    if not isinstance(tasks, list) or len(tasks) > 1000:
        raise ValueError('invalid_index')
    target = normalized(name)
    matches, known, ids = [], [], set()
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError('invalid_index')
        task_id = str(uuid.UUID(item['task_id']))
        if task_id != item['task_id'] or task_id in ids:
            raise ValueError('duplicate_or_invalid_task_id')
        ids.add(task_id)
        title = item['name']
        aliases = item.get('aliases', [])
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise ValueError('invalid_index')
        keys = [normalized(x) for x in [title] + aliases]
        binding = Path(item['binding'])
        if not binding.is_absolute() or '..' in binding.parts:
            raise ValueError('invalid_binding_path')
        detail = item.get('description', '')
        if not isinstance(detail, str) or len(detail) > 240:
            raise ValueError('invalid_index')
        known.append(title)
        if target in keys:
            matches.append({'task_id': task_id, 'name': title,
                            'description': detail, 'binding': str(binding)})
    status = 'matched' if len(matches) == 1 else 'choose' if matches else 'not_found'
    return {'schema_version': 1, 'status': status, 'matches': matches,
            **({'registered_names': list(dict.fromkeys(known))} if not matches else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--index', type=Path, default=Path.home() / '.local/share/memorynexus/task-index.json')
    args = parser.parse_args()
    try:
        result = lookup(args.index, args.name)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({'schema_version': 1, 'status': 'error', 'code': 'task_index_unavailable_or_invalid'}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
