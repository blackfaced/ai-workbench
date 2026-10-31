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
import subprocess
import sys
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
    expected = (SOURCE / "SKILL.md").read_text()
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
    for relative in ("references/project-context.md", "references/integration-setup.md",
                     "references/error-observability.md"):
        old["clients"]["shared"]["files"].pop(relative)
    # Keep the historical split format explicit in this upgrade fixture.
    old["clients"]["shared"]["frontmatter"] = "skills/setup-aiwb/legacy.frontmatter.md"
    box, installed = fixture(root / "upgrade", old)
    body = Path(box.repo) / "skills/setup-aiwb/SKILL.md"
    header = (SOURCE / "SKILL.md").read_text().split("---", 2)[1]
    body.with_name("legacy.frontmatter.md").write_text("---" + header + "---\n")
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
    for relative in ("references/project-context.md", "references/error-observability.md"):
        broken = copy.deepcopy(component("work-mac"))
        broken["clients"]["shared"]["files"].pop(relative)
        box, installed = fixture(root / ("missing-" + Path(relative).stem), broken)
        run(box, "apply")
        missing = missing_references(installed / "SKILL.md")
        require(missing == {(installed / relative).resolve()},
                "reference detector catches omitted " + relative + " even when apply succeeds")


def upstream_baseline_contract():
    body = (SOURCE / "SKILL.md").read_text()
    context = (SOURCE / "references/project-context.md").read_text()
    lock = json.loads((REPO / "skills/sources.lock.json").read_text())
    entries = {entry["name"]: entry for entry in lock["skills"]}
    upstream = entries["setup-matt-pocock-skills"]
    setup = entries["setup-aiwb"]
    require("resolve, validate and read the passive upstream dependency" in body
            and "Do not invoke it by Skill name" in body,
            "setup-aiwb reads the passive project dependency instead of invoking by name")
    require("references/matt-project-baseline.md" in body,
            "setup-aiwb reaches the fixed project dependency contract")
    dependency = (SOURCE / "references/matt-project-baseline.md").read_text()
    require("<project-root>/.agents/skills/setup-matt-pocock-skills/SKILL.md" in dependency,
            "dependency contract names the only accepted project entry")
    require("Do not search user-global discovery directories" in dependency
            and "No workspace manager or activation registry is required" in dependency
            and "a match to the pinned upstream Git tree does" in dependency,
            "contract allows standalone verification without global fallback")
    for required in ("agents/openai.yaml", "domain.md", "issue-tracker-github.md",
                     "issue-tracker-gitlab.md", "issue-tracker-local.md", "triage-labels.md"):
        require(required in dependency, "dependency contract requires " + required)
    require("Continue only independent requests such as a guide-only update" in body,
            "a missing project dependency blocks only dependent setup")
    require("docs/agents/issue-tracker.md" in context and "docs/agents/domain.md" in context,
            "project context reuses tracker and Domain Docs outputs")
    require(upstream["revision"] == "5c89081d4bbeb3d039a42093653f90bb698d780e"
            and upstream["tree_digest"] == "ec07f82df54064d01aa1648670e81da41e2cbdc2"
            and upstream["source_path"] == "skills/engineering/setup-matt-pocock-skills",
            "upstream setup source is pinned with its complete path and tree digest")
    require("`.agents/skills/setup-matt-pocock-skills/`" in upstream["note"]
            and "不回退用户全局同名副本" in upstream["note"],
            "source handoff preserves the project-only no-fallback contract")
    from test_matt_baseline import verifier
    require(verifier.SOURCE == {"repository": upstream["source"],
                              "commit": upstream["revision"],
                              "path": upstream["source_path"],
                              "tree": upstream["tree_digest"]},
            "bundled verifier pin matches the source registry")
    require("scripts/verify_matt_baseline.py" in dependency
            and "Prepare a missing package directly" in dependency
            and "git archive" in dependency,
            "standalone path includes a verifier and ordinary Git preparation")
    require(setup.get("depends_on") == ["setup-matt-pocock-skills"],
            "setup-aiwb declares the upstream setup dependency")
    for profile in ("work-mac", "work-linux", "home-mac"):
        entry = component(profile)
        require("install_with" not in entry,
                profile + " legacy profile does not take over project activation")
        require(entry["clients"]["shared"]["files"].get("references/matt-project-baseline.md")
                == "skills/setup-aiwb/references/matt-project-baseline.md",
                profile + " distributes the project dependency contract")
        require(entry["clients"]["shared"]["files"].get("scripts/verify_matt_baseline.py")
                == "skills/setup-aiwb/scripts/verify_matt_baseline.py",
                profile + " distributes the standalone verifier")


def main():
    upstream_baseline_contract()
    subprocess.run([sys.executable, str(Path(__file__).with_name("test_matt_baseline.py"))],
                   check=True)
    with tempfile.TemporaryDirectory(prefix="aiwb-setup-distribution-") as directory:
        root = Path(directory)
        for profile in ("work-mac", "work-linux", "home-mac"):
            fresh_install(root, profile)
        upgrade(root)
        missing_resource_control(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
