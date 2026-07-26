from __future__ import annotations

import json
import os
import select
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


class UnusedAgentAdapter:
    def run(self, request: AgentRequest):
        raise AssertionError(f"unexpected Agent role: {request.role}")


class GreetingAgentAdapter:
    def run(self, request: AgentRequest) -> AgentResult:
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting():\n"
                "    assert greeting('Ada') == 'Hello, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "greeting.py").write_text(
                "def greeting(name):\n"
                "    return f'Hello, {name}!'\n",
                encoding="utf-8",
            )
        return AgentResult(
            session_id=f"mcp-{request.role}",
            final_output="completed",
        )


def test_stdio_mcp_lists_tools_and_reports_daemon_status() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=UnusedAgentAdapter(),
            socket_path=socket_path,
        )
        daemon_thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        daemon_thread.start()
        _wait_until(DaemonClient(socket_path).ping)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "aiwb.mcp_server",
                "--socket",
                str(socket_path),
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            initialized = _request(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "unsupported-test-version",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1"},
                    },
                },
            )
            assert initialized["result"]["serverInfo"]["name"] == "ai-workbench"
            assert initialized["result"]["protocolVersion"] == "2025-06-18"
            assert initialized["result"]["capabilities"] == {"tools": {}}
            _notify(
                server,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            listed = _request(
                server,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )
            assert [tool["name"] for tool in listed["result"]["tools"]] == [
                "aiwb_daemon_status",
                "aiwb_goal_report",
                "aiwb_goal_status",
                "aiwb_goal_submit",
            ]

            called = _request(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "aiwb_daemon_status",
                        "arguments": {},
                    },
                },
            )
            assert called["result"]["isError"] is False
            assert json.loads(called["result"]["content"][0]["text"]) == {
                "socket": str(socket_path.resolve()),
                "status": "ok",
            }
            unknown = _request(
                server,
                {"jsonrpc": "2.0", "id": 4, "method": "unknown/method"},
            )
            assert unknown["error"]["code"] == -32601
        finally:
            server.terminate()
            server.wait(timeout=5)
            daemon.shutdown()
            daemon_thread.join(timeout=5)

        assert not daemon_thread.is_alive()


def test_stdio_mcp_submits_and_observes_a_complete_goal() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=GreetingAgentAdapter(),
            socket_path=socket_path,
        )
        daemon_thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        daemon_thread.start()
        _wait_until(DaemonClient(socket_path).ping)
        server = _start_mcp(socket_path)
        try:
            _request(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
            )
            submitted = _tool_value(
                _request(
                    server,
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "aiwb_goal_submit",
                            "arguments": {"contract_path": str(contract)},
                        },
                    },
                )
            )
            run_id = submitted["run_id"]

            status = None
            deadline = time.monotonic() + 20
            request_id = 3
            while time.monotonic() < deadline:
                status = _tool_value(
                    _request(
                        server,
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "tools/call",
                            "params": {
                                "name": "aiwb_goal_status",
                                "arguments": {"run_id": run_id},
                            },
                        },
                    )
                )
                request_id += 1
                if status["status"] == "merge_ready":
                    break
                time.sleep(0.05)
            assert status is not None
            assert status["status"] == "merge_ready"

            report = _tool_value(
                _request(
                    server,
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": "aiwb_goal_report",
                            "arguments": {"run_id": run_id},
                        },
                    },
                )
            )
            assert report["status"] == "merge_ready"
            assert report["goal_id"] == "mcp-greeting-goal"
            assert {
                item["role"]
                for item in report["consumption"]["agents"]
            } == {
                "test_designer",
                "implementer",
                "verifier",
                "candidate_verifier",
            }
            assert report["consumption"]["harnesses"][0][
                "execution_count"
            ] == 5

            invalid = _request(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": request_id + 1,
                    "method": "tools/call",
                    "params": {
                        "name": "aiwb_goal_status",
                        "arguments": {},
                    },
                },
            )
            assert invalid["result"]["isError"] is True
            assert _tool_value(invalid)["error"] == "operation_error"
        finally:
            server.terminate()
            server.wait(timeout=5)
            daemon.shutdown()
            daemon_thread.join(timeout=5)

        assert not daemon_thread.is_alive()


def _request(server: subprocess.Popen[str], value):
    _notify(server, value)
    assert server.stdout is not None
    readable, _, _ = select.select([server.stdout], [], [], 5)
    if not readable:
        stderr = server.stderr.read() if server.stderr is not None else ""
        raise AssertionError(f"MCP response timed out: {stderr}")
    return json.loads(server.stdout.readline())


def _start_mcp(socket_path: Path) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "aiwb.mcp_server",
            "--socket",
            str(socket_path),
        ],
        cwd=str(TOOL_ROOT),
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _tool_value(response):
    return json.loads(response["result"]["content"][0]["text"])


def _notify(server: subprocess.Popen[str], value) -> None:
    assert server.stdin is not None
    server.stdin.write(json.dumps(value) + "\n")
    server.stdin.flush()


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
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    test_command = [sys.executable, "-m", "pytest", "-q"]
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {
                        "unit": {"argv": test_command, "approved": True},
                    },
                    "skills": {},
                },
                "harness": {
                    "allowed_kubernetes_contexts": [],
                    "profiles": {},
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


def _write_contract(root: Path, repository: Path) -> Path:
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "mcp-greeting-goal",
                    "title": "Add a greeting",
                    "requirement": "Expose a greeting for a supplied name.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting includes the name."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Implement greeting"},
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q"],
                    "allowed_paths": ["tests/test_greeting.py"],
                },
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
