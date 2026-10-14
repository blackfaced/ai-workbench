"""Conflict-protected v2 project snapshot restore; never restore arbitrary paths."""
import json
import os
from pathlib import Path
import re
import context_io


def restore(pc, repo, backup, dry_run, force):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', backup):
        raise RuntimeError('invalid backup name')
    root = Path(pc.backups_root(repo)) / backup
    context_io.guard(root)
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('version') != pc.env.MANIFEST_VERSION:
        raise RuntimeError('backup version mismatch')
    state = pc.load_state(repo)
    done=skipped=0
    global_paths = {os.path.join(os.path.realpath(os.path.expanduser('~')), p[2:]) for p in pc.GLOBAL_TRUST_CONFIG.values()}
    for entry in reversed(manifest['entries']):
        target = os.path.abspath(entry['original_path'])
        cid = entry.get('component','')
        if entry['kind'] == 'config_block':
            pieces=cid.split('::')
            if len(pieces)!=3 or pieces[1] not in pc.CLIENTS or pieces[2] not in pc.MANAGED_IDS:
                raise RuntimeError('invalid component identity')
            checkout=os.path.abspath(os.path.join(repo,pieces[0]))
            expected=os.path.join(checkout,pc.CLIENTS[pieces[1]])
            if target != expected: raise RuntimeError('manifest target outside component identity')
            known = state.get('components', {}).get(cid, {}).get('path')
            related = os.path.realpath(checkout) == os.path.realpath(repo)
            if not related:
                import subprocess
                common=[]
                for ck in (repo,checkout):
                    p=subprocess.run(['git','-C',ck,'rev-parse','--git-common-dir'],capture_output=True,text=True)
                    if p.returncode != 0: break
                    common.append(os.path.realpath(os.path.join(ck,p.stdout.strip())))
                related = len(common)==2 and common[0]==common[1]
            if not related and known != target:
                raise RuntimeError('external checkout lacks Git relation or ledger provenance')
            pc.guard_target(checkout, pc.CLIENTS[pieces[1]])
            if entry['block']['begin'] != pc.markers_for(pieces[2])[0] or entry['block']['end'] != pc.markers_for(pieces[2])[1]:
                raise RuntimeError('manifest marker mismatch')
        elif entry['kind'] == 'trust':
            if target not in global_paths or not cid.startswith(('trust::','trust-cleanup::')):
                raise RuntimeError('manifest trust target outside authorized config')
        else:
            raise RuntimeError('unsupported snapshot kind')
        context_io.guard(target)
        observed=context_io.fingerprint(target)
        text,nl=pc._read_for_edit(target)
        pc.validate_toml(text,target)
        previous=entry.get('backup_file')
        raw_before=b''
        if previous:
            if Path(previous).name != previous: raise RuntimeError('unsafe backup file')
            src=root/previous
            context_io.guard(src)
            raw_before=src.read_bytes()
            if pc.env.sha256_file(str(src)) != entry['sha256']: raise RuntimeError('backup digest mismatch')
        changed=False
        new_text=text
        try:
            if entry['kind']=='trust':
                block=entry['block']
                if 'table_before' in block:
                    key=block['path']
                    if not isinstance(key,str) or not os.path.isabs(key) or block.get('begin') != pc._project_table_header(key):
                        raise RuntimeError('trust key/header mismatch')
                    # A trust snapshot may only change its named project table.
                    for fragment in (block['table_before'],block['table_after']):
                        parsed=pc.load_toml_parser().loads(fragment)
                        if parsed and (set(parsed)!={'projects'} or set(parsed['projects'])!={key}):
                            raise RuntimeError('trust snapshot contains unrelated sections')
                    current=pc._trust_table(text,key)
                    if current != block['table_after'] and not force: raise RuntimeError('trust table changed after apply')
                    new_text=pc._replace_trust_table(text,key,block['table_before'])
                else:
                    reason=pc.env.restore_guard(entry)
                    if reason and not force: raise RuntimeError(reason)
                    new_text=raw_before.decode('utf-8')
            else:
                block=entry['block']; begin,end=block['begin'],block['end']
                current=pc.env.extract_block(text,begin,end)
                before=block['previous_body']; applied=block.get('applied_body')
                # Removal snapshots from legacy versions recorded None after write.
                if current != applied and not force:
                    raise RuntimeError('managed block changed after apply')
                if current is None and before is None:
                    print('  already absent: '+target); skipped+=1; continue
                lines=text.splitlines(keepends=True)
                if current is not None:
                    b=next(i for i,l in enumerate(lines) if l.strip()==begin)
                    e=next(i for i,l in enumerate(lines[b+1:],b+1) if l.strip()==end)
                    stop=e+1
                    if before is None and block.get('inserted_blank_after') and stop<len(lines) and not lines[stop].strip(): stop+=1
                    replacement=[] if before is None else pc._build_block_lines(begin,before,end,nl)
                    lines[b:stop]=replacement
                elif before is not None:
                    hit=pc._detect_table_line(lines)
                    insert=pc._build_block_lines(begin,before,end,nl)
                    if hit is not None:
                        lines[hit:hit]=insert+([nl] if block.get('inserted_blank_after') else [])
                    else:
                        lines.extend(insert)
                new_text=''.join(lines)
            pc.validate_toml(new_text,target)
            changed=new_text != text
            if not dry_run and changed:
                # A newly-created native file can be removed only if it has no
                # added user content; otherwise retain that content as a file.
                if not entry['existed'] and new_text.strip()=='':
                    if context_io.fingerprint(target)!=observed: raise RuntimeError('restore target drift')
                    os.unlink(target)
                else:
                    context_io.atomic_write(target,new_text,observed)
            if not dry_run:
                before_state=entry.get('state_before') or {}
                if before_state: state.setdefault('components',{}).update(before_state)
                else: state.get('components',{}).pop(cid,None)
            done+=1
            print('  '+('would restore ' if dry_run else 'restored ')+target)
        except RuntimeError as exc:
            skipped+=1
            print('  restore blocked: '+str(exc))
    if not dry_run: pc.save_state(repo,state)
    print('restore done=%s skipped=%s' % (done,skipped))
    return 1 if skipped else 0
