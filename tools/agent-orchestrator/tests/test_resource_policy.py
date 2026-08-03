from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentDaemon,
    AgentRequest,
    AgentResult,
    DaemonClient,
    DaemonError,
    GoalRunner,
    GateError,
    ProviderQuotaError,
    RunPaused,
    preview_execution,
)


class ResourceAgent:
    def __init__(self, usage_by_role=None) -> None:
        self.calls = []
        self.usage_by_role = usage_by_role or {}

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls.append(
            (
                request.todo_id,
                request.role,
                request.provider,
                request.model,
            )
        )
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting():\n"
                "    assert greeting() == 'hello'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "greeting.py").write_text(
                "def greeting():\n"
                "    return 'hello'\n",
                encoding="utf-8",
            )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}",
            final_output="completed",
            usage=self.usage_by_role.get(request.role, {}),
        )


class QuotaOnceAgent(ResourceAgent):
    def __init__(self) -> None:
        super().__init__()
        self.quota_exhausted = True

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role == "implementer" and self.quota_exhausted:
            self.calls.append(
                (
                    request.todo_id,
                    request.role,
                    request.provider,
                    request.model,
                )
            )
            self.quota_exhausted = False
            raise ProviderQuotaError(
                provider=request.provider,
                detail="subscription usage limit reached",
                usage={"total_tokens": 7},
            )
        return super().run(request)


class BrokenImplementationAgent(ResourceAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.role == "implementer":
            (Path(request.worktree) / "greeting.py").write_text(
                "def greeting():\n"
                "    return 'wrong'\n",
                encoding="utf-8",
            )
        return result


class ParallelQuotaAgent:
    def __init__(self) -> None:
        self._implementers_ready = threading.Barrier(2, timeout=5)
        self._lock = threading.Lock()
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        with self._lock:
            self.calls.append((request.todo_id, request.role))
        worktree = Path(request.worktree)
        module = {
            "T-1": "greeting",
            "T-2": "farewell",
            "T-3": "welcome",
        }[request.todo_id]
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / f"test_{module}.py").write_text(
                f"from {module} import {module}\n\n"
                f"def test_{module}():\n"
                f"    assert {module}() == '{module}'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            self._implementers_ready.wait()
            if request.todo_id == "T-1":
                raise ProviderQuotaError(
                    provider=request.provider,
                    detail="subscription usage limit reached",
                )
            (worktree / f"{module}.py").write_text(
                f"def {module}():\n"
                f"    return '{module}'\n",
                encoding="utf-8",
            )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"{request.todo_id}-{request.role}",
            final_output="completed",
        )


def test_agent_attempt_boundary_pauses_and_resumes_the_same_provider_model() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository, {"agent_attempts": 2})
        agent = ResourceAgent()
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)

        with pytest.raises(RunPaused, match="agent_attempts"):
            runner.run(contract)

        paused = runner.report(prepared.run_id)
        assert paused.status == "paused_resource"
        assert paused.stop is not None
        assert paused.stop.reason == "resource_boundary"
        assert paused.stop.boundary == "agent_attempts"
        assert paused.stop.todo_id == "T-1"
        assert paused.stop.role == "verifier"
        assert paused.stop.resumable is True
        assert paused.todos[0].status == "paused"
        assert [item[1] for item in agent.calls] == [
            "test_designer",
            "implementer",
        ]

        runner.resume(prepared.run_id)
        completed = runner.run(contract)

        assert completed.status == "merge_ready"
        assert completed.stop is None
        assert [item[1] for item in agent.calls] == [
            "test_designer",
            "implementer",
            "verifier",
            "candidate_verifier",
        ]
        assert all(item[2] == "claude-code" for item in agent.calls)
        assert all(item[3] == "sonnet" for item in agent.calls)


def test_preflight_exposes_only_configured_resource_boundaries() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            {
                "agent_attempts": 4,
                "wall_clock_seconds": 120,
                "provider_tokens": 9000,
            },
        )

        envelope = preview_execution(contract).to_dict()

        assert envelope["resource_boundaries"] == {
            "agent_attempts": 4,
            "wall_clock_seconds": 120.0,
            "provider_tokens": 9000,
        }


def test_wall_clock_deadline_pauses_before_starting_an_agent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            {"wall_clock_seconds": 0.001},
        )
        agent = ResourceAgent()
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)
        time.sleep(0.01)

        with pytest.raises(RunPaused, match="wall_clock_seconds"):
            runner.run(contract)

        paused = runner.report(prepared.run_id)
        assert paused.status == "paused_deadline"
        assert paused.stop is not None
        assert paused.stop.reason == "deadline"
        assert paused.stop.boundary == "wall_clock_seconds"
        assert paused.stop.role == "test_designer"
        assert agent.calls == []


def test_harness_time_boundary_pauses_before_the_next_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            {"harness_seconds": 0.000001},
        )
        agent = ResourceAgent()
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)

        with pytest.raises(RunPaused, match="harness_seconds"):
            runner.run(contract)

        paused = runner.report(prepared.run_id)
        assert paused.status == "paused_resource"
        assert paused.stop is not None
        assert paused.stop.boundary == "harness_seconds"
        assert paused.stop.stage == "green"
        assert [item[1] for item in agent.calls] == [
            "test_designer",
            "implementer",
        ]
        assert len(paused.todos[0].evidence) == 1


def test_reported_token_boundary_pauses_before_the_next_provider_call() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            {"provider_tokens": 5},
        )
        agent = ResourceAgent(
            usage_by_role={
                "test_designer": {
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "total_tokens": 6,
                }
            }
        )
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)

        with pytest.raises(RunPaused, match="provider_tokens"):
            runner.run(contract)

        paused = runner.report(prepared.run_id)
        assert paused.status == "paused_resource"
        assert paused.stop is not None
        assert paused.stop.boundary == "provider_tokens"
        assert paused.stop.role == "implementer"
        assert [item[1] for item in agent.calls] == ["test_designer"]
        assert paused.attempts[0].usage == {
            "input_tokens": 4,
            "output_tokens": 2,
            "total_tokens": 6,
        }


def test_provider_quota_pauses_without_consuming_a_code_attempt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository, {})
        agent = QuotaOnceAgent()
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)

        with pytest.raises(RunPaused, match="provider_quota"):
            runner.run(contract)

        paused = runner.report(prepared.run_id)
        assert paused.status == "paused_provider_quota"
        assert paused.stop is not None
        assert paused.stop.reason == "provider_quota"
        assert paused.stop.role == "implementer"
        assert paused.stop.provider == "claude-code"
        assert paused.stop.model == "sonnet"
        assert paused.stop.known_usage == {"total_tokens": 7}
        assert [attempt.role for attempt in paused.attempts] == ["test_designer"]
        assert not (Path(paused.todos[0].worktree) / "greeting.py").exists()

        runner.resume(prepared.run_id)
        completed = runner.run(contract)

        assert completed.status == "merge_ready"
        assert completed.stop is None
        assert [item[1] for item in agent.calls].count("implementer") == 2
        assert {item[2] for item in agent.calls} == {"claude-code"}
        assert {item[3] for item in agent.calls} == {"sonnet"}


def test_harness_gate_failure_has_a_distinct_stop_reason() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository, {})
        runner = GoalRunner(
            state_dir=root / "state",
            agent=BrokenImplementationAgent(),
        )
        prepared = runner.prepare(contract)

        with pytest.raises(GateError, match="GREEN gate failed"):
            runner.run(contract)

        failed = runner.report(prepared.run_id)
        assert failed.status == "failed_harness"
        assert failed.stop is not None
        assert failed.stop.reason == "harness_failure"
        assert failed.stop.stage == "green"
        assert failed.stop.resumable is False


def test_daemon_restart_rejects_paused_legacy_state_without_resuming() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository, {"agent_attempts": 2})
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        first_agent = ResourceAgent()
        first_daemon = AgentDaemon(
            state_dir=state_dir,
            agent=first_agent,
            socket_path=socket_path,
        )
        first_thread = threading.Thread(
            target=first_daemon.serve_forever,
            daemon=True,
        )
        first_thread.start()
        first_client = DaemonClient(socket_path)
        _wait_until(first_client.ping)
        try:
            submitted = first_client.submit(contract)
            _wait_until(
                lambda: first_client.status(submitted.run_id).status
                == "paused_resource",
                timeout=20,
            )
            paused = first_client.status(submitted.run_id)
            assert paused.reason == "resource_boundary"
            assert paused.boundary == "agent_attempts"
            assert paused.role == "verifier"
            assert paused.provider == "claude-code"
            assert paused.model == "sonnet"
            assert paused.resumable is True
        finally:
            first_daemon.shutdown()
            first_thread.join(timeout=5)
        assert not first_thread.is_alive()

        second_agent = ResourceAgent()
        with pytest.raises(DaemonError) as captured:
            AgentDaemon(
                state_dir=state_dir,
                agent=second_agent,
                socket_path=socket_path,
            )

        assert captured.value.code == "incompatible_state"
        assert second_agent.calls == []


def test_paused_todo_does_not_cancel_independent_work_or_unlock_dependents() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_multi_todo_contract(root, repository)
        agent = ParallelQuotaAgent()
        runner = GoalRunner(
            state_dir=root / "state",
            agent=agent,
            max_workers=2,
        )
        prepared = runner.prepare(contract)

        with pytest.raises(RunPaused, match="provider_quota"):
            runner.run(contract)

        report = runner.report(prepared.run_id)
        todos = {todo.todo_id: todo for todo in report.todos}
        assert report.status == "paused_provider_quota"
        assert todos["T-1"].status == "paused"
        assert todos["T-2"].status == "verified"
        assert todos["T-3"].status == "pending"
        assert ("T-2", "verifier") in agent.calls
        assert not any(todo_id == "T-3" for todo_id, _ in agent.calls)


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (ConnectionError, FileNotFoundError):
            pass
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


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
                    "commands": {
                        "unit": {"argv": command, "approved": True},
                    },
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


def _write_contract(
    root: Path,
    repository: Path,
    resources: dict[str, object],
) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "resource-goal",
                    "title": "Bound unattended work",
                    "requirement": "Implement a greeting within approved boundaries.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting returns hello."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc),
                },
                "agent": {
                    "provider": "claude-code",
                    "model": "sonnet",
                },
                "resources": resources,
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Implement greeting"},
                "test": {
                    "command": command,
                    "allowed_paths": ["tests/test_greeting.py"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _write_multi_todo_contract(root: Path, repository: Path) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "resource-dag-goal",
                    "title": "Respect resource boundaries across a DAG",
                    "requirement": "Complete independent work without unlocking dependents.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting works."},
                        {"id": "AC-2", "statement": "Farewell works."},
                        {"id": "AC-3", "statement": "Welcome works."},
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc),
                },
                "agent": {
                    "provider": "claude-code",
                    "model": "sonnet",
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
                    {
                        "id": "T-3",
                        "title": "Implement welcome",
                        "depends_on": ["T-1"],
                        "test_ids": ["AC-3"],
                        "test": {
                            "command": command,
                            "allowed_paths": ["tests/test_welcome.py"],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
