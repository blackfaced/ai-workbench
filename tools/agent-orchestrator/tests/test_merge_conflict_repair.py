from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentRequest, AgentResult, GoalRunner, RunReport  # noqa: E402
from aiwb.repair import MergeConflictRepairError  # noqa: E402


class ConflictingTodoAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def run(self, request: AgentRequest) -> AgentResult:
        with self._lock:
            self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)
        tests = worktree / "tests"

        if request.role == "test_designer":
            tests.mkdir(exist_ok=True)
            if request.todo_id == "T-1":
                (tests / "test_greeting.py").write_text(
                    "from messages import greeting\n\n"
                    "def test_greeting():\n"
                    "    assert greeting() == 'hello'\n",
                    encoding="utf-8",
                )
            else:
                (tests / "test_farewell.py").write_text(
                    "from messages import farewell\n\n"
                    "def test_farewell():\n"
                    "    assert farewell() == 'goodbye'\n",
                    encoding="utf-8",
                )
        elif request.role == "implementer":
            source = worktree / "messages.py"
            if request.todo_id == "T-1":
                source.write_text(
                    "def greeting():\n"
                    "    return 'hello'\n",
                    encoding="utf-8",
                )
            else:
                source.write_text(
                    "def farewell():\n"
                    "    return 'goodbye'\n",
                    encoding="utf-8",
                )
        elif request.role == "conflict_repairer":
            assert request.todo_id == "T-2"
            assert "messages.py" in request.prompt
            (worktree / "messages.py").write_text(
                "def greeting():\n"
                "    return 'hello'\n\n"
                "def farewell():\n"
                "    return 'goodbye'\n",
                encoding="utf-8",
            )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")

        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}-session",
            final_output="completed",
        )


class PlannedRepairInterruption(RuntimeError):
    pass


class InterruptedConflictAgent(ConflictingTodoAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.role == "conflict_repairer":
            raise PlannedRepairInterruption("simulated restart during conflict repair")
        return result


class ScopeEscapingConflictAgent(ConflictingTodoAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.role == "conflict_repairer":
            (Path(request.worktree) / "unrelated.py").write_text(
                "unexpected = True\n",
                encoding="utf-8",
            )
        return result


def test_candidate_repairs_a_todo_merge_conflict_with_a_fresh_agent_session() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        agent = ConflictingTodoAgent()

        report = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        ).run(contract)

        assert report.status == "merge_ready"
        assert agent.calls.count(("T-2", "conflict_repairer")) == 1
        repaired_todo = next(todo for todo in report.todos if todo.todo_id == "T-2")
        repair_attempts = [
            attempt
            for attempt in repaired_todo.attempts
            if attempt.role == "conflict_repairer"
        ]
        assert len(repair_attempts) == 1
        assert repair_attempts[0].status == "succeeded"
        assert repair_attempts[0].todo_id == "T-2"
        assert repair_attempts[0].session_id == "T-2-conflict_repairer-session"
        assert len(repaired_todo.repair_commits) == 1
        assert repaired_todo.repair_commits[0] != repaired_todo.code_commit
        assert RunReport.from_dict(report.to_dict()) == report
        assert _git(repository, "show", f"{report.branch}:messages.py").stdout == (
            "def greeting():\n"
            "    return 'hello'\n\n"
            "def farewell():\n"
            "    return 'goodbye'\n"
        )


def test_resume_repairs_an_interrupted_candidate_merge_without_rerunning_todos() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"

        with pytest.raises(
            PlannedRepairInterruption,
            match="simulated restart",
        ):
            GoalRunner(
                state_dir=state_dir,
                agent=InterruptedConflictAgent(),
                max_workers=2,
            ).run(contract)

        resumed_agent = ConflictingTodoAgent()
        report = GoalRunner(
            state_dir=state_dir,
            agent=resumed_agent,
            max_workers=2,
        ).run(contract)

        assert report.status == "merge_ready"
        assert resumed_agent.calls == [
            ("T-2", "conflict_repairer"),
            ("candidate", "candidate_verifier"),
        ]


def test_conflict_repairer_cannot_change_paths_outside_the_conflict() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)

        with pytest.raises(MergeConflictRepairError, match="unexpected paths"):
            GoalRunner(
                state_dir=root / "state",
                agent=ScopeEscapingConflictAgent(),
                max_workers=2,
            ).run(contract)

        assert "unrelated.py" not in _git(repository, "ls-files").stdout


def _create_repository(root: Path) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    (repository / "messages.py").write_text(
        "def version():\n"
        "    return 'base'\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "pytest", "-q"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {"unit": {"argv": command, "approved": True}},
                    "skills": {},
                },
                "harness": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_contract(root: Path, repository: Path) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "conflicting-messages",
                    "title": "Add two messages",
                    "requirement": "Expose greeting and farewell messages.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting returns hello."},
                        {"id": "AC-2", "statement": "Farewell returns goodbye."},
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todos": [
                    {
                        "id": "T-1",
                        "title": "Implement greeting",
                        "depends_on": [],
                        "test_ids": ["AC-1"],
                        "test": {
                            "command": command,
                            "allowed_paths": ["tests/test_greeting.py"],
                        },
                    },
                    {
                        "id": "T-2",
                        "title": "Implement farewell",
                        "depends_on": [],
                        "test_ids": ["AC-2"],
                        "test": {
                            "command": command,
                            "allowed_paths": ["tests/test_farewell.py"],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
