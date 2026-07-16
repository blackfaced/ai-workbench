from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentDaemon, AgentRequest, DaemonClient  # noqa: E402


class UnusedAgentAdapter:
    def run(self, request: AgentRequest):
        raise AssertionError(f"unexpected Agent role: {request.role}")


def test_cli_reports_a_reachable_daemon() -> None:
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
        try:
            _wait_until(DaemonClient(socket_path).ping)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aiwb",
                    "daemon",
                    "status",
                    "--state-dir",
                    str(state_dir),
                ],
                cwd=str(TOOL_ROOT),
                env=environment,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert completed.returncode == 0, completed.stderr
            assert json.loads(completed.stdout) == {
                "socket": str(socket_path.resolve()),
                "status": "ok",
            }
        finally:
            daemon.shutdown()
            daemon_thread.join(timeout=5)


def test_cli_can_sweep_kubernetes_leases_without_a_daemon() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "janitor",
                "sweep",
                "--state-dir",
                str(state_dir),
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {
            "cleaned": 0,
            "failed": 0,
            "retained": 0,
            "scanned": 0,
        }


def _wait_until(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("daemon did not become ready")
