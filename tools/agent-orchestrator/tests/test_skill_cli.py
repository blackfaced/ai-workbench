from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]


def test_skills_ask_cli_is_advisory_and_returns_bounded_json() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "skills",
                "ask",
                "--repo",
                str(repository),
                "--task",
                "submit an approved unattended goal and inspect evidence",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["recommendations"][0]["name"] == (
            "run-approved-goal"
        )
        assert not (repository / ".ai-workbench").exists()


def test_setup_cli_requires_apply_before_it_installs_a_project_skill() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        command = [
            sys.executable,
            "-m",
            "aiwb",
            "setup",
            "--repo",
            str(repository),
            "--agent-target",
            "codex",
            "--install-skill",
            "ask-ai-workbench",
        ]

        inspected = subprocess.run(
            command,
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        installed = repository / ".codex" / "skills" / "ask-ai-workbench" / "SKILL.md"
        assert inspected.returncode == 0, inspected.stderr
        assert not installed.exists()

        applied = subprocess.run(
            [*command, "--apply"],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert applied.returncode == 0, applied.stderr
        assert installed.is_file()
