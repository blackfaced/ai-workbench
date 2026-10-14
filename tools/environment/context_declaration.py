"""Strict project declaration validation; project rules are never built in."""
import hashlib
import json
import os
import re
from pathlib import Path


ROOT_FIELDS = {'version','tracker','commitConvention','knowledgeSources','lazyPolicy',
               'pack','additiveEntry','profiles','instructions','rulesSource','trust'}


def string(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise RuntimeError('%s must be a non-empty string' % label)
    return value


def fields(value, allowed, label):
    if not isinstance(value, dict):
        raise RuntimeError('%s must be an object' % label)
    unknown = set(value) - set(allowed)
    if unknown:
        raise RuntimeError('unsupported %s fields: %s' % (label, sorted(unknown)))


def validate(decl, clients):
    fields(decl, ROOT_FIELDS, 'declaration')
    if 'version' in decl and (type(decl['version']) is not int or decl['version'] != 1):
        raise RuntimeError('unsupported declaration version')
    if 'trust' in decl and type(decl['trust']) is not bool:
        raise RuntimeError('trust must be boolean; declaration is not runtime authorization')
    tr = decl.get('tracker', {})
    fields(tr, {'kind','workItemIdRequired','idPattern'}, 'tracker')
    if 'kind' in tr: string(tr['kind'], 'tracker.kind')
    if 'workItemIdRequired' in tr and type(tr['workItemIdRequired']) is not bool:
        raise RuntimeError('workItemIdRequired must be boolean')
    if 'idPattern' in tr: string(tr['idPattern'], 'tracker.idPattern')
    if tr.get('workItemIdRequired') and not tr.get('idPattern'):
        raise RuntimeError('workItemIdRequired needs project-owned idPattern')
    cc = decl.get('commitConvention', {})
    fields(cc, {'carriesWorkItem'}, 'commitConvention')
    if 'carriesWorkItem' in cc and type(cc['carriesWorkItem']) is not bool:
        raise RuntimeError('carriesWorkItem must be boolean')
    if cc.get('carriesWorkItem') is False and tr.get('workItemIdRequired'):
        raise RuntimeError('conflicting project work-item requirements')
    if cc.get('carriesWorkItem') is True and not tr.get('workItemIdRequired'):
        raise RuntimeError('commit carriesWorkItem requires tracker.workItemIdRequired')
    if 'lazyPolicy' in decl and decl['lazyPolicy'] != 'complete':
        raise RuntimeError('unsupported lazyPolicy')
    sources = decl.get('knowledgeSources', [])
    if not isinstance(sources, list): raise RuntimeError('knowledgeSources must be array')
    for source in sources:
        fields(source, {'ref','load'}, 'knowledgeSource')
        string(source.get('ref'), 'knowledgeSource.ref')
        if source.get('load', 'on-demand') != 'on-demand': raise RuntimeError('unsupported source load')
    fields(decl.get('pack', {}), {'source','revision'}, 'pack')
    if decl.get('pack') and set(decl['pack']) != {'source','revision'}:
        raise RuntimeError('pack needs both source and revision')
    for k,v in decl.get('pack', {}).items(): string(v, 'pack.'+k)
    entry = decl.get('additiveEntry', {})
    fields(entry, {'clients','files','field','markerPrefix','tracked'}, 'additiveEntry')
    chosen = entry.get('clients', list(clients))
    if not isinstance(chosen,list) or not chosen or any(c not in clients for c in chosen) or len(set(chosen)) != len(chosen):
        raise RuntimeError('clients must be a non-empty unique supported list')
    fields(entry.get('files', {}), set(clients), 'additiveEntry.files')
    for c,p in entry.get('files', {}).items():
        if p != clients[c]: raise RuntimeError('custom native file paths unsupported; refusing to ignore')
    if entry.get('field', 'developer_instructions') != 'developer_instructions': raise RuntimeError('unsupported additive field')
    if entry.get('markerPrefix','setup-aiwb:') != 'setup-aiwb:': raise RuntimeError('unsupported markerPrefix')
    if entry.get('tracked') is True:
        raise RuntimeError('tracked native config requires explicit ownership reconciliation outside this renderer')
    if 'tracked' in entry and type(entry['tracked']) is not bool: raise RuntimeError('tracked must be boolean')
    profiles = decl.get('profiles', {})
    if not isinstance(profiles,dict): raise RuntimeError('profiles must be object')
    for name,body in profiles.items(): string(name,'profile'); string(body,'profile instructions')
    if 'instructions' in decl: string(decl['instructions'],'instructions')
    if 'rulesSource' in decl:
        fields(decl['rulesSource'], {'path','sha256'}, 'rulesSource')
        string(decl['rulesSource'].get('path'), 'rulesSource.path')
        if not re.fullmatch('[0-9a-f]{64}', str(decl['rulesSource'].get('sha256',''))):
            raise RuntimeError('rulesSource requires sha256 pin')
    return chosen


def rule_text(decl, profile, repo):
    parts = []
    direct = decl.get('profiles', {}).get(profile, decl.get('instructions'))
    if direct: parts.append(direct)
    source = decl.get('rulesSource')
    if source:
        path = Path(source['path'])
        if not path.is_absolute():
            root = Path(repo).resolve()
            path = root / path
            if os.path.commonpath([str(root),str(path.resolve())]) != str(root):
                raise RuntimeError('relative rule source escapes project')
        from context_io import guard
        guard(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise RuntimeError('project rule source digest mismatch')
        parts.append(raw.decode('utf-8'))
    tr = decl.get('tracker', {})
    if tr.get('workItemIdRequired'):
        parts.append('Tracker: %s. Every commit / MR must carry project work-item pattern %s.' % (tr.get('kind','project'),tr['idPattern']))
    for source in decl.get('knowledgeSources', []):
        parts.append('Load owning project source on demand: '+source['ref'])
    if decl.get('lazyPolicy') == 'complete':
        parts.append('Resolve and verify the complete project source chain before acting.')
    if decl.get('pack'):
        pack=decl['pack']
        parts.append('Selected instruction pack: %s @ %s.' % (pack.get('source','project'),pack.get('revision','unspecified')))
    if not parts:
        return None
    return '\n'.join(parts)
