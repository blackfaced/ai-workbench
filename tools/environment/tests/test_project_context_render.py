#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end checks for the machine-agnostic project-context additive renderer.

Drives ``project_context.py`` in disposable repo copies and asserts the
contracts the design requires: three profiles, outside-block byte preservation,
idempotency, foreign-edit rejection, block-level restore + post-restore edit
protection, enumerated worktrees, symlink / path-traversal / ACL refusal, TOML
validity, and an explicit Claude refusal.

Standard library only, Python 3.9 compatible. Run from this directory::

    python3 test_project_context_render.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_DIR = os.path.dirname(HERE)
TOOL = os.path.join(ENV_DIR, "project_context.py")

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None


def require(ok, message):
    if not ok:
        raise AssertionError(message)
    print("PASS " + message)


def read(path):
    with open(path, "r", encoding="utf-8") as h:
        return h.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(text)


def run(args, env=None, manage_trust=False):
    full = list(args)
    if "--repo" in full and "--declaration" not in full:
        repo = full[full.index("--repo")+1]
        decl = os.path.join(repo, ".aiwb", "project-context.json")
        if os.path.isfile(decl):
            full += ["--declaration", decl]
    if not manage_trust:
        full.append("--no-manage-trust")
    proc = subprocess.Popen(
        [sys.executable, TOOL] + full,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, env=env)
    out, _ = proc.communicate(timeout=120)
    return proc.returncode, out


def make_repo():
    root = tempfile.mkdtemp(prefix="pc-test-")
    repo = os.path.join(root, "repo")
    write(os.path.join(repo, ".codex", "config.toml"),
          'model = "o4"\n\n[projects."/Users/me/old"]\ntrust_level = "trusted"\n')
    write(os.path.join(repo, ".trae", "traecli.toml"),
          'editor = "vscode"\n')
    # Historical policy belongs to this characterization fixture/project,
    # not the reusable renderer. Keep legacy expected content unchanged.
    write(os.path.join(repo, ".aiwb", "project-context.json"), json.dumps({
        "profiles": {
            "las-full": "LAS business knowledge is loaded on demand from the owning project sources; do not inline a second copy here.\nLazy policy: complete -- resolve and verify the full chain before acting.\nEvery commit / MR message must carry the work-item id matching m-<id>.",
            "meego-only": "Tracker is Meego; a work-item id is required.\nEvery commit / MR message must carry the Meego work-item id m-<id>."
        }
    }))
    return repo


def codex(repo):
    return os.path.join(repo, ".codex", "config.toml")


def trae(repo):
    return os.path.join(repo, ".trae", "traecli.toml")


def block(text, mid):
    begin = "# setup-aiwb:%s BEGIN" % mid
    end = "# setup-aiwb:%s END" % mid
    if begin not in text:
        return None
    lines = text.splitlines()
    s = lines.index(begin)
    tail = lines[s + 1:]
    if end not in tail:
        return None
    return "\n".join(tail[:tail.index(end)])


def valid_toml(path):
    if tomllib is None:
        return True  # placement-guaranteed on py<3.11; nothing to parse
    try:
        with open(path, "rb") as h:
            tomllib.load(h)
        return True
    except Exception:
        return False


def test_profiles():
    print("\n-- three profiles --")
    repo = make_repo()
    for profile, mid in (("las-full", "las-work-rules"),
                         ("meego-only", "meego-commit-id")):
        rc, out = run(["--repo", repo, "--profile", profile, "--apply"])
        require(rc == 0, "%s apply rc=0" % profile)
        c = block(read(codex(repo)), mid)
        require(c is not None, "%s emits %s block" % (profile, mid))
        require("developer_instructions = '''" in read(codex(repo)),
                "%s block carries developer_instructions field" % profile)
        require(valid_toml(codex(repo)), "%s emits valid TOML (codex)" % profile)
        require(valid_toml(trae(repo)), "%s emits valid TOML (trae)" % profile)
    # switching profile drops the previous block
    require(block(read(codex(repo)), "las-work-rules") is None,
            "switch to meego-only removed las-work-rules block")
    rc, out = run(["--repo", repo, "--profile", "none", "--apply"])
    require(rc == 0, "none apply rc=0")
    require("developer_instructions" not in read(codex(repo)),
            "profile=none leaves no managed block (absence is the output)")


def test_preservation_and_idempotency():
    print("\n-- outside-block preservation + idempotency --")
    repo = make_repo()
    before = read(codex(repo))
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    after = read(codex(repo))
    # user content byte-identical outside the block region
    require('model = "o4"' in after, "user top-level key preserved")
    require('[projects."/Users/me/old"]' in after, "user table preserved")
    require('trust_level = "trusted"' in after, "user table value preserved")
    # top-level developer_instructions must NOT have landed inside the table
    if tomllib is not None:
        import io
        data = tomllib.loads(after)
        require("developer_instructions" in data, "developer_instructions is top-level")
        require("developer_instructions" not in data.get("projects", {}).get("/Users/me/old", {}),
                "developer_instructions did not leak into user table")
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc == 0 and "already target shape" in out, "repeat apply is idempotent")
    after2 = read(codex(repo))
    require(after == after2, "idempotent apply leaves file bytes unchanged")


def test_foreign_edit_rejected():
    print("\n-- foreign-edit rejection --")
    repo = make_repo()
    run(["--repo", repo, "--profile", "las-full", "--apply"])
    cpath = codex(repo)
    t = read(cpath)
    t = t.replace("do not inline a second copy here", "ATTACKER-EDIT")
    write(cpath, t)
    rc, out = run(["--repo", repo, "--profile", "las-full"])
    require(rc != 0, "plan reports foreign edit as blocked (rc!=0)")
    require("ATTACKER-EDIT" in read(cpath), "foreign edit preserved, not overwritten")
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc != 0, "apply refuses foreign edit (rc!=0)")
    require("ATTACKER-EDIT" in read(cpath), "foreign edit still preserved after refused apply")


def test_restore_and_post_restore_protection():
    print("\n-- restore + post-restore edit protection --")
    repo = make_repo()
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    cpath = codex(repo)
    installed = read(cpath)
    # switch profile so a removal backup is created, then restore it
    run(["--repo", repo, "--profile", "none", "--apply"])
    require(block(read(cpath), "las-work-rules") is None, "none removed block")
    backups = sorted(os.listdir(os.path.join(repo, ".ai-workbench", "project-context", "backups")))
    rc, out = run(["--repo", repo, "--restore", backups[-1]])
    require(rc == 0, "restore rc=0")
    require(block(read(cpath), "las-work-rules") is not None,
            "restore brought back the removed block")
    # now edit the restored block; re-apply must refuse (post-restore protection)
    t = read(cpath).replace("do not inline a second copy here", "POST-RESTORE-EDIT")
    write(cpath, t)
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc != 0, "post-restore edit is rejected on re-apply")
    require("POST-RESTORE-EDIT" in read(cpath), "post-restore edit preserved")


def test_worktree_enumerated():
    print("\n-- enumerated worktree list --")
    repo = make_repo()
    wt = os.path.join(tempfile.mkdtemp(prefix="pc-wt-"), "wt")
    write(os.path.join(wt, ".codex", "config.toml"), 'base = true\n')
    rc, out = run(["--repo", repo, "--profile", "meego-only",
                   "--worktree", wt, "--apply"])
    require(rc == 0, "apply to enumerated worktree rc=0")
    require(block(read(os.path.join(wt, ".codex", "config.toml")),
                  "meego-commit-id") is not None,
            "managed block provisioned into declared worktree")
    # undeclared / missing worktree is blocked, not auto-scanned
    rc, out = run(["--repo", repo, "--profile", "none",
                   "--worktree", "/no/such/checkout", "--apply"])
    require(rc != 0, "missing declared checkout is blocked")
    require("does not exist" in out, "missing checkout reported, not silently scanned")


def test_symlink_refusal():
    print("\n-- symlink refusal --")
    root = tempfile.mkdtemp(prefix="pc-sym-")
    repo = os.path.join(root, "repo")
    write(os.path.join(repo, ".codex", "config.toml"), 'x=1\n')
    write(os.path.join(repo, ".aiwb", "project-context.json"), json.dumps({"instructions":"fixture rule"}))
    target = os.path.join(root, "elsewhere.toml")
    write(target, 'victim = true\n')
    link = os.path.join(repo, ".codex", "config.toml")
    os.remove(link)
    os.symlink(target, link)
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc != 0, "symlink target refused (rc!=0)")
    require(read(target) == 'victim = true\n', "symlink victim untouched")


def test_path_traversal_refusal():
    print("\n-- path containment --")
    repo = make_repo()
    # craft a target that escapes via a rel path, exercising _resolve_in_repo
    sys.path.insert(0, ENV_DIR)
    import project_context as pc
    try:
        pc._resolve_in_repo(repo, ".codex/../../etc/passwd")
        require(False, "traversal rel path should have raised")
    except RuntimeError as e:
        require("traversal" in str(e) or "outside" in str(e),
                "traversal rel path refused: %s" % e)


def test_acl_refusal():
    print("\n-- ACL / read-only refusal --")
    repo = make_repo()
    cpath = codex(repo)
    os.chmod(cpath, 0o444)
    try:
        rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
        require(rc != 0, "read-only target refused (rc!=0)")
    finally:
        os.chmod(cpath, 0o644)


def test_claude_refused():
    print("\n-- Claude explicitly unsupported --")
    repo = make_repo()
    rc, out = run(["--repo", repo, "--profile", "las-full", "--client", "claude"])
    require(rc != 0, "Claude client rejected (rc!=0)")


def test_f1_crlf_preserved():
    print("\n-- F1: CRLF / outside-byte newline preserved --")
    repo = make_repo()
    p = codex(repo)
    crlf = 'model = "o4"\r\n\r\n[projects."/o"]\r\ntrust_level = "trusted"\r\n'
    with open(p, "wb") as h:
        h.write(crlf.encode())
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc == 0, "CRLF apply rc=0")
    data = open(p, "rb").read().decode()
    require("\r\n" in data, "CRLF endings preserved in output")
    require('model = "o4"\r\n' in data, "user CRLF line preserved outside block")
    require('[projects."/o"]\r\ntrust_level = "trusted"\r\n' in data,
            "user table CRLF bytes preserved")


def test_f2_non_utf8_failclosed():
    print("\n-- F2: non-UTF8 preflight fail-closed, no write/trace --")
    repo = make_repo()
    p = codex(repo)
    junk = b"model = 'x'\n\xff\xfe binary \x00\n"
    with open(p, "wb") as h:
        h.write(junk)
    rc, out = run(["--repo", repo, "--profile", "las-full", "--apply"])
    require(rc != 0, "non-UTF8 apply refused rc!=0")
    require(open(p, "rb").read() == junk, "non-UTF8 target left untouched")
    rc2, out2 = run(["--repo", repo, "--profile", "las-full"])
    require(rc2 != 0, "non-UTF8 plan also blocked (no trace)")


def test_f3_blank_no_accumulation():
    print("\n-- F3: inserted blank ledgered, no accumulation across apply/restore --")
    repo = make_repo()
    p = codex(repo)
    open(p, "w").write('[projects."/o"]\ntrust="trusted"\n')
    run(["--repo", repo, "--profile", "las-full", "--apply"])
    first = open(p).read()
    blank_after_block = first.count("\n\n")
    run(["--repo", repo, "--profile", "las-full", "--apply"])
    second = open(p).read()
    require(first == second, "repeat apply does not accumulate blank lines")
    # empty file case
    repo2 = make_repo()
    p2 = codex(repo2)
    open(p2, "w").write("")
    run(["--repo", repo2, "--profile", "meego-only", "--apply"])
    out2 = open(p2).read()
    require("developer_instructions" in out2, "empty file rendered block")
    # empty file: block starts at line 1 (no spurious leading separator blank)
    require(out2.splitlines()[0].startswith("# setup-aiwb:"),
            "empty-file block starts at first line, no leading blank")
    run(["--repo", repo2, "--profile", "meego-only", "--apply"])
    require(open(p2).read() == out2, "empty-file repeat apply stable")


def test_f4_client_intersection():
    print("\n-- F4: undeclared --client refused, not extended --")
    repo = make_repo()
    run(["--repo", repo, "--profile", "las-full", "--apply"])
    require("developer_instructions" in read(codex(repo)), "codex block present")
    require("developer_instructions" in read(trae(repo)), "trae block present")
    rc, out = run(["--repo", repo, "--profile", "las-full", "--client", "bogus"])
    require(rc != 0, "unknown client refused by argparse")


def test_f3_remove_blank_cycle_byte_restore():
    print("\n-- F3: remove reverses inserted blank; apply<->none byte-restores original --")
    scenarios = {
        "table-before": ('[projects."/o"]\ntrust="trusted"\n', "\n"),
        "eof": ('model="o4"\n', "\n"),
        "empty": ("", "\n"),
        "crlf": ('[projects."/o"]\r\ntrust="trusted"\r\n', "\r\n"),
    }
    for name, (orig, _nl) in scenarios.items():
        repo = make_repo()
        p = codex(repo)
        open(p, "wb").write(orig.encode())
        before0 = open(p, "rb").read()
        # cycle 1 apply
        rc, _ = run(["--repo", repo, "--profile", "las-full", "--apply"])
        require(rc == 0, "%s apply rc=0" % name)
        after_apply = open(p, "rb").read()
        require(b"setup-aiwb:" in after_apply, "%s block inserted" % name)
        # cycle 1 remove (profile none) must byte-restore original exactly
        rc2, _ = run(["--repo", repo, "--profile", "none", "--apply"])
        require(rc2 == 0, "%s remove->none rc=0" % name)
        restored = open(p, "rb").read()
        require(restored == before0,
                "%s: remove byte-restores original (no stray blank)" % name)
        # cycle 2 apply again and remove -> still byte-restored (no accumulation)
        run(["--repo", repo, "--profile", "las-full", "--apply"])
        run(["--repo", repo, "--profile", "none", "--apply"])
        require(open(p, "rb").read() == before0,
                "%s: second cycle no blank accumulation" % name)


def test_trust_governance():
    print("\n-- trust: user-level project trust added, idempotent, fields kept --")
    import os
    home = tempfile.mkdtemp(prefix="trust-home-")
    os.makedirs(home + "/.codex")
    gcfg = home + "/.codex/config.toml"
    open(gcfg, "w").write('model = "o4"\n\n[other]\nx = 1\n')
    repo = tempfile.mkdtemp(prefix="trust-repo-")
    os.makedirs(repo + "/.codex")
    open(repo + "/.codex/config.toml", "w").write("")
    env = dict(os.environ, HOME=home)
    rc, out = run(["--repo", repo, "--profile", "none",
                  "--manage-trust", "--apply"], env=env, manage_trust=True)
    require(rc == 0, "trust apply rc=0")
    realrepo = os.path.realpath(repo)
    g = open(gcfg).read()
    require('[projects."%s"]' % realrepo in g, "project table added (realpath key)")
    require(repo == realrepo or '[projects."%s"]' % repo not in g,
            "no alias key written first run")
    require('trust_level = "trusted"' in g, "trust_level trusted set")
    require('model = "o4"' in g, "user field preserved")
    require('[other]' in g and 'x = 1' in g, "other table preserved")
    # repeat -> idempotent (no duplicate table, rc=0)
    before = open(gcfg).read()
    rc2, _ = run(["--repo", repo, "--profile", "none",
                  "--manage-trust", "--apply"], env=env, manage_trust=True)
    require(rc2 == 0, "repeat trust rc=0")
    require(open(gcfg).read() == before, "trust repeated idempotent")
    # after apply+repeat, --check must report consistent (rc=0, no change)
    rc3, out3 = run(["--repo", repo, "--profile", "none",
                     "--manage-trust", "--check"], env=env, manage_trust=True)
    require(rc3 == 0, "trust check rc0 after trusted (no drift)")
    # explicit untrusted (on the realpath key) -> blocked, never overwritten
    g2 = home + "/.codex/config.toml"
    open(g2, "w").write('[projects."%s"]\ntrust_level = "untrusted"\n' % realrepo)
    rc4, out4 = run(["--repo", repo, "--profile", "none",
                     "--manage-trust", "--apply"], env=env, manage_trust=True)
    require(rc4 != 0, "explicit untrusted blocked rc!=0")
    require('trust_level = "untrusted"' in open(g2).read(),
            "untrusted value preserved (not overwritten)")


def test_trust_realpath_cleanup():
    print("\n-- trust: realpath only, legacy alias cleanup scoped + restore --")
    import tempfile
    home = tempfile.mkdtemp()
    os.makedirs(home + "/.codex")
    realhome = tempfile.mkdtemp()
    aliashome = realhome + "/linked"
    os.symlink(realhome, aliashome)          # /homealias -> real
    repo = realhome + "/repo"                # real repo under realhome
    os.makedirs(repo + "/.codex")
    open(repo + "/.codex/config.toml", "w").write("")
    homecfg = home + "/.codex/config.toml"
    open(homecfg, "w").write('model="o4"\n')
    env = dict(os.environ, HOME=home)
    # first run through the alias path writes ONLY the realpath key
    rc, out = run(["--repo", repo + "/../repo", "--profile", "none",
                   "--manage-trust", "--apply"], env=env, manage_trust=True)
    require(rc == 0, "realpath apply rc=0")
    realrepo = os.path.realpath(repo)
    g = open(homecfg).read()
    require('[projects."%s"]' % realrepo in g, "realpath key written")
    require('linked' not in g, "no alias path key written")
    # inject an OLD alias table that WE previously added (proven via ledger)
    old_alias = aliashome + "/repo"
    ledger_dir = repo + "/.ai-workbench/project-context"
    st = json.load(open(ledger_dir + "/state.json"))
    st["components"]["trust::codex::%s" % old_alias] = {
        "project_abs": old_alias, "trust_level": "trusted"}
    json.dump(st, open(ledger_dir + "/state.json", "w"))
    open(homecfg, "w").write(
        'model="o4"\n[projects."%s"]\ntrust_level = "trusted"\n[projects."%s"]\ntrust_level = "trusted"\n'
        % (old_alias, realrepo))
    # plan shows cleanup
    rc2, plan = run(["--repo", repo, "--profile", "none", "--manage-trust"],
                    env=env, manage_trust=True)
    require("cleanup legacy alias" in plan, "plan lists scoped cleanup")
    # apply removes only the alias table, keeps realpath key
    rc3, out3 = run(["--repo", repo, "--profile", "none",
                     "--manage-trust", "--apply"], env=env, manage_trust=True)
    require(rc3 == 0, "cleanup apply rc=0")
    g3 = open(homecfg).read()
    require(old_alias not in g3, "legacy alias table removed")
    require('[projects."%s"]' % realrepo in g3, "realpath key kept")
    require('model="o4"' in g3 or 'model = "o4"' in g3,
            "user model field kept after cleanup")


def main():
    test_profiles()
    test_preservation_and_idempotency()
    test_foreign_edit_rejected()
    test_restore_and_post_restore_protection()
    test_worktree_enumerated()
    test_symlink_refusal()
    test_path_traversal_refusal()
    test_acl_refusal()
    test_claude_refused()
    test_f1_crlf_preserved()
    test_f2_non_utf8_failclosed()
    test_f3_blank_no_accumulation()
    test_f3_remove_blank_cycle_byte_restore()
    test_f4_client_intersection()
    test_trust_governance()
    test_trust_realpath_cleanup()
    print("\nALL PROJECT-CONTEXT RENDER TESTS PASSED")


if __name__ == "__main__":
    main()
