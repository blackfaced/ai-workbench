#!/usr/bin/env python3
"""Exercise setup-aiwb's installed resource graph and update/restore contract.

Uses real profile components and the public installer in disposable HOME/source
copies. Native client loading requires the separate project pilot; these checks
do not replace that evidence. Standard library only, Python 3.9 compatible.
"""

import copy
import json
from pathlib import Path
import re
import shutil
import tempfile

from regression import ENV_DIR, Sandbox, base_profile


REPO = Path(ENV_DIR).parent.parent
SOURCE = REPO / "skills/setup-aiwb"


def require(ok, message):
    if not ok:
        raise AssertionError(message)
    print("PASS " + message)


def component(profile):
    data = json.loads((Path(ENV_DIR) / "profiles" / (profile + ".json")).read_text())
    return next(c for c in data["components"] if c["id"] == "setup-aiwb")


def fixture(root, entry):
    box = Sandbox(str(root))
    shutil.copytree(SOURCE, Path(box.repo) / "skills/setup-aiwb")
    box.profile(base_profile([entry]))
    return box, Path(box.path(".agents", "skills", "setup-aiwb"))


def run(box, action, expected=0, *extra):
    rc, output = box.run(action, "--profile", "harness", "--only", "setup-aiwb", *extra)
    require(rc == expected, action + " exit=" + str(expected) + ("\n" + output if rc != expected else ""))


def missing_references(entry):
    """Follow installed Markdown references, including second-level guide links."""
    seen, missing, pending = set(), set(), [entry]
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            missing.add(path)
            continue
        if path.suffix != ".md":
            continue
        for link in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text()):
            if not re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", link):
                pending.append(path.parent / link)
    return missing


def fresh_install(root, profile):
    entry = component(profile)
    box, installed = fixture(root / profile, entry)
    run(box, "plan")
    require(not installed.exists(), profile + " plan leaves HOME unchanged")
    run(box, "apply")
    expected = ((SOURCE / "clients/shared.frontmatter.md").read_text().rstrip("\n")
                + "\n\n" + (SOURCE / "SKILL.md").read_text().lstrip("\n"))
    require((installed / "SKILL.md").read_text() == expected, profile + " rendered entry matches source")
    missing = missing_references(installed / "SKILL.md")
    require(not missing, profile + " installed reference graph is readable: " + str(sorted(map(str, missing))))
    for relative, source in entry["clients"]["shared"]["files"].items():
        require((installed / relative).read_bytes() == (REPO / source).read_bytes(), profile + " distributes " + relative)
    run(box, "check")
    backup, state = box.latest_backup(), box.state()
    run(box, "apply")
    require(state == box.state(), profile + " repeated apply is idempotent")
    note = installed / "owner-note.md"
    note.write_text("Keep this user-owned note.\n")
    rc, output = box.run("restore", "--backup", backup)
    managed = ["SKILL.md"] + list(entry["clients"]["shared"]["files"])
    require(rc == 0 and all(not (installed / p).exists() for p in managed), profile + " restore removes managed files: " + (output if rc else ""))
    require(note.read_text() == "Keep this user-owned note.\n", profile + " restore preserves user files")
    run(box, "apply")
    private_guide = installed / "references/project-context.md"
    edited = private_guide.read_text() + "\nOwner's local amendment.\n"
    private_guide.write_text(edited)
    run(box, "apply", expected=1)
    require(private_guide.read_text() == edited, profile + " update protects user-modified reference")
    run(box, "check", expected=1)


def upgrade(root):
    current = component("work-mac")
    old = copy.deepcopy(current)
    for relative in ("references/project-context.md", "references/integration-setup.md"):
        old["clients"]["shared"]["files"].pop(relative)
    box, installed = fixture(root / "upgrade", old)
    body = Path(box.repo) / "skills/setup-aiwb/SKILL.md"
    original = (SOURCE / "references/integration-setup.md").read_text().replace(
        "(integration-guide.md)", "(references/integration-guide.md)")
    body.write_text(original)
    run(box, "apply")
    guide_before = (installed / "references/integration-guide.md").read_bytes()
    body.write_text((SOURCE / "SKILL.md").read_text())
    box.profile(base_profile([current]))
    run(box, "apply")
    run(box, "check")
    require(not missing_references(installed / "SKILL.md"), "old integration-only installation upgrades with readable references")
    require((installed / "references/integration-guide.md").read_bytes() == guide_before,
            "upgrade preserves the existing integration guide")
    require((installed / "references/integration-setup.md").read_text().replace(
        "(integration-guide.md)", "(references/integration-guide.md)") == original,
        "upgrade retains the previous integration instructions")


def missing_resource_control(root):
    broken = copy.deepcopy(component("work-mac"))
    broken["clients"]["shared"]["files"].pop("references/project-context.md")
    box, installed = fixture(root / "missing-resource", broken)
    run(box, "apply")
    missing = missing_references(installed / "SKILL.md")
    require(missing == {(installed / "references/project-context.md").resolve()},
            "reference detector catches omitted project guide even when apply succeeds")


def main():
    with tempfile.TemporaryDirectory(prefix="aiwb-setup-distribution-") as directory:
        root = Path(directory)
        for profile in ("work-mac", "work-linux", "home-mac"):
            fresh_install(root, profile)
        upgrade(root)
        missing_resource_control(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
