#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#370 known-fault experiment at the legacy public installation entry.

    python3 tools/environment/tests/legacy_delegation_pilot.py
    python3 tools/environment/tests/legacy_delegation_pilot.py --fault --output /tmp/new-run

--fault exposes the detector's failure (exit 1); the default matrix expects it,
then requires a correct control and a fresh-HOME repeat (experiment exit 0).
Only isolated source copies are mutated. No model, network or real HOME writes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

from regression import ENV_DIR, Sandbox, base_profile, read, write


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observe(root, fault):
    repo = Path(ENV_DIR).parent.parent
    box = Sandbox(str(root / "sandbox"))
    names = ("implement-batch", "deliver-spec", "test-design", "self-test-report")
    profile = json.loads(read(os.path.join(ENV_DIR, "profiles", "work-mac.json")))
    components = [c for c in profile["components"] if c["id"] in names]
    for name in names:
        shutil.copytree(repo / "skills" / name, Path(box.repo) / "skills" / name)
    box.profile(base_profile(components))

    alias = Path(box.repo) / "skills/implement-batch/SKILL.md"
    before = alias.read_text(encoding="utf-8")
    principal = re.search(r"\]\(([^)#]+)\)", before)
    if principal is None:
        raise AssertionError("legacy entry has no principal delegation reference")
    original_target = principal.group(1)
    if fault:
        # One known typo only; remaining section-anchor links stay intact.
        after = before[:principal.start(1)] + "../absent-canonical/SKILL.md" + before[principal.end(1):]
        alias.write_text(after, encoding="utf-8")
    write(str(root / "source-alias.md"), read(str(alias)))

    apply_rc, apply_out = box.run("apply", "--profile", "harness", "--only", "implement-batch")
    write(str(root / "apply.log"), apply_out)
    check_rc, check_out = box.run("check", "--profile", "harness", "--only", "implement-batch")
    write(str(root / "check.log"), check_out)
    installed = Path(box.path(".agents", "skills", "implement-batch"))
    attachment = installed / "references/botmux.md"
    # Frozen observation semantics from 16bfd98 case_implement_batch_distribution.
    # Fixture loading includes the new companions; the old observer is unchanged.
    old = {
        "apply_rc_zero": apply_rc == 0,
        "botmux_bytes_equal": attachment.is_file() and attachment.read_bytes()
        == (repo / "skills/implement-batch/references/botmux.md").read_bytes(),
        "check_rc_zero": check_rc == 0,
    }
    entry = installed / "SKILL.md"
    links = re.findall(r"\]\(([^)#]+)\)", entry.read_text(encoding="utf-8")) if entry.is_file() else []
    target = (installed / links[0]).resolve() if links else None
    readable = target is not None and target.is_file()
    canonical = repo / "skills/deliver-spec"
    expected = (read(str(canonical / "clients/shared.frontmatter.md")).rstrip("\n")
                + "\n\n" + read(str(canonical / "SKILL.md")).lstrip("\n"))
    actual = target.read_text(encoding="utf-8") if readable else ""
    resources = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", actual)
    local = [link for link in resources if not re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", link)]
    enhanced = {
        "principal_reference_readable": readable,
        "current_canonical_bytes_equal": readable and actual == expected,
        "canonical_resources_readable": readable and bool(local)
        and all((target.parent / link).is_file() for link in local),
    }
    result = {
        "case_id": "PILOT-LEGACY-DELEGATION-01", "fault": fault,
        "old_observer": old, "enhanced_observer": enhanced,
        "detector_status": "PASS" if all(old.values()) and all(enhanced.values()) else "FAIL",
        "principal_reference": links[0] if links else None,
        "original_reference": original_target,
        "apply_rc": apply_rc, "check_rc": check_rc,
        "fixture": "real work-mac components; isolated shared discovery, HOME and source copy",
    }
    write(str(root / "result.json"), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(root.name + " " + result["detector_status"] + " " + json.dumps(result, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault", action="store_true", help="run only the raw known-fault detector; expect exit 1")
    parser.add_argument("--output", type=Path, help="new evidence directory; must not already exist")
    args = parser.parse_args()
    root = args.output
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="aiwb-delegation-pilot-"))
    else:
        root.mkdir(parents=True, exist_ok=False)
    repo = Path(ENV_DIR).parent.parent
    sources = [Path(__file__), Path(ENV_DIR) / "tests/regression.py", Path(ENV_DIR) / "env.py",
               Path(ENV_DIR) / "skills_discovery.py", Path(ENV_DIR) / "profiles/work-mac.json"]
    for name in ("implement-batch", "deliver-spec", "test-design", "self-test-report"):
        sources.extend(p for p in (repo / "skills" / name).rglob("*") if p.is_file())
    identity = {"utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                "platform": platform.platform(), "role": "developer self-test",
                "source_sha256": {str(p.relative_to(repo)): digest(p) for p in sorted(set(sources))}}
    write(str(root / "identity.json"), json.dumps(identity, ensure_ascii=False, indent=2) + "\n")
    results = []
    for name, fault in (("fault", True),) if args.fault else (("fault", True), ("correct", False), ("repeat", False)):
        attempt = root / name
        attempt.mkdir()
        results.append(observe(attempt, fault))
    if args.fault:
        code = 0 if results[0]["detector_status"] == "PASS" else 1
    else:
        code = 0 if (all(all(r["old_observer"].values()) for r in results)
                     and not results[0]["enhanced_observer"]["principal_reference_readable"]
                     and all(r["detector_status"] == "PASS" for r in results[1:])) else 1
    print("experiment_exit=%d evidence=%s" % (code, root))
    if args.output is None and code == 0:
        shutil.rmtree(root)
    return code


if __name__ == "__main__":
    sys.exit(main())
