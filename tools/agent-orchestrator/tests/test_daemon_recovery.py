from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentDaemon,
    AgentRequest,
    AgentResult,
    DaemonClient,
)


class ProcessAgentAdapter:
    def __init__(self, block_implementer: bool, marker_dir: Path) -> None:
        self.block_implementer = block_implementer
        self.marker_dir = marker_dir

    def run(self, request: AgentRequest) -> AgentResult:
        worktree = Path(request.worktree)
        (self.marker_dir / f"{os.getpid()}-{request.role}").write_text(
            request.role,
            encoding="utf-8",
        )
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting_includes_the_name():\n"
                "    assert greeting('Ada') == 'Hello, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            if self.block_implementer:
                (self.marker_dir / "blocked-implementer").write_text(
                    str(os.getpid()),
                    encoding="utf-8",
                )
                while True:
                    time.sleep(1)
            (worktree / "greeting.py").write_text(
                "def greeting(name):\n"
                "    return f'Hello, {name}!'\n",
                encoding="utf-8",
            )
        elif request.role != "verifier":
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"{os.getpid()}-{request.role}",
            final_output=f"{request.role} completed",
        )


def test_new_daemon_process_recovers_a_run_interrupted_after_red() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        state_dir = root / "state"
        marker_dir = root / "markers"
        socket_path = state_dir / "run" / "daemon.sock"
        repository.mkdir()
        marker_dir.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AI Workbench Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n.pytest_cache/\n",
            encoding="utf-8",
        )
        (repository / "README.md").write_text("# Fixture project\n", encoding="utf-8")
        _write_policy(repository)
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Initial fixture")
        contract_path = _write_contract(root, repository)

        context = multiprocessing.get_context("spawn")
        first = context.Process(
            target=_serve,
            args=(state_dir, socket_path, marker_dir, True),
        )
        first.start()
        client = DaemonClient(socket_path)

        try:
            _wait_until(client.ping)
            submitted = client.submit(contract_path)
            _wait_until(lambda: (marker_dir / "blocked-implementer").exists(), timeout=15)
            assert client.status(submitted.run_id).status == "running"

            first_pid = first.pid
            first.terminate()
            first.join(timeout=5)
            assert not first.is_alive()

            second = context.Process(
                target=_serve,
                args=(state_dir, socket_path, marker_dir, False),
            )
            second.start()
            try:
                _wait_until(client.ping)
                _wait_until(
                    lambda: client.status(submitted.run_id).status == "merge_ready",
                    timeout=20,
                )
                report = client.report(submitted.run_id)
            finally:
                second.terminate()
                second.join(timeout=5)

            assert report.status == "merge_ready"
            assert report.sessions["test_designer"].startswith(f"{first_pid}-")
            assert not report.sessions["implementer"].startswith(f"{first_pid}-")
            assert not report.sessions["verifier"].startswith(f"{first_pid}-")
        finally:
            if first.is_alive():
                first.terminate()
                first.join(timeout=5)


def _serve(
    state_dir: Path,
    socket_path: Path,
    marker_dir: Path,
    block_implementer: bool,
) -> None:
    AgentDaemon(
        state_dir=state_dir,
        agent=ProcessAgentAdapter(block_implementer, marker_dir),
        socket_path=socket_path,
    ).serve_forever()


def _write_contract(root: Path, repository: Path) -> Path:
    contract_path = root / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "recovery-greeting-goal",
                    "title": "Add a greeting",
                    "requirement": "Expose a greeting function for a supplied name.",
                    "acceptance": [
                        {
                            "id": "AC-1",
                            "statement": "Greeting includes the supplied name.",
                        }
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Implement the greeting behavior"},
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q"],
                    "allowed_paths": ["tests/**"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract_path


def _write_policy(repository: Path) -> None:
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
                "harness": {"profiles": {"local": {"environment": "local"}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _wait_until(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (ConnectionError, FileNotFoundError) as error:
            last_error = error
        time.sleep(0.02)
    raise AssertionError(f"condition not met before timeout: {last_error}")


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
