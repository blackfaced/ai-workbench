#!/usr/bin/env python3
"""Read-only verification of the project Matt package; no manager or network needed.

Git object hashing matches the pinned upstream tree, including file modes and
extra/missing files. This proves package content, not client loading or ownership
for later updates. Python 3.9+, standard library only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

SOURCE = {
    "repository": "https://github.com/mattpocock/skills",
    "commit": "5c89081d4bbeb3d039a42093653f90bb698d780e",
    "path": "skills/engineering/setup-matt-pocock-skills",
    "tree": "ec07f82df54064d01aa1648670e81da41e2cbdc2",
}
ENTRY = Path(".agents/skills/setup-matt-pocock-skills")


def object_id(kind, data):
    return hashlib.sha1(kind + b" " + str(len(data)).encode() + b"\0" + data).digest()


def tree_id(directory):
    entries = []
    for child in directory.iterdir():
        mode = child.lstat().st_mode
        name = os.fsencode(child.name)
        if stat.S_ISDIR(mode):
            entries.append((name + b"/", b"40000", name, tree_id(child)))
        elif stat.S_ISREG(mode):
            file_mode = b"100755" if mode & stat.S_IXUSR else b"100644"
            entries.append((name, file_mode, name, object_id(b"blob", child.read_bytes())))
        else:
            # This pinned package contains only regular files and directories.
            raise ValueError("package contains a symlink or non-regular file")
    content = b"".join(mode + b" " + name + b"\0" + digest
                       for _, mode, name, digest in sorted(entries))
    return object_id(b"tree", content)


def project_package(entry):
    """Resolve links without permitting an intermediate global discovery hop."""
    forbidden = set()
    for base in (".agents", ".codex", ".claude", ".trae"):
        path = Path.home() / base / "skills"
        forbidden.update((path, path.resolve()))
    path = entry
    for _ in range(40):
        if any(path == base or base in path.parents for base in forbidden):
            return None
        for prefix in (*reversed(path.parents), path):
            if prefix.is_symlink():
                target = Path(os.readlink(prefix))
                if not target.is_absolute():
                    target = prefix.parent / target
                path = Path(os.path.normpath(str(target / path.relative_to(prefix))))
                break
        else:
            return path.resolve(strict=True)
    raise ValueError("too many package symlinks")


def verify(project):
    root = Path(project).expanduser().resolve(strict=True)
    result = {"status": "BLOCKED", "source": SOURCE,
              "project_entry": str(root / ENTRY / "SKILL.md"), "writes": False}
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=10)
    if proc.returncode or Path(proc.stdout.strip()).resolve() != root or root == Path.home().resolve():
        return dict(result, code="INVALID_PROJECT_ROOT")
    entry = root / ENTRY
    if not entry.exists():
        return dict(result, code="PROJECT_DEPENDENCY_MISSING")
    package = project_package(entry)
    if package is None:
        return dict(result, code="GLOBAL_DEPENDENCY_REJECTED")
    result["resolved_package"] = str(package)
    if not package.is_dir() or not (package / "SKILL.md").is_file():
        return dict(result, code="PROJECT_DEPENDENCY_INCOMPLETE")
    actual = tree_id(package).hex()
    result["actual_tree"] = actual
    if actual != SOURCE["tree"]:
        return dict(result, code="DEPENDENCY_TREE_MISMATCH")
    return dict(result, status="PASS", code="PINNED_PROJECT_PACKAGE",
                verification="full Git tree: file names, bytes and modes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="exact target Git checkout root")
    args = parser.parse_args()
    try:
        result = verify(args.project)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result = {"status": "BLOCKED", "code": "DEPENDENCY_UNREADABLE",
                  "reason": type(error).__name__, "writes": False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
