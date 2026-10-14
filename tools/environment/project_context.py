#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project-owned additive context, explicit trust, guarded project snapshots.

Legacy profile names/markers and v2 ledgers remain supported. Rule bodies come
from project declarations/pinned local sources, never from machine-wide policy.
Python 3.9 imports are supported; writes require tomllib or tomli.
"""

import argparse
import json
import os
import re
import sys
import hashlib
import tempfile
import context_io

import env  # same directory: the environment installer whose primitives we reuse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT_DEFAULT = os.getcwd()

# Managed-segment catalogue. A given checkout resolves to at most ONE of these
# being present; the other must be absent. `none` means both are absent.
PROFILES = ("none", "project", "owned-full", "legacy-only")
PROFILE_TO_ID = {
    "none": None,
    "project": "project-context",
    "owned-full": "owned-work-rules",
    "legacy-only": "legacy-commit-id",
}
MANAGED_IDS = tuple(PROFILE_TO_ID[i] for i in PROFILES if PROFILE_TO_ID[i])

CLIENTS = {
    "codex": ".codex/config.toml",
    "trae": ".trae/traecli.toml",
}
# User-level global config files where we manage ONLY [projects."<abs>"]
# trust_level (permission), never instruction body.
GLOBAL_TRUST_CONFIG = {
    "codex": "~/.codex/config.toml",
    "trae": "~/.trae/traecli.toml",
}
FIELD = "developer_instructions"
MARKER_PREFIX = "setup-aiwb:"

# Top-level TOML keys must appear before the first table header.
TABLE_HEADER_RE = re.compile(r"^\s*\[")

with open(__file__, "rb") as _source_file:
    DEFAULT_PIN = "candidate-" + hashlib.sha256(_source_file.read()).hexdigest()[:12]


# --------------------------------------------------------------------------
# TOML validation (lazy: tomllib is stdlib only on 3.11+)
# --------------------------------------------------------------------------

def load_toml_parser():
    try:
        import tomllib  # type: ignore
        return tomllib
    except ImportError:  # pragma: no cover - exercised only on py<3.11
        try:
            import tomli  # type: ignore
            return tomli
        except ImportError:
            return None


def validate_toml(text, what):
    """A parser is mandatory for every configuration write and check."""
    parser = load_toml_parser()
    if parser is None:
        raise RuntimeError("TOML parser required; use Python 3.11+ or install tomli")
    try:
        parser.loads(text)
    except Exception as exc:  # tomllib.TOMLDecodeError
        raise RuntimeError("emitted TOML invalid for %s: %s" % (what, exc))
    return None


# --------------------------------------------------------------------------
# Instruction bodies (the only place generic rule text lives; projects reuse by
# selecting a profile, never by copying this body)
# --------------------------------------------------------------------------

def _provenance_lines(pin, workenv):
    return [
        "# --- managed by setup-aiwb (do not edit by hand; use project_context.py) ---",
        "# source: aiwb@%s workenv=%s" % (pin[:12] if re.fullmatch(r'[0-9a-f]{40}', pin) else pin, workenv),
    ]


def render_body(profile, pin, workenv, rules=None):
    """Render only project-owned text. Legacy profiles select marker IDs only."""
    if profile == "none":
        return None
    if rules is None:
        raise RuntimeError("project rules required: pass --declaration; existing owned blocks can be checked without one")
    # JSON basic string is also valid TOML; literal multiline keeps old shapes
    # when safe and basic-string fallback handles embedded literal delimiters.
    text = "\n" + "\n".join(_provenance_lines(pin, workenv)) + "\n\n" + rules + "\n"
    if "'''" not in text:
        return ["%s = '''" % FIELD] + text.split("\n")[:-1] + ["'''"]
    return [FIELD + " = " + json.dumps(text, ensure_ascii=False)]


# --------------------------------------------------------------------------
# Project-scoped state / backup (reuse env.Backup, redirect the root)
# --------------------------------------------------------------------------

def state_dir(repo):
    return os.path.join(repo, ".ai-workbench", "project-context")


def state_path(repo):
    return os.path.join(state_dir(repo), "state.json")


def load_state(repo):
    path = state_path(repo)
    if not os.path.exists(path):
        return {"components": {}}
    context_io.guard(path)
    state = json.loads(env.read_text(path))
    if not isinstance(state, dict) or not isinstance(state.get("components"), dict):
        raise RuntimeError("invalid ledger; refusing to discard ownership evidence")
    return state


def save_state(repo, state):
    context_io.atomic_write(state_path(repo), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


class ProjectBackup(env.Backup):
    """An env.Backup whose snapshot root lives inside the repo checkout."""

    def __init__(self, repo):
        super(ProjectBackup, self).__init__()
        self._root = os.path.join(state_dir(repo), "backups")

    def _ensure_dir(self):
        if self.dir is None:
            context_io.guard(self._root)
            os.makedirs(self._root, exist_ok=True)
            import time
            self.dir = tempfile.mkdtemp(prefix=env.utc_stamp()+"-%020d-" % time.time_ns(), dir=self._root)
        return self.dir

    def _flush(self):
        context_io.atomic_write(os.path.join(self.dir, "manifest.json"),
            json.dumps({"version": env.MANIFEST_VERSION, "created_at": env.utc_iso(),
                        "entries": self.entries}, ensure_ascii=False, indent=2)+"\n")


class Ctx(object):
    """Minimal context exposing exactly what env.write_block / the guard need."""

    def __init__(self, repo, force=False):
        self.repo = repo
        self.state = load_state(repo)
        self.backup = ProjectBackup(repo)
        self.force = force

    # mirrors env.Context.backup_save: record state_before for rollback
    def backup_save(self, path, component=None, state_keys=None, **kwargs):
        components = self.state.get("components", {})
        before = {}
        for key in (state_keys if state_keys is not None else [component]):
            if key in components:
                before[key] = dict(components[key])
        return self.backup.save(path, component=component, state_before=before, **kwargs)

    def record(self, cid, entry):
        entry["applied_at"] = env.utc_iso()
        entry["backup_dir"] = self.backup.dir
        self.state.setdefault("components", {})[cid] = entry


# --------------------------------------------------------------------------
# Hard guards (path containment, symlink, ACL) -- the installer never needed
# --------------------------------------------------------------------------

def _resolve_in_repo(repo, rel):
    """Resolve ``repo/rel`` and refuse anything that escapes the repo root.

    Returns the absolute path or raises RuntimeError.
    """
    repo_abs = os.path.realpath(repo)
    # lexically join first so '..' is visible before any symlink resolution
    joined = os.path.normpath(os.path.join(repo_abs, rel))
    if joined != repo_abs and not joined.startswith(repo_abs + os.sep):
        raise RuntimeError("path traversal refused: %r escapes repo %r" % (rel, repo_abs))
    real = os.path.realpath(joined)
    if real != repo_abs and not real.startswith(repo_abs + os.sep):
        raise RuntimeError("path resolves outside repo (symlink escape?): %r" % rel)
    return joined


def guard_target(repo, rel):
    """Validate a target file path BEFORE any write. Returns absolute path."""
    abs_path = _resolve_in_repo(repo, rel)
    if os.path.islink(abs_path):
        raise RuntimeError("refusing to follow symlink %r (managed block must own a real file)" % abs_path)
    parent = os.path.dirname(abs_path)
    if os.path.islink(parent):
        raise RuntimeError("refusing: parent of %r is a symlink" % abs_path)
    if os.path.exists(abs_path):
        st = os.stat(abs_path)
        if st.st_uid != os.getuid():
            raise RuntimeError("refusing to write foreign-owned file %r (uid=%d, mine=%d)"
                               % (abs_path, st.st_uid, os.getuid()))
        if not os.access(abs_path, os.W_OK):
            raise RuntimeError("refusing to write read-only / non-writable target %r (ACL)" % abs_path)
    context_io.guard(abs_path)
    return abs_path


# --------------------------------------------------------------------------
# Plan / apply for one target file
# --------------------------------------------------------------------------

def markers_for(mid):
    return ("# %s%s BEGIN" % (MARKER_PREFIX, mid),
            "# %s%s END" % (MARKER_PREFIX, mid))


def desired_id(profile):
    return PROFILE_TO_ID[profile]


def build_plan(repo, profile, pin, workenv, clients, worktrees, rules=None):
    """Return a Plan of actions over the enumerated checkouts.

    ``worktrees`` is an explicit list of checkout roots (main repo + declared
    worktrees). We never discover checkouts ourselves.
    """
    plan = {"changes": [], "blocked": [], "notes": [], "obs": []}
    desired = desired_id(profile)
    ledger = load_state(repo).get("components", {})

    def foreign(cid_key, current):
        """Mirror env.overwrite_guard for planning: block foreign/stale blocks."""
        recorded = ledger.get(cid_key, {}).get("sha256_after_apply")
        if recorded is None:
            return "块存在但非本入口安装（不是我写的），不接管；需要人工协调声明与现有归属"
        if recorded != env.sha256_text(current):
            return "块与安装记录不一致（安装后被改过），不覆盖；需要人工协调声明与现有归属"
        return None

    for checkout in [repo] + list(worktrees):
        checkout = os.path.realpath(checkout)
        if not os.path.isdir(checkout):
            plan["blocked"].append((checkout, "declared checkout does not exist"))
            continue
        for client in clients:
            rel = CLIENTS[client]
            try:
                abs_target = guard_target(checkout, rel)
            except RuntimeError as exc:
                plan["blocked"].append((client, str(exc)))
                continue

            try:
                existing, _nl = _read_for_edit(abs_target)
                validate_toml(existing, rel)
                import subprocess
                tracked = subprocess.run(["git", "-C", checkout, "ls-files", "--error-unmatch", "--", rel],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if tracked.returncode == 0:
                    raise RuntimeError("native config is Git-tracked; private ownership reconciliation required")
                observed_hash = context_io.fingerprint(abs_target)
                for managed in MANAGED_IDS:
                    begin_m, end_m = markers_for(managed)
                    if existing.count(begin_m) != existing.count(end_m) or existing.count(begin_m) > 1:
                        raise RuntimeError("malformed/duplicate managed markers")
            except RuntimeError as exc:
                plan["blocked"].append((client, str(exc)))
                continue

            # Reconcile every managed id: desired -> write/update, undesired -> remove.
            for mid in MANAGED_IDS:
                begin, end = markers_for(mid)
                current = env.extract_block(existing, begin, end)
                cid = "%s::%s::%s" % (os.path.relpath(checkout, repo), client, mid)

                if mid == desired:
                    if rules is None:
                        reason = foreign(cid, current) if current is not None else "project rules required: --declaration"
                        if reason:
                            plan["blocked"].append((cid, reason))
                        else:
                            plan["notes"].append((cid, "owned legacy block retained; declaration migration pending"))
                        continue
                    want_lines = render_body(profile, pin, workenv, rules)
                    desired_text = "\n".join(want_lines)
                    if current is not None and current == desired_text:
                        reason = foreign(cid, current)
                        if reason:
                            plan["blocked"].append((cid, reason))
                        else:
                            plan["notes"].append((cid, "managed block already target shape"))
                        continue
                    if current is not None:
                        reason = foreign(cid, current)
                        if reason:
                            plan["blocked"].append((cid, reason))
                            continue
                    plan["changes"].append((cid, "update" if current is not None else "insert", {
                        "kind": "upsert", "checkout": checkout, "rel": rel,
                        "abs": abs_target, "observed_hash": observed_hash, "mid": mid, "client": client,
                        "profile": profile, "begin": begin, "end": end,
                        "body": desired_text, "current": current,
                    }))
                else:
                    # undesired managed id present -> remove it (foreign -> block)
                    if current is not None:
                        reason = foreign(cid, current)
                        if reason:
                            plan["blocked"].append((cid, reason))
                            continue
                        plan["changes"].append((cid, "remove", {
                            "kind": "remove", "checkout": checkout, "rel": rel,
                            "abs": abs_target, "observed_hash": observed_hash, "mid": mid, "client": client,
                            "profile": profile, "begin": begin, "end": end,
                            "current": current,
                        }))
    return plan


def _insert_before_re(text):
    """Insert managed block before the first table header; None => append."""
    for line in text.splitlines():
        if TABLE_HEADER_RE.match(line):
            return r"^\s*\["
    return None


def _detect_table_line(lines_with_ends):
    """Index of first TOML table-header line, or None. Lines keep their NL."""
    for i, line in enumerate(lines_with_ends):
        if TABLE_HEADER_RE.match(line.strip()):
            return i
    return None


def _read_for_edit(path):
    """Return (text, nl); fail closed on non-UTF8 (no write ever happens)."""
    if not os.path.isfile(path):
        return "", "\n"
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw:
        return "", "\n"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("target is not UTF-8; refusing to edit: %s" % path)
    nl = "\r\n" if "\r\n" in text else "\n"
    return text, nl


def _build_block_lines(begin, body, end, nl):
    """Block lines terminated with the file's own newline style."""
    body_nl = body.replace("\n", nl)
    return [begin + nl, body_nl + nl, end + nl]


def execute_change(ctx, spec):
    """Apply one planned change under the project-private ledger + manifest."""
    abs_target = spec["abs"]
    begin, end = spec["begin"], spec["end"]
    cid = spec["cid_key"]

    # Re-confirm hard guards at apply time (state may have changed since plan).
    guard_target(spec["checkout"], spec["rel"])
    if context_io.fingerprint(abs_target) != spec.get("observed_hash"):
        raise RuntimeError("target drifted since plan")

    # Read bytes now: validates UTF-8 and captures the file's newline style so
    # we never re-serialize CRLF/other endings into bare \n (F1/F2).
    existing, nl = _read_for_edit(abs_target)
    before = existing

    # Foreign-edit guard: a managed block that exists but no longer matches what
    # WE last wrote was touched by someone else. Refuse (fail-closed; no force).
    if spec.get("current") is not None:
        reason = env.overwrite_guard(ctx, cid, abs_target, spec["current"])
        if reason:
            raise RuntimeError(reason)

    if spec["kind"] == "remove":
        # Reverse exactly what upsert wrote: the span, plus the single blank
        # line upsert inserted after END when it placed the block before a
        # table. That flag is read from the ledger we recorded at upsert time;
        # we never delete a blank line we did not insert.
        prior = ctx.state.get("components", {}).get(cid, {})
        was_blank_after = bool(prior.get("inserted_blank_after"))
        entry = ctx.backup_save(abs_target, component=cid, kind="config_block",
                                block={"begin": begin, "end": end,
                                       "previous_body": spec["current"],
                                       "inserted_blank_after": was_blank_after,
                                       "applied_body": spec["current"]})
        lines = existing.splitlines(keepends=True)
        b = next(i for i, l in enumerate(lines) if l.strip() == begin)
        e = next(i for i, l in enumerate(lines) if l.strip() == end)
        end_line = e
        if was_blank_after and e + 1 < len(lines) and lines[e + 1].strip() == "":
            end_line = e + 1  # also drop the blank we inserted after END
        del lines[b:end_line + 1]
        new_text = "".join(lines)
        validate_toml(new_text, spec["rel"])
        context_io.atomic_write(abs_target, new_text, spec["observed_hash"])
        ctx.backup.mark_written(entry)
        ctx.last_write_digest = env.sha256_text(new_text)
        ctx.state.get("components", {}).pop(cid, None)
        return

    # upsert (insert or update).
    lines = existing.splitlines(keepends=True)
    block_lines = _build_block_lines(begin, spec["body"], end, nl)
    inserted_blank_after = False

    b = next((i for i, l in enumerate(lines) if l.strip() == begin), None)
    if b is not None:
        e = next(i for i, l in enumerate(lines) if l.strip() == end)
        new_lines = lines[:b] + block_lines + lines[e + 1:]
    else:
        hit = _detect_table_line(lines)
        if hit is not None:
            # Insert before the first table header; add one blank line after the
            # block and record it so restore removes exactly that one.
            new_lines = lines[:hit] + block_lines + [nl] + lines[hit:]
            inserted_blank_after = True
        else:
            # Append at EOF. Ensure exactly one separator newline before the block.
            if lines and not lines[-1].endswith(nl):
                lines[-1] = lines[-1] + nl
            new_lines = lines + block_lines
    new_text = "".join(new_lines)

    note = validate_toml(new_text, spec["rel"])

    entry = ctx.backup_save(abs_target, component=cid, kind="config_block",
                            block={"begin": begin, "end": end,
                                   "previous_body": spec["current"],
                                   "inserted_blank_after": inserted_blank_after,
                                   "applied_body": None})
    context_io.atomic_write(abs_target, new_text, spec["observed_hash"])
    ctx.backup.mark_written(entry)
    ctx.last_write_digest = env.sha256_text(new_text)
    ctx.record(cid, {
        "path": abs_target,
        "client": spec.get("client"),
        "mid": spec["mid"],
        "profile": spec.get("profile"),
        "sha256_after_apply": env.sha256_text(spec["body"]),
        "toml_note": note,
        "inserted_blank_after": inserted_blank_after,
        "owner": "setup-aiwb",
    })


# --------------------------------------------------------------------------
# Trust governance: ensure [projects."<abs>"] trust_level="trusted" in the
# USER-LEVEL global config. Permission only; additive this round (never removes).
# --------------------------------------------------------------------------

def _project_table_header(abs_path):
    return '[projects.%s]' % json.dumps(abs_path, ensure_ascii=False)


def trust_status(text, abs_path):
    """Classify the current config for this project:
    'trusted' (idempotent, no change) | 'add' (no table / no trust_level key) |
    'blocked:<value>' (explicit untrusted / non-standard value -> refuse)."""
    parser = load_toml_parser()
    if parser is None:
        raise RuntimeError("TOML parser required")
    validate_toml(text, "global trust config")
    table = parser.loads(text).get("projects", {}).get(abs_path)
    if table is None or "trust_level" not in table:
        return "add"
    val = table["trust_level"]
    return "trusted" if val == "trusted" else "blocked:%s" % val


def ensure_trust(text, nl, abs_path):
    """Return (new_text, changed). Fail-closed on explicit non-trusted value."""
    status = trust_status(text, abs_path)
    if status.startswith("blocked"):
        raise RuntimeError("existing trust_level %s; refusing to overwrite (no "
                           "overwrite authorization this round)"
                           % status.split(":", 1)[1])
    if status == "trusted":
        return text, False
    header = _project_table_header(abs_path)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == header:
            lines.insert(i + 1, 'trust_level = "trusted"' + nl)
            return "".join(lines), True
    if lines and not lines[-1].endswith(nl):
        lines[-1] = lines[-1] + nl
    block = [nl, header + nl, 'trust_level = "trusted"' + nl]
    return "".join(lines + block), True


def _realpath(p):
    rp = os.path.realpath(p)
    if not os.path.exists(rp):
        raise RuntimeError("repo/worktree does not exist: %s" % p)
    return rp


def build_trust_plan(repo, clients, worktrees, manage_trust):
    """Read current user config; return (changes, blocked, cleanups).
    Identity, trust-table key, cid and ledger all use the resolved realpath.
    Already-trusted produces no change; explicit untrusted/non-standard is
    blocked. cleanups lists OLD alias tables (e.g. /home/... path) that point at
    the SAME realpath and were previously added by us — provenance-gated."""
    changes, blocked, cleanups = [], [], []
    if not manage_trust:
        return changes, blocked, cleanups
    try:
        checkouts = [_realpath(repo)] + [_realpath(w) for w in worktrees]
    except (OSError, RuntimeError) as exc:
        blocked.append(("trust::repo", "cannot resolve realpath: %s" % exc))
        return changes, blocked, cleanups
    for client in clients:
        glob = os.path.join(os.path.realpath(os.path.expanduser("~")), GLOBAL_TRUST_CONFIG[client][2:])
        for ck in checkouts:
            cid = "trust::%s::%s" % (client, ck)
            if os.path.islink(glob):
                blocked.append((cid, "symlink global config"))
                continue
            try:
                context_io.guard(glob)
                before, _nl = _read_for_edit(glob)
                validate_toml(before, glob)
            except RuntimeError as exc:
                blocked.append((cid, str(exc)))
                continue
            status = trust_status(before, ck)
            if status == "trusted":
                pass  # idempotent; realpath key present
            elif status.startswith("blocked"):
                blocked.append((cid, "existing trust_level %s"
                                % status.split(":", 1)[1]))
            else:
                changes.append((cid, {"kind": "trust", "client": client,
                                      "global": glob, "abs": ck}))
            # legacy alias cleanup: an old alias project table (different path)
            # that is trusted but NOT this realpath -> scoped removal candidate.
            for alias in _alias_tables(before, ck):
                cleanups.append((cid + "::cleanup", {
                    "kind": "trust-cleanup", "client": client, "global": glob,
                    "abs": ck, "alias": alias}))
    return changes, blocked, cleanups


def _alias_tables(text, real_ck):
    """Return project-table paths that equal real_ck after resolving, or are
    legacy /home aliases of it. This read-only helper lists candidates; removal
    is further gated by ledger/backup proof at apply time."""
    import re
    out = []
    for m in re.finditer(r'^\s*\[projects\."([^"]+)"\]\s*$', text, re.M):
        p = m.group(1)
        if p == real_ck:
            continue
        try:
            if os.path.realpath(p) == os.path.realpath(real_ck):
                out.append(p)
        except OSError:
            continue
    return out


def execute_trust(ctx, spec):
    glob = spec["global"]
    abs_ck = spec["abs"]
    if os.path.islink(glob):
        raise RuntimeError("refusing symlink global config: " + glob)
    context_io.guard(glob)
    observed = context_io.fingerprint(glob)
    before, nl = _read_for_edit(glob)
    new_text, changed = ensure_trust(before, nl, abs_ck)
    if not changed:
        return
    entry = ctx.backup_save(glob, component="trust::%s::%s" % (spec["client"], abs_ck), kind="trust",
                            block={"begin": _project_table_header(abs_ck),
                                   "end": 'trust_level = "trusted"',
                                   "path": abs_ck, "trust_level": "trusted",
                                   "table_before": _trust_table(before, abs_ck),
                                   "table_after": _trust_table(new_text, abs_ck)})
    validate_toml(new_text, glob)
    context_io.atomic_write(glob, new_text, observed)
    ctx.backup.mark_written(entry)
    ctx.record("trust::%s::%s" % (spec["client"], abs_ck), {
        "client": spec["client"], "project_abs": abs_ck,
        "trust_level": "trusted", "owner": "setup-aiwb",
    })


def execute_trust_cleanup(ctx, spec):
    """Delete a legacy alias project table ONLY if we can prove from the ledger
    that THIS tool added it for this same realpath. Never touches user's
    pre-existing / untrusted / non-alias tables. Backup + ledger recorded."""
    glob = spec["global"]
    real_ck, alias = spec["abs"], spec["alias"]
    if os.path.islink(glob):
        raise RuntimeError("refusing symlink global config: " + glob)
    context_io.guard(glob)
    observed = context_io.fingerprint(glob)
    before, nl = _read_for_edit(glob)
    # provenance gate: ledger must show we wrote the alias path
    wrote_alias = any(
        v.get("project_abs") == alias and v.get("trust_level") == "trusted"
        for v in ctx.state.get("components", {}).values()
    )
    if not wrote_alias:
        return  # not ours -> leave user data untouched
    header = '[projects."%s"]' % alias
    lines = before.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if l.strip() == header), None)
    if idx is None:
        return
    # never remove an untrusted/non-trusted alias
    j = idx + 1
    while j < len(lines) and not TABLE_HEADER_RE.match(lines[j].strip()):
        if lines[j].strip().startswith("trust_level") and \
                '"trusted"' not in lines[j] and "'trusted'" not in lines[j]:
            return
        j += 1
    owned_table = load_toml_parser().loads(before).get("projects", {}).get(alias, {})
    if set(owned_table) != {"trust_level"} or owned_table.get("trust_level") != "trusted":
        raise RuntimeError("alias table has unrelated fields; refusing whole-table cleanup")
    entry = ctx.backup_save(glob, component="trust-cleanup::%s" % alias,
                            kind="trust", block={"begin": header,
                                                 "end": header,
                                                 "alias": alias, "real": real_ck,
                                                 "path": alias,
                                                 "table_before": _trust_table(before, alias),
                                                 "table_after": ""})
    del lines[idx:j]
    new_text = "".join(lines)
    validate_toml(new_text, glob)
    context_io.atomic_write(glob, new_text, observed)
    ctx.backup.mark_written(entry)
    ctx.record("trust-cleanup::%s" % alias, {"path": glob, "owner": "setup-aiwb"})


def _atomic_write(path, text):
    context_io.atomic_write(path, text)


# --------------------------------------------------------------------------
# Restore (reuse env's block-level restore against the project backup root)
# --------------------------------------------------------------------------

def backups_root(repo):
    return os.path.join(state_dir(repo), "backups")


def cmd_restore(repo, backup, dry_run, force):
    import context_restore
    return context_restore.restore(sys.modules[__name__], repo, backup, dry_run, force)


def _trust_table(text, key):
    header = _project_table_header(key)
    lines = text.splitlines(keepends=True)
    start = next((i for i,l in enumerate(lines) if l.strip()==header), None)
    if start is None:
        return ""
    stop=start+1
    while stop<len(lines) and not TABLE_HEADER_RE.match(lines[stop].strip()):
        stop+=1
    while stop>start+1 and not lines[stop-1].strip():
        stop-=1
    return "".join(lines[start:stop])


def _replace_trust_table(text,key,table):
    old=_trust_table(text,key)
    if old:
        return text.replace(old,table,1)
    return text + ("\n" if text and not text.endswith("\n") else "") + table


# --------------------------------------------------------------------------
# Declaration / schema
# --------------------------------------------------------------------------

def load_declaration(path):
    if not path:
        return {}
    if not os.path.isfile(path):
        env.die("声明文件不存在：%s" % path)
    try:
        return json.loads(env.read_text(path))
    except ValueError as exc:
        env.die("声明不是合法 JSON：%s (%s)" % (path, exc))


def check_declaration(decl, profile):
    import context_declaration
    clients = context_declaration.validate(decl, CLIENTS)
    return clients, []


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(prog="project_context.py",
                                description="render managed developer_instructions blocks")
    p.add_argument("--repo", default=REPO_ROOT_DEFAULT)
    p.add_argument("--declaration", help="path to .aiwb/project-context.json")
    p.add_argument("--profile", choices=PROFILES, default=None,
                   help="none | project | owned-full | legacy-only (overrides declaration)")
    p.add_argument("--worktree", action="append", default=[],
                   help="enumerated extra checkout; repeatable. We never auto-scan.")
    p.add_argument("--client", action="append", choices=sorted(CLIENTS),
                   help="restrict to these clients")
    p.add_argument("--manage-trust", dest="manage_trust", action="store_true",
                   default=None, help="ensure user-level project trust_level=trusted")
    p.add_argument("--no-manage-trust", dest="manage_trust", action="store_false",
                   help="disable trust management")
    p.add_argument("--pin", default=DEFAULT_PIN, help="AIWB source pin recorded in block")
    p.add_argument("--workenv", default=None, help="workenv reference recorded in block")
    p.add_argument("--apply", action="store_true", help="actually write (default = plan only)")
    p.add_argument("--check", action="store_true", help="assert no drift; rc!=1 on drift")
    p.add_argument("--force", action="store_true",
                   help="restore-only override of stale-backup guard; it does NOT "
                        "bypass foreign-edit fail-closed (user-edited managed blocks "
                        "are always refused)")
    p.add_argument("--restore", metavar="BACKUP", help="restore a snapshot by ts")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def _main(argv):
    args = parse_args(argv)
    repo = os.path.realpath(args.repo)

    if args.restore:
        return cmd_restore(repo, args.restore, args.dry_run, args.force)

    declaration_path = args.declaration or os.environ.get("AIWB_PROJECT_DECLARATION")
    local = os.path.join(repo, ".aiwb", "project-context.json")
    if not declaration_path and os.path.isfile(local):
        declaration_path = local
    decl = load_declaration(declaration_path)
    profile = args.profile
    if profile is None:
        profile = "project" if decl else "none"
    clients, notes = check_declaration(decl, profile)
    if args.client:
        requested = set(args.client)
        allowed = set(clients)
        extra = requested - allowed
        if extra:
            # F4: a client not in the declaration's allowed set is refused,
            # never silently extended.
            raise RuntimeError(
                "client(s) %s not declared allowed (%s); refusing"
                % (sorted(extra), sorted(allowed)))
        clients = sorted(requested)
    workenv = args.workenv or profile

    import context_declaration
    rules = context_declaration.rule_text(decl, profile, repo) if profile != "none" else None
    plan = build_plan(repo, profile, args.pin, workenv, clients, args.worktree, rules)

    # Only an explicit runtime flag authorizes mutation of global trust. A
    # project declaration may request trust but cannot grant its own permission.
    manage_trust = args.manage_trust is True
    trust_changes, trust_blocked, trust_cleanups = build_trust_plan(
        repo, clients, args.worktree, manage_trust)

    print("repo=%s profile=%s clients=%s trust=%s"
          % (repo, profile, ",".join(clients), manage_trust))
    for cid, text in plan["notes"]:
        print("  = %s: %s" % (cid, text))
    for cid, text in plan["blocked"]:
        print("  ! %s: %s" % (cid, text))
    for cid, text in trust_blocked:
        print("  ! %s: %s" % (cid, text))
    for cid, summary, spec in plan["changes"]:
        spec["cid_key"] = cid
        print("  ~ %s: %s" % (cid, summary))
    for cid, spec in trust_changes:
        spec["cid_key"] = cid
        print("  ~ %s: ensure project trust (realpath)" % cid)
    for cid, spec in trust_cleanups:
        spec["cid_key"] = cid
        print("  ~ %s: cleanup legacy alias table %s" % (cid, spec["alias"]))

    if args.check:
        if (plan["changes"] or plan["blocked"] or trust_changes
                or trust_blocked or trust_cleanups):
            print("结论：有漂移 ✗ (changes=%d blocked=%d trust=%d trustblocked=%d cleanup=%d)"
                  % (len(plan["changes"]), len(plan["blocked"]),
                     len(trust_changes), len(trust_blocked),
                     len(trust_cleanups)))
            return 1
        print("结论：与目标一致 ✓")
        return 0

    if not args.apply:
        print("（plan only；加 --apply 才会写入）changes=%d blocked=%d trust=%d trustblocked=%d"
              % (len(plan["changes"]), len(plan["blocked"]),
                 len(trust_changes), len(trust_blocked)))
        return 0 if not (plan["blocked"] or trust_blocked) else 1

    if plan["blocked"] or trust_blocked:
        print("blocked preflight: no target/ledger writes performed")
        return 1
    if args.dry_run:
        return 0
    if not plan["changes"] and not trust_changes and not trust_cleanups:
        return 0
    ctx = Ctx(repo, force=args.force)
    exit_code = 0
    for cid, summary, spec in plan["changes"]:
        spec["cid_key"] = cid
        try:
            execute_change(ctx, spec)
            for next_cid, _summary, next_spec in plan["changes"]:
                if next_spec["abs"] == spec["abs"]:
                    next_spec["observed_hash"] = ctx.last_write_digest
            print("  ✓ %s applied" % cid)
        except RuntimeError as exc:
            print("  ✗ %s 中止：%s" % (cid, exc))
            save_state(repo, ctx.state)
            return 1
    for cid, spec in trust_changes:
        spec["cid_key"] = cid
        try:
            execute_trust(ctx, spec)
            print("  ✓ %s trust ensured" % cid)
        except RuntimeError as exc:
            print("  ✗ %s trust 中止：%s" % (cid, exc))
            save_state(repo, ctx.state)
            return 1
    for cid, spec in trust_cleanups:
        spec["cid_key"] = cid
        try:
            execute_trust_cleanup(ctx, spec)
            print("  ✓ %s alias cleaned" % cid)
        except RuntimeError as exc:
            print("  ✗ %s cleanup 中止：%s" % (cid, exc))
            save_state(repo, ctx.state)
            return 1
    save_state(repo, ctx.state)
    if ctx.backup.dir:
        print("备份：%s" % ctx.backup.dir)
    print("ledger：%s" % state_path(repo))
    total_blocked = len(plan["blocked"]) + len(trust_blocked)
    if total_blocked:
        print("有 %d 项被拦截未写" % total_blocked)
        return 1
    return 0


def main(argv):
    args = parse_args(argv)
    resources = [state_path(os.path.realpath(args.repo))]
    if args.restore:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', args.restore):
            raise RuntimeError("invalid backup name")
        manifest_path = os.path.join(backups_root(os.path.realpath(args.repo)), args.restore, "manifest.json")
        context_io.guard(manifest_path)
        manifest = json.loads(env.read_text(manifest_path))
        resources.extend(e["original_path"] for e in manifest["entries"])
    for ck in [args.repo] + args.worktree:
        resources.extend(os.path.join(os.path.realpath(ck), rel) for rel in CLIENTS.values())
    if args.manage_trust or args.restore:
        resources.extend(os.path.join(os.path.realpath(os.path.expanduser("~")), p[2:]) for p in GLOBAL_TRUST_CONFIG.values())
    # Locks do not configure trust or native context. Keep through replanning
    # and state flush so different repos sharing a trust file cannot lose data.
    with context_io.locks(resources):
        return _main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (RuntimeError, ValueError, OSError) as exc:
        sys.stderr.write("project-context refused: %s\n" % exc)
        sys.exit(1)
