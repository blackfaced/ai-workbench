from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import GoalIntake  # noqa: E402
from aiwb.mcp_server import McpServer  # noqa: E402


def test_small_single_todo_task_stays_in_the_installed_matt_flow() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        contract = _write_contract(root, repository, todo_count=1)
        before = _tree(root)

        result = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert _tree(root) == before
        assert result.readiness == "interactive"
        assert result.cheapest_viable_path == "interactive_matt"
        assert result.blockers == ()
        assert result.next_action == "invoke_ask_matt"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 4
        assert result.execution_envelope["deterministic"]["harness_executions"] == 5


def test_durable_draft_is_ready_for_one_explicit_approval() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Complete two independent Todos overnight with recovery.",
        )

        result = GoalIntake(daemon_probe=lambda: True).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert result.readiness == "ready_for_approval"
        assert result.cheapest_viable_path == "ai_workbench_unattended"
        assert result.blockers == ()
        assert result.daemon_status == "ok"
        assert result.approval_required is True
        assert result.submission_required is True
        assert result.next_action == "approve_contract"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 7
        assert result.execution_envelope["deterministic"]["harness_executions"] == 10


def test_durable_intake_returns_all_actionable_readiness_blockers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root, approved=False)
        contract = root / "blocked.contract.yaml"
        contract.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "goal": {
                        "id": "blocked-goal",
                        "title": "Blocked overnight work",
                        "requirement": "Run multiple Todos overnight.",
                        "acceptance": [],
                    },
                    "approval": {"status": "draft"},
                    "project": {"repo": str(repository), "base_ref": "main"},
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "First",
                            "test_ids": [],
                            "test": {},
                        },
                        {
                            "id": "T-2",
                            "title": "Second",
                            "depends_on": ["missing"],
                            "test_ids": [],
                            "test": {
                                "command": ["missing-test"],
                                "allowed_paths": [],
                                "harness": "production",
                            },
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )

        codes = {blocker.code for blocker in result.blockers}
        assert result.readiness == "blocked"
        assert codes >= {
            "acceptance_boundary",
            "todo_dependencies",
            "harness_configuration",
            "permissions",
            "provider_selection",
            "resource_policy",
            "non_production",
        }
        assert result.next_action == "resolve_blockers"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 7


def test_approved_contract_requires_daemon_then_explicit_submission() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Run unattended overnight.",
        )
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        data["approval"] = {
            "status": "approved",
            "approved_by": "owner",
            "approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc),
        }
        contract.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

        unavailable = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )
        available = GoalIntake(daemon_probe=lambda: True).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert unavailable.readiness == "blocked"
        assert [item.code for item in unavailable.blockers] == ["daemon_state"]
        assert unavailable.next_action == "start_daemon"
        assert available.readiness == "ready_to_submit"
        assert available.blockers == ()
        assert available.approval_required is False
        assert available.submission_required is True
        assert available.next_action == "submit_contract"


def test_accepted_tickets_choose_interactive_or_contract_handoff_by_shape() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        small = _write_tickets(root / "small.md", ["Fix typo"])
        durable = _write_tickets(
            root / "durable.md",
            ["Add API", "Add browser E2E"],
        )
        intake = GoalIntake(daemon_probe=lambda: True)

        small_result = intake.inspect(
            repository=repository,
            tickets_path=small,
        )
        durable_result = intake.inspect(
            repository=repository,
            tickets_path=durable,
        )

        assert small_result.readiness == "interactive"
        assert small_result.next_action == "invoke_ask_matt"
        assert durable_result.readiness == "blocked"
        assert durable_result.cheapest_viable_path == "ai_workbench_unattended"
        assert durable_result.next_action == "create_contract_draft"
        assert {item.code for item in durable_result.blockers} == {
            "contract_draft"
        }
        assert durable_result.execution_envelope["deterministic"][
            "agent_attempts"
        ] == 7


def test_cli_and_mcp_share_the_same_intake_result() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Run unattended overnight.",
        )
        missing_socket = root / "missing-daemon.sock"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "goal",
                "intake",
                "--repo",
                str(repository),
                "--contract",
                str(contract),
                "--socket",
                str(missing_socket),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        cli_value = json.loads(completed.stdout)

        server = McpServer(missing_socket)
        result = server._call_tool(
            "aiwb_goal_intake",
            {
                "repository": str(repository),
                "contract_path": str(contract),
            },
        )
        assert result["isError"] is False
        mcp_value = json.loads(result["content"][0]["text"])

        assert cli_value == mcp_value
        assert cli_value["readiness"] == "ready_for_approval"
        assert cli_value["daemon_status"] == "unavailable"
        assert cli_value["next_action"] == "approve_contract"


def _create_repository(root: Path, approved: bool = True) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    command = [sys.executable, "-m", "pytest", "-q"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved" if approved else "draft",
                "project": {
                    "root": str(repository),
                    "trusted": approved,
                },
                "capabilities": {
                    "commands": {
                        "unit": {"argv": command, "approved": approved},
                    },
                    "skills": {},
                },
                "harness": {
                    "allowed_kubernetes_contexts": [],
                    "profiles": (
                        {}
                        if approved
                        else {
                            "production": {
                                "kind": "kubernetes",
                                "environment": "production",
                                "context": "production",
                            }
                        }
                    ),
                },
                "images": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_contract(
    root: Path,
    repository: Path,
    todo_count: int,
    requirement: str = "Make one small local change.",
) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    acceptance = [
        {"id": f"AC-{index}", "statement": f"Behavior {index} works."}
        for index in range(1, todo_count + 1)
    ]
    todos = [
        {
            "id": f"T-{index}",
            "title": f"Implement behavior {index}",
            "depends_on": [],
            "test_ids": [f"AC-{index}"],
            "test": {
                "command": command,
                "allowed_paths": [f"tests/test_behavior_{index}.py"],
            },
        }
        for index in range(1, todo_count + 1)
    ]
    contract = root / f"{todo_count}-todo.contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": f"intake-{todo_count}-todo",
                    "title": "Inspect task readiness",
                    "requirement": requirement,
                    "acceptance": acceptance,
                },
                "approval": {"status": "draft"},
                "agent": {"provider": "codex"},
                "resources": {},
                "project": {"repo": str(repository), "base_ref": "main"},
                "todos": todos,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _install_ask_matt(repository: Path) -> None:
    skill = repository / ".codex" / "skills" / "ask-matt" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: ask-matt\n"
        "description: Route general engineering work to an upstream Skill.\n"
        "---\n",
        encoding="utf-8",
    )


def _write_tickets(path: Path, titles: list[str]) -> Path:
    lines = ["# Tickets: Intake fixture", "Accepted engineering work.", ""]
    for index, title in enumerate(titles):
        lines.extend(
            [
                f"## {title}",
                f"**What to build:** Implement {title.lower()}.",
                "**Blocked by:** None",
                f"- [ ] {title} is accepted.",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tree(root: Path) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (str(path.relative_to(root)), path.stat().st_size)
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
