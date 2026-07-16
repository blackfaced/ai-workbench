from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]


def test_init_discovers_repository_capabilities_without_executing_them() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        output_path = repository / ".ai-workbench" / "workflow.yaml"
        marker = root / "script-was-executed"
        (repository / "tests").mkdir(parents=True)
        (repository / "scripts").mkdir()
        (repository / ".agents" / "skills" / "tdd").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            encoding="utf-8",
        )
        (repository / "playwright.config.ts").write_text(
            "export default {};\n",
            encoding="utf-8",
        )
        (repository / ".agents" / "skills" / "tdd" / "SKILL.md").write_text(
            "# TDD\n",
            encoding="utf-8",
        )
        script = repository / "scripts" / "e2e-local.sh"
        script.write_text(
            f"#!/bin/sh\ntouch '{marker}'\n",
            encoding="utf-8",
        )
        script.chmod(0o755)

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "init",
                "--repo",
                str(repository),
                "--output",
                str(output_path),
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert not marker.exists()
        assert json.loads(completed.stdout) == {
            "config": str(output_path.resolve()),
            "status": "draft",
            "suggestions": 3,
        }
        config = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        assert config["schema_version"] == 1
        assert config["status"] == "draft"
        assert config["project"] == {
            "root": str(repository.resolve()),
            "trusted": False,
        }
        assert config["discovery"] == {
            "scripts": ["scripts/e2e-local.sh"],
            "signals": ["playwright", "pytest"],
            "skills": [".agents/skills/tdd/SKILL.md"],
        }
        assert config["suggestions"]["commands"] == {
            "browser_e2e": {
                "argv": ["npx", "playwright", "test"],
                "reason": "playwright configuration detected",
            },
            "local_e2e": {
                "argv": ["./scripts/e2e-local.sh"],
                "reason": "executable repository script detected",
            },
            "unit": {
                "argv": [sys.executable, "-m", "pytest", "-q"],
                "reason": "pytest configuration or tests directory detected",
            },
        }
        assert config["capabilities"] == {"commands": {}, "skills": {}}
        assert config["harness"] == {
            "allowed_kubernetes_contexts": [],
            "profiles": {},
        }
        assert config["images"] == {"profiles": {}}
