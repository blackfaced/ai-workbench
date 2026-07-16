from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
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


class BlockingAgentAdapter:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.roles = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.roles.append(request.role)
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            self.started.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("test did not release Test Designer")
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting_includes_the_name():\n"
                "    assert greeting('Ada') == 'Hello, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "greeting.py").write_text(
                "def greeting(name):\n"
                "    return f'Hello, {name}!'\n",
                encoding="utf-8",
            )
        elif request.role != "verifier":
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"daemon-{request.role}-session",
            final_output=f"{request.role} completed",
        )


def test_daemon_accepts_a_goal_and_reports_background_completion() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        repository.mkdir()
        test_command = [sys.executable, "-m", "pytest", "-q"]
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AI Workbench Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n.pytest_cache/\n",
            encoding="utf-8",
        )
        (repository / "README.md").write_text("# Fixture project\n", encoding="utf-8")
        _write_policy(repository, test_command)
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Initial fixture")

        contract_path = root / "contract.yaml"
        contract_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "goal": {
                        "id": "daemon-greeting-goal",
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
                        "approved_at": datetime(
                            2026,
                            7,
                            15,
                            tzinfo=timezone.utc,
                        ),
                    },
                    "project": {
                        "repo": str(repository),
                        "base_ref": "main",
                    },
                    "todo": {
                        "id": "T-1",
                        "title": "Implement the greeting behavior",
                    },
                    "test": {
                        "command": test_command,
                        "allowed_paths": ["tests/**"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        adapter = BlockingAgentAdapter()
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=adapter,
            socket_path=socket_path,
        )
        daemon_thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        daemon_thread.start()
        client = DaemonClient(socket_path)

        try:
            _wait_until(client.ping)
            submitted = client.submit(contract_path)
            assert adapter.started.wait(timeout=2)
            assert submitted.run_id.startswith("daemon-greeting-goal-")
            assert client.status(submitted.run_id).status == "running"
            live_report = client.report(submitted.run_id)
            assert live_report.status == "approved"
            assert live_report.goal_id == "daemon-greeting-goal"

            adapter.release.set()
            _wait_until(
                lambda: client.status(submitted.run_id).status == "merge_ready",
                timeout=20,
            )
            report = client.report(submitted.run_id)

            assert report.status == "merge_ready"
            assert report.goal_id == "daemon-greeting-goal"
            assert adapter.roles == ["test_designer", "implementer", "verifier"]
            assert set(report.sessions) == {
                "test_designer",
                "implementer",
                "verifier",
            }
        finally:
            adapter.release.set()
            daemon.shutdown()
            daemon_thread.join(timeout=5)

        assert not daemon_thread.is_alive()
        assert not socket_path.exists()


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


def _write_policy(repository: Path, command) -> None:
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
