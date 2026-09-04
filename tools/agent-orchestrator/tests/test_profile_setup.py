from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    CodexDriver,
    HarnessApplyRequest,
    HarnessProfileSelections,
    HarnessSetup,
    HarnessSetupRequest,
)
from aiwb.profile_setup import resolve_harness_profile  # noqa: E402


_CATALOG = {
    "models": [
        {
            "slug": "gpt-test",
            "display_name": "GPT Test",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": "low"},
                {"effort": "medium"},
                {"effort": "high"},
                {"effort": "xhigh"},
                {"effort": "max"},
            ],
            "visibility": "list",
        },
        {
            "slug": "gpt-internal",
            "display_name": "GPT Internal",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [{"effort": "medium"}],
            "visibility": "hide",
        },
    ]
}

_FAKE_CODEX_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys

catalog = os.environ.get("AIWB_FAKE_CODEX_CATALOG")
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.151.0")
elif sys.argv[1:] == ["debug", "models"]:
    print(catalog)
else:
    sys.exit(2)
"""

_FIXED_CLOCK = lambda: datetime(2026, 9, 3, tzinfo=timezone.utc)  # noqa: E731


def _fake_codex(root: Path, catalog: dict = None) -> Path:
    path = root / "fake-codex"
    path.write_text(_FAKE_CODEX_SCRIPT, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    os.environ["AIWB_FAKE_CODEX_CATALOG"] = json.dumps(catalog or _CATALOG)
    return path


def _driver(root: Path, catalog: dict = None) -> CodexDriver:
    return CodexDriver(str(_fake_codex(root, catalog)))


def _selections(**overrides: object) -> HarnessProfileSelections:
    values = {"model": "gpt-test"}
    values.update(overrides)
    return HarnessProfileSelections(**values)


def _resolve(root: Path, selections: HarnessProfileSelections, catalog: dict = None):
    return resolve_harness_profile(
        root,
        selections,
        ("codex",),
        driver=_driver(root, catalog),
        clock=_FIXED_CLOCK,
    )


def test_resolve_produces_an_exact_profile_with_stable_digest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        resolution = _resolve(root, _selections())
        assert resolution.profile.driver == "codex"
        assert resolution.profile.model == "gpt-test"
        assert resolution.profile.effort == "medium"
        assert resolution.profile.permissions == ("workspace-write",)
        assert resolution.internal_role_models == ("gpt-internal",)
        assert resolution.catalog.version == "codex-cli 0.151.0"
        assert resolution.profile_digest == _resolve(root, _selections()).profile_digest


def test_resolve_honors_an_explicit_supported_effort() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        resolution = _resolve(root, _selections(effort="max"))
        assert resolution.profile.effort == "max"


def test_resolve_fails_closed_on_unsupported_selections() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with pytest.raises(ValueError, match="explicit Model"):
            _resolve(root, _selections(model=" "))
        with pytest.raises(ValueError, match="not in the Codex catalog"):
            _resolve(root, _selections(model="gpt-unknown"))
        with pytest.raises(ValueError, match="internal Harness identifier"):
            _resolve(root, _selections(model="gpt-internal"))
        with pytest.raises(ValueError, match="does not support reasoning effort"):
            _resolve(root, _selections(effort="ultra"))
        with pytest.raises(ValueError, match="codex Agent target"):
            resolve_harness_profile(
                root, _selections(), ("claude-code",),
                driver=_driver(root), clock=_FIXED_CLOCK,
            )
        with pytest.raises(ValueError, match="codex Agent target"):
            resolve_harness_profile(
                root, _selections(), (),
                driver=_driver(root), clock=_FIXED_CLOCK,
            )


def test_resolve_locks_named_extension_digests_and_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        skill = root / ".codex" / "skills" / "focused" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: focused\ndescription: Focus this attempt.\nversion: 1\n---\n\n# Focused\n",
            encoding="utf-8",
        )
        resolution = _resolve(root, _selections(extensions=("skill:focused@1",)))
        assert len(resolution.extensions) == 1
        extension = resolution.extensions[0]
        assert extension.identity == "skill:focused@1"
        assert extension.path == ".codex/skills/focused/SKILL.md"
        assert len(extension.sha256) == 64
        assert resolution.profile.resolved_extensions
        with pytest.raises(ValueError, match="not installed"):
            _resolve(root, _selections(extensions=("skill:missing@1",)))
        with pytest.raises(ValueError, match="identity or version does not match"):
            _resolve(root, _selections(extensions=("skill:focused@2",)))
        mcp = root / ".ai-workbench" / "extensions" / "mcp"
        mcp.mkdir(parents=True)
        entrypoint = root / "tools" / "mcp-server.sh"
        entrypoint.parent.mkdir()
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (mcp / "search.yaml").write_text(
            "kind: mcp\nname: search\nversion: 1\ndriver: codex\n"
            "configuration:\n  entrypoint: tools/mcp-server.sh\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unsupported Codex Harness Extension"):
            _resolve(root, _selections(extensions=("mcp:search@1",)))


def test_profile_digest_tracks_model_effort_catalog_and_extension_drift() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = _resolve(root, _selections()).profile_digest
        assert _resolve(root, _selections(model="gpt-test", effort="high")).profile_digest != base
        changed_catalog = json.loads(json.dumps(_CATALOG))
        changed_catalog["models"][0]["display_name"] = "GPT Test Renamed"
        assert _resolve(root, _selections(), catalog=changed_catalog).profile_digest != base
        skill = root / ".codex" / "skills" / "focused" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: focused\ndescription: v1.\nversion: 1\n---\n\n# Focused\n",
            encoding="utf-8",
        )
        with_skill = _resolve(root, _selections(extensions=("skill:focused@1",))).profile_digest
        skill.write_text(
            "---\nname: focused\ndescription: v1 updated.\nversion: 1\n---\n\n# Focused\n",
            encoding="utf-8",
        )
        assert _resolve(root, _selections(extensions=("skill:focused@1",))).profile_digest != with_skill


def test_apply_persists_the_resolved_profile_idempotently() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        driver = _driver(root)
        setup = HarnessSetup(codex_driver=driver)
        request = HarnessSetupRequest(
            repository=repository,
            agent_targets=("codex",),
            profile_selections=_selections(),
        )
        plan = setup.plan(request)
        candidate = setup.apply(HarnessApplyRequest(plan=plan, confirmed=True))
        profile_path = repository / ".ai-workbench" / "agent-harness.yaml"
        assert candidate.profile is not None
        assert profile_path.is_file()
        document = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        assert document["profile_digest"] == candidate.profile.profile_digest
        assert document["agent_harness"]["model"] == "gpt-test"
        assert document["agent_harness"]["effort"] == "medium"
        first_contents = profile_path.read_text(encoding="utf-8")

        second = setup.apply(HarnessApplyRequest(plan=setup.plan(request), confirmed=True))
        assert second.changed is False
        assert profile_path.read_text(encoding="utf-8") == first_contents

        changed_request = HarnessSetupRequest(
            repository=repository,
            agent_targets=("codex",),
            profile_selections=_selections(effort="high"),
        )
        third = setup.apply(
            HarnessApplyRequest(plan=setup.plan(changed_request), confirmed=True)
        )
        assert third.changed is True
        updated = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        assert updated["agent_harness"]["effort"] == "high"
        assert updated["profile_digest"] != document["profile_digest"]
