from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


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


def test_setup_cli_lists_the_optional_reviewed_packs_without_installing_them() -> None:
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
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        matt = next(
            pack for pack in json.loads(completed.stdout)["packs"] if pack["name"] == "matt"
        )
        assert matt["installable"] is True
        assert matt["revision"] == (
            "main snapshot 2026-08-20 "
            "(0ab1b63a410a03d3627979a109c8695de27af954)"
        )
        assert matt["profiles"][0]["name"] == "engineering"
        karpathy = next(
            pack
            for pack in json.loads(completed.stdout)["packs"]
            if pack["name"] == "karpathy"
        )
        assert karpathy["installable"] is True
        assert karpathy["profiles"][0]["skills"] == ["karpathy-guidelines"]
        assert not (repository / ".agents").exists()


def test_goal_draft_converts_approved_local_tickets_to_an_unapproved_contract() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        tickets = repository / "tickets.md"
        tickets.write_text(
            "# Tickets: Greeting flow\n\n"
            "Add greeting and farewell behavior.\n\n"
            "## Add greeting\n\n"
            "**What to build:** A user can receive a greeting.\n\n"
            "**Blocked by:** None — can start immediately.\n\n"
            "- [ ] Greeting includes the supplied name.\n\n"
            "## Add farewell\n\n"
            "**What to build:** A user can receive a farewell.\n\n"
            "**Blocked by:** Add greeting\n\n"
            "- [ ] Farewell includes the supplied name.\n",
            encoding="utf-8",
        )
        output = repository / "greeting.contract.yaml"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "goal",
                "draft",
                "--repo",
                str(repository),
                "--tickets",
                str(tickets),
                "--output",
                str(output),
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        document = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert json.loads(completed.stdout)["status"] == "draft"
        assert document["approval"]["status"] == "draft"
        assert document["todos"][0]["depends_on"] == []
        assert document["todos"][1]["depends_on"] == ["T-1"]
        assert document["todos"][0]["test_ids"] == ["AC-1-1"]
        assert document["todos"][1]["test_ids"] == ["AC-2-1"]
        assert document["todos"][0]["test"]["command"] == [
            "REPLACE_WITH_APPROVED_TEST_COMMAND"
        ]
