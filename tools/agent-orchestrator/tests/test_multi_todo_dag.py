from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentRequest, AgentResult, GateError, GoalRunner, RunReport  # noqa: E402


class ParallelTodoAgent:
    def __init__(self) -> None:
        self._designers_ready = threading.Barrier(2, timeout=5)
        self._lock = threading.Lock()
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        with self._lock:
            self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)

        if request.role == "test_designer":
            self._designers_ready.wait()
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            if request.todo_id == "T-1":
                (tests / "test_greeting.py").write_text(
                    "from greeting import greeting\n\n"
                    "def test_greeting():\n"
                    "    assert greeting('Ada') == 'Hello, Ada!'\n",
                    encoding="utf-8",
                )
            elif request.todo_id == "T-2":
                (tests / "test_farewell.py").write_text(
                    "from farewell import farewell\n\n"
                    "def test_farewell():\n"
                    "    assert farewell('Ada') == 'Goodbye, Ada!'\n",
                    encoding="utf-8",
                )
        elif request.role == "implementer":
            if request.todo_id == "T-1":
                (worktree / "greeting.py").write_text(
                    "def greeting(name):\n"
                    "    return f'Hello, {name}!'\n",
                    encoding="utf-8",
                )
            elif request.todo_id == "T-2":
                (worktree / "farewell.py").write_text(
                    "def farewell(name):\n"
                    "    return f'Goodbye, {name}!'\n",
                    encoding="utf-8",
                )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")

        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}-session",
            final_output="completed",
        )


class DependencyAwareAgent:
    def __init__(self) -> None:
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)
        if request.todo_id == "T-2" and request.role == "test_designer":
            assert (worktree / "greeting.py").is_file()

        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            module = "greeting" if request.todo_id == "T-1" else "farewell"
            expected = "Hello" if request.todo_id == "T-1" else "Goodbye"
            (tests / f"test_{module}.py").write_text(
                f"from {module} import {module}\n\n"
                f"def test_{module}():\n"
                f"    assert {module}('Ada') == '{expected}, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            module = "greeting" if request.todo_id == "T-1" else "farewell"
            expected = "Hello" if request.todo_id == "T-1" else "Goodbye"
            (worktree / f"{module}.py").write_text(
                f"def {module}(name):\n"
                f"    return f'{expected}, {{name}}!'\n",
                encoding="utf-8",
            )
        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}-session",
            final_output="completed",
        )


class PlannedInterruption(RuntimeError):
    pass


class RecoveringDagAgent:
    _modules = {
        "T-1": ("greeting", "Hello"),
        "T-2": ("farewell", "Goodbye"),
        "T-3": ("welcome", "Welcome"),
    }

    def __init__(self, interrupt_t1: bool = False) -> None:
        self.interrupt_t1 = interrupt_t1
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)
        if request.role == "candidate_verifier":
            return AgentResult(
                session_id="candidate-verifier-session",
                final_output="completed",
            )
        module, expected = self._modules[request.todo_id]
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / f"test_{module}.py").write_text(
                f"from {module} import {module}\n\n"
                f"def test_{module}():\n"
                f"    assert {module}('Ada') == '{expected}, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            if request.todo_id == "T-1" and self.interrupt_t1:
                raise PlannedInterruption("simulated host restart")
            (worktree / f"{module}.py").write_text(
                f"def {module}(name):\n"
                f"    return f'{expected}, {{name}}!'\n",
                encoding="utf-8",
            )
        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}-session",
            final_output="completed",
        )


class CrossTodoRegressionAgent:
    def __init__(self) -> None:
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)
        tests = worktree / "tests"
        if request.role == "test_designer":
            tests.mkdir(exist_ok=True)
            if request.todo_id == "T-1":
                (tests / "test_greeting.py").write_text(
                    "from greeting import greeting\n\n"
                    "def test_greeting():\n"
                    "    assert greeting('Ada') == 'Hello, Ada!'\n",
                    encoding="utf-8",
                )
            else:
                (tests / "test_farewell.py").write_text(
                    "from farewell import farewell\n\n"
                    "def test_farewell():\n"
                    "    assert farewell('Ada') == 'Goodbye, Ada!'\n",
                    encoding="utf-8",
                )
        elif request.role == "implementer":
            if request.todo_id == "T-1":
                (worktree / "greeting.py").write_text(
                    "from settings import PREFIX\n\n"
                    "def greeting(name):\n"
                    "    return f'{PREFIX}, {name}!'\n",
                    encoding="utf-8",
                )
            else:
                (worktree / "settings.py").write_text(
                    "PREFIX = 'Hola'\n",
                    encoding="utf-8",
                )
                (worktree / "farewell.py").write_text(
                    "def farewell(name):\n"
                    "    return f'Goodbye, {name}!'\n",
                    encoding="utf-8",
                )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}-session",
            final_output="completed",
        )


class MutatingCandidateVerifierAgent(ParallelTodoAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        if request.role == "candidate_verifier":
            assert request.sandbox == "read-only"
            self.calls.append((request.todo_id, request.role))
            (Path(request.worktree) / "greeting.py").write_text(
                "def greeting(name):\n"
                "    return 'mutated'\n",
                encoding="utf-8",
            )
            return AgentResult(
                session_id="mutating-candidate-verifier",
                final_output="completed",
            )
        return super().run(request)


class InterruptingFinalAcceptanceRunner(GoalRunner):
    def _run_gate(self, contract, todo, stage, cwd):
        if stage == "candidate_acceptance:T-2":
            raise PlannedInterruption("simulated final acceptance interruption")
        return super()._run_gate(contract, todo, stage, cwd)


def test_independent_todos_run_in_parallel_worktrees_and_integrate_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        agent = ParallelTodoAgent()

        report = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        ).run(contract)

        assert report.status == "merge_ready"
        assert RunReport.from_dict(report.to_dict()) == report
        assert {todo.todo_id: todo.status for todo in report.todos} == {
            "T-1": "integrated",
            "T-2": "integrated",
        }
        assert len({todo.worktree for todo in report.todos}) == 2
        assert all(todo.worktree != report.worktree for todo in report.todos)
        assert set(agent.calls) == {
            ("T-1", "test_designer"),
            ("T-1", "implementer"),
            ("T-1", "verifier"),
            ("T-2", "test_designer"),
            ("T-2", "implementer"),
            ("T-2", "verifier"),
            ("candidate", "candidate_verifier"),
        }
        assert _git(repository, "show", f"{report.branch}:greeting.py").stdout.startswith(
            "def greeting"
        )
        assert _git(repository, "show", f"{report.branch}:farewell.py").stdout.startswith(
            "def farewell"
        )


def test_dependent_todo_starts_from_integrated_upstream_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        data["todos"][1]["depends_on"] = ["T-1"]
        contract.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        agent = DependencyAwareAgent()

        report = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        ).run(contract)

        assert report.status == "merge_ready"
        assert agent.calls == [
            ("T-1", "test_designer"),
            ("T-1", "implementer"),
            ("T-1", "verifier"),
            ("T-2", "test_designer"),
            ("T-2", "implementer"),
            ("T-2", "verifier"),
            ("candidate", "candidate_verifier"),
        ]
        todos = {todo.todo_id: todo for todo in report.todos}
        assert _git(
            repository,
            "merge-base",
            "--is-ancestor",
            todos["T-1"].code_commit,
            todos["T-2"].base_commit,
        ).returncode == 0


def test_interruption_keeps_downstream_frozen_and_resumes_other_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        data["todos"][1]["depends_on"] = ["T-1"]
        data["goal"]["acceptance"].append(
            {"id": "AC-3", "statement": "Welcome includes the name."}
        )
        data["todos"].append(
            {
                "id": "T-3",
                "title": "Implement welcome",
                "depends_on": [],
                "test_ids": ["AC-3"],
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q"],
                    "allowed_paths": ["tests/test_welcome.py"],
                },
            }
        )
        contract.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        interrupted_agent = RecoveringDagAgent(interrupt_t1=True)
        interrupted_runner = GoalRunner(
            state_dir=root / "state",
            agent=interrupted_agent,
            max_workers=2,
        )
        prepared = interrupted_runner.prepare(contract)
        try:
            interrupted_runner.run(contract)
        except RuntimeError as error:
            assert str(error) == "codex role 'implementer' failed: PlannedInterruption"
            assert "simulated host restart" not in str(error)
        else:
            raise AssertionError("the first run must be interrupted")

        interrupted = interrupted_runner.report(prepared.run_id)
        statuses = {todo.todo_id: todo.status for todo in interrupted.todos}
        assert statuses == {
            "T-1": "red_verified",
            "T-2": "pending",
            "T-3": "verified",
        }
        assert not any(todo_id == "T-2" for todo_id, _ in interrupted_agent.calls)

        resumed_agent = RecoveringDagAgent()
        resumed = GoalRunner(
            state_dir=root / "state",
            agent=resumed_agent,
            max_workers=2,
        ).run(contract)

        assert resumed.status == "merge_ready"
        assert all(todo.status == "integrated" for todo in resumed.todos)
        assert ("T-1", "test_designer") not in resumed_agent.calls
        assert not any(todo_id == "T-3" for todo_id, _ in resumed_agent.calls)
        assert [role for todo_id, role in resumed_agent.calls if todo_id == "T-2"] == [
            "test_designer",
            "implementer",
            "verifier",
        ]


def test_final_candidate_acceptance_rejects_a_cross_todo_regression() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        (repository / "settings.py").write_text("PREFIX = 'Hello'\n", encoding="utf-8")
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow_data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        workflow_data["capabilities"]["commands"] = {
            "greeting": {
                "argv": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_greeting.py",
                ],
                "approved": True,
            },
            "farewell": {
                "argv": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_farewell.py",
                ],
                "approved": True,
            },
        }
        workflow.write_text(
            yaml.safe_dump(workflow_data, sort_keys=False),
            encoding="utf-8",
        )
        _git(repository, "add", "settings.py", ".ai-workbench/workflow.yaml")
        _git(repository, "commit", "-m", "Add shared greeting settings")
        contract = _write_contract(root, repository)
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        data["todos"][0]["test"]["command"] = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_greeting.py",
        ]
        data["todos"][1]["test"]["command"] = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_farewell.py",
        ]
        contract.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        agent = CrossTodoRegressionAgent()
        runner = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        )
        prepared = runner.prepare(contract)

        try:
            runner.run(contract)
        except GateError as error:
            assert "Final Candidate acceptance failed for T-1" in str(error)
        else:
            raise AssertionError("the integrated regression must reject acceptance")

        report = runner.report(prepared.run_id)
        assert report.status == "failed_acceptance"
        assert report.stop is not None
        assert report.stop.reason == "acceptance_failure"
        assert report.stop.stage == "candidate_acceptance:T-1"
        assert ("candidate", "candidate_verifier") in agent.calls
        assert any(
            attempt.role == "candidate_verifier"
            and attempt.todo_id == "candidate"
            and attempt.status == "succeeded"
            for attempt in report.attempts
        )
        assert any(
            item.stage == "candidate_acceptance:T-1"
            and item.returncode != 0
            for item in report.evidence
        )


def test_final_candidate_verifier_cannot_mutate_the_assembled_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        agent = MutatingCandidateVerifierAgent()
        runner = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        )
        prepared = runner.prepare(contract)

        try:
            runner.run(contract)
        except GateError as error:
            assert "mutated the immutable Candidate" in str(error)
        else:
            raise AssertionError("a mutating final verifier must reject acceptance")

        report = runner.report(prepared.run_id)
        assert report.status == "failed_acceptance"
        assert report.stop is not None
        assert report.stop.reason == "acceptance_failure"
        assert report.candidate_commit
        assert report.attempts[-1].role == "candidate_verifier"
        assert report.attempts[-1].status == "rejected"
        assert _git(
            repository,
            "show",
            f"{report.candidate_commit}:greeting.py",
        ).stdout == "def greeting(name):\n    return f'Hello, {name}!'\n"
        assert _git(
            Path(report.worktree),
            "status",
            "--porcelain",
        ).stdout == ""


def test_final_candidate_acceptance_resumes_without_repeating_completed_work() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        interrupted_agent = ParallelTodoAgent()
        runner = InterruptingFinalAcceptanceRunner(
            state_dir=root / "state",
            agent=interrupted_agent,
            max_workers=2,
        )
        prepared = runner.prepare(contract)

        try:
            runner.run(contract)
        except PlannedInterruption as error:
            assert "final acceptance" in str(error)
        else:
            raise AssertionError("the first final acceptance must be interrupted")

        interrupted = runner.report(prepared.run_id)
        assert interrupted.status == "candidate_accepting"
        assert [
            item.stage
            for item in interrupted.evidence
            if item.stage.startswith("candidate_acceptance:")
        ] == ["candidate_acceptance:T-1"]
        assert interrupted_agent.calls.count(
            ("candidate", "candidate_verifier")
        ) == 1

        resumed_agent = ParallelTodoAgent()
        resumed = GoalRunner(
            state_dir=root / "state",
            agent=resumed_agent,
            max_workers=2,
        ).run(contract)

        assert resumed.status == "merge_ready"
        assert resumed_agent.calls == []
        assert [
            item.stage
            for item in resumed.evidence
            if item.stage.startswith("candidate_acceptance:")
        ] == [
            "candidate_acceptance:T-1",
            "candidate_acceptance:T-2",
        ]


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
    (repository / "README.md").write_text("# Fixture project\n", encoding="utf-8")
    test_command = [sys.executable, "-m", "pytest", "-q"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {"unit": {"argv": test_command, "approved": True}},
                    "skills": {},
                },
                "harness": {"profiles": {"local": {"environment": "local"}}},
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
                    "id": "salutations-goal",
                    "title": "Add salutations",
                    "requirement": "Expose greeting and farewell functions.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting includes the name."},
                        {"id": "AC-2", "statement": "Farewell includes the name."},
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
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
