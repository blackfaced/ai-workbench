from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]


def test_doctor_validates_an_approved_non_production_project_without_running_commands() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        marker = root / "command-was-executed"
        command = repository / "verify.sh"
        command.write_text(
            f"#!/bin/sh\ntouch '{marker}'\n",
            encoding="utf-8",
        )
        command.chmod(0o755)
        config_path = repository / "workflow.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {
                        "root": str(repository),
                        "trusted": True,
                    },
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [str(command)],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {
                        "profiles": {
                            "local": {"environment": "local"},
                            "development": {"environment": "development"},
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "doctor",
                "--config",
                str(config_path),
                "--agent-provider",
                "claude-code",
                "--claude-bin",
                sys.executable,
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
        report = json.loads(completed.stdout)
        assert report["status"] == "ok"
        assert {check["name"] for check in report["checks"]} == {
            "approved",
            "commands",
            "non_production",
            "provider",
            "repository",
            "schema",
            "trusted",
        }
        assert all(check["status"] == "pass" for check in report["checks"])
        provider_check = next(
            check for check in report["checks"] if check["name"] == "provider"
        )
        assert "Claude Code executable" in provider_check["detail"]


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
