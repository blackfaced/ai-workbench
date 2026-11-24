#!/usr/bin/env python3
"""Report managed credential presence without returning values or making calls."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys


MAX_BYTES = 1024 * 1024
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,79}')


def read_json(path):
    """Bound reads and reject special files before parsing; never return errors."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError('unsupported source')
        data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('oversized source')
    return json.loads(data)


def validate(profile):
    if (not isinstance(profile, dict) or type(profile.get('version')) is not int or profile['version'] != 1
            or not isinstance(profile.get('sources'), list) or not profile['sources']):
        raise ValueError('profile invalid')
    seen = set()
    for source in profile['sources']:
        name = source['id']
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in seen:
            raise ValueError('source identity invalid')
        seen.add(name)
        if source['type'] not in ('json', 'environment'):
            raise ValueError('source type invalid')
        if source['type'] == 'json' and (not isinstance(source.get('path'), str) or not source['path']):
            raise ValueError('source path invalid')
        if source.get('recovery', 'unverified') not in ('available', 'unavailable', 'unverified'):
            raise ValueError('recovery state invalid')
        authentication = source.get('authentication', 'unverified')
        if authentication not in ('valid', 'invalid', 'unverified'):
            raise ValueError('authentication state invalid')
        reference = source.get('authentication_evidence_ref')
        if authentication != 'unverified' and (not isinstance(reference, str) or not reference.strip()):
            raise ValueError('authentication evidence missing')
        fields = source.get('fields')
        if not isinstance(fields, list) or not fields:
            raise ValueError('fields required')
        names = set()
        for field in fields:
            if not isinstance(field['name'], str) or not NAME.fullmatch(field['name']) or field['name'] in names:
                raise ValueError('field label invalid')
            names.add(field['name'])
            keys = field['keys']
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k for k in keys):
                raise ValueError('field path invalid')
            for key in keys:
                key.encode('utf-8')
            if source['type'] == 'environment' and len(keys) != 1:
                raise ValueError('environment field must name one variable')
            if type(field.get('secret', False)) is not bool:
                raise ValueError('field kind invalid')


def field_present(value, keys):
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return value is not None and value != '' and value != [] and value != {}


def inspect_source(source, base, environ):
    data, unavailable = None, None
    try:
        if source['type'] == 'environment':
            data = environ
        else:
            path = Path(source['path']).expanduser()
            data = read_json(path if path.is_absolute() else base/path)
            if not isinstance(data, dict):
                raise ValueError('source must be an object')
    except FileNotFoundError:
        unavailable = 'missing'
    except (OSError, ValueError, TypeError, RuntimeError):
        unavailable = 'unverified'
    fields = [{'name':f['name'], 'keys':f['keys'], 'secret':f.get('secret',False),
               'status':unavailable or ('present' if field_present(data,f['keys']) else 'missing')}
              for f in source['fields']]
    status = ('unverified' if any(f['status']=='unverified' for f in fields) else
              'missing' if any(f['status']=='missing' for f in fields) else 'present')
    authentication = source.get('authentication','unverified')
    recovery = source.get('recovery','unverified')
    missing_secret = any(f['secret'] and f['status']=='missing' for f in fields)
    if status == 'unverified':
        action = 'resolve_evidence'
    elif missing_secret or authentication == 'invalid':
        action = {'available':'use_managed_recovery', 'unavailable':'ask_user',
                  'unverified':'resolve_evidence'}[recovery]
    elif status == 'missing':
        action = 'discover_identifiers'
    else:
        action = 'not_needed'
    return {'id':source['id'], 'type':source['type'], 'status':status, 'fields':fields,
            'supplied_authentication':authentication, 'recovery':recovery, 'action':action}


def preflight(profile, *, base, environ):
    validate(profile)
    rows = [inspect_source(source,base,environ) for source in profile['sources']]
    status = ('unverified' if any(r['status']=='unverified' for r in rows) else
              'missing' if any(r['status']=='missing' for r in rows) else 'present')
    return {'status':status, 'execution_context':'current-process', 'sources':rows,
            'question_sources':[r['id'] for r in rows if r['action']=='ask_user'],
            'authentication_verified':False, 'native_session_verified':False,
            'side_effects':[]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        profile = read_json(args.profile)
        report = preflight(profile,base=args.profile.resolve().parent,environ=dict(os.environ))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        # Paths, parser context and rejected values may contain private data.
        print(json.dumps({'status':'unverified','reason':'profile_unavailable_or_invalid',
                          'question_sources':[], 'side_effects':[]}))
        return 2
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report['status']=='present' and all(r['action']=='not_needed' for r in report['sources']) else 2


if __name__ == '__main__': sys.exit(main())
