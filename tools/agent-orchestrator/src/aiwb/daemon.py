from __future__ import annotations

import json
import os
import socket
import socketserver
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .agent import AgentAdapter
from .runner import GoalRunner, RunReport


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    status: str
    error: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunStatus":
        return cls(
            run_id=str(value["run_id"]),
            status=str(value["status"]),
            error=str(value.get("error", "")),
        )


class DaemonError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DaemonClient:
    """Small control interface over the daemon's local Unix socket."""

    def __init__(self, socket_path: Path, timeout_seconds: float = 5) -> None:
        self._socket_path = Path(socket_path).expanduser()
        self._timeout_seconds = timeout_seconds

    def ping(self) -> bool:
        try:
            result = self._request("ping")
        except (OSError, DaemonError):
            return False
        return result.get("status") == "ok"

    def submit(self, contract_path: Path) -> RunStatus:
        result = self._request(
            "submit",
            contract_path=str(Path(contract_path).expanduser().resolve()),
        )
        return RunStatus.from_dict(result)

    def status(self, run_id: str) -> RunStatus:
        return RunStatus.from_dict(self._request("status", run_id=run_id))

    def report(self, run_id: str) -> RunReport:
        return RunReport.from_dict(self._request("report", run_id=run_id))

    def _request(self, method: str, **parameters: object) -> Mapping[str, object]:
        request = json.dumps({"method": method, "params": parameters}) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self._timeout_seconds)
            connection.connect(str(self._socket_path))
            connection.sendall(request.encode("utf-8"))
            response_bytes = bytearray()
            while not response_bytes.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response_bytes.extend(chunk)
                if len(response_bytes) > 16 * 1024 * 1024:
                    raise DaemonError("response_too_large", "daemon response exceeded 16 MiB")

        if not response_bytes:
            raise ConnectionError("daemon closed the socket without a response")
        try:
            response = json.loads(response_bytes)
        except json.JSONDecodeError as error:
            raise DaemonError("invalid_response", "daemon returned invalid JSON") from error
        if not isinstance(response, dict):
            raise DaemonError("invalid_response", "daemon response must be a mapping")
        if response.get("ok") is not True:
            error_data = response.get("error", {})
            if not isinstance(error_data, dict):
                error_data = {}
            raise DaemonError(
                str(error_data.get("code", "daemon_error")),
                str(error_data.get("message", "daemon request failed")),
            )
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise DaemonError("invalid_response", "daemon result must be a mapping")
        return result


class AgentDaemon:
    """Own background Run execution and expose it over a local Unix socket."""

    def __init__(
        self,
        state_dir: Path,
        agent: AgentAdapter,
        socket_path: Optional[Path] = None,
        max_workers: int = 1,
        todo_workers: int = 2,
        image_poll_interval_seconds: float = 5.0,
        janitor_interval_seconds: float = 60.0,
    ) -> None:
        if (
            max_workers <= 0
            or todo_workers <= 0
            or image_poll_interval_seconds <= 0
            or janitor_interval_seconds <= 0
        ):
            raise ValueError("worker counts and intervals must be positive")
        self._state_dir = Path(state_dir).expanduser().resolve()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.socket_path = (
            Path(socket_path).expanduser().resolve()
            if socket_path
            else self._state_dir / "run" / "daemon.sock"
        )
        self._runner = GoalRunner(
            self._state_dir,
            agent,
            max_workers=todo_workers,
            image_poll_interval_seconds=image_poll_interval_seconds,
        )
        self._jobs = _JobStore(self._state_dir / "daemon.db")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="aiwb-run",
        )
        self._futures: Dict[str, Future[None]] = {}
        self._futures_lock = threading.Lock()
        self._janitor_interval_seconds = janitor_interval_seconds
        self._janitor_stop = threading.Event()
        self._janitor_thread: Optional[threading.Thread] = None
        self._server: Optional[_ThreadingUnixServer] = None

    def serve_forever(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._reject_live_or_remove_stale_socket()
        server = _ThreadingUnixServer(str(self.socket_path), _RequestHandler)
        server.agent_daemon = self
        self._server = server
        os.chmod(self.socket_path, 0o600)
        self._runner.sweep_kubernetes()
        self._janitor_thread = threading.Thread(
            target=self._janitor_loop,
            name="aiwb-kubernetes-janitor",
            daemon=True,
        )
        self._janitor_thread.start()
        self._recover_jobs()
        try:
            server.serve_forever(poll_interval=0.05)
        finally:
            self._janitor_stop.set()
            if self._janitor_thread is not None:
                self._janitor_thread.join(timeout=5)
            server.server_close()
            self._executor.shutdown(wait=True)
            self._server = None
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def shutdown(self) -> None:
        self._janitor_stop.set()
        server = self._server
        if server is not None:
            server.shutdown()

    def _janitor_loop(self) -> None:
        while not self._janitor_stop.wait(self._janitor_interval_seconds):
            self._runner.sweep_kubernetes()

    def _dispatch(self, request: object) -> Mapping[str, object]:
        if not isinstance(request, dict):
            raise DaemonError("invalid_request", "request must be a mapping")
        method = request.get("method")
        parameters = request.get("params", {})
        if not isinstance(parameters, dict):
            raise DaemonError("invalid_request", "params must be a mapping")

        if method == "ping":
            return {"status": "ok"}
        if method == "submit":
            contract_path = _required_parameter(parameters, "contract_path")
            prepared = self._runner.prepare(Path(contract_path))
            status = self._jobs.submit(prepared.run_id, Path(contract_path))
            self._schedule(prepared.run_id)
            return asdict(status)
        if method == "status":
            return asdict(self._jobs.status(_required_parameter(parameters, "run_id")))
        if method == "report":
            run_id = _required_parameter(parameters, "run_id")
            report = self._jobs.report(run_id)
            if report is None:
                try:
                    report = self._runner.report(run_id)
                except KeyError as error:
                    raise DaemonError(
                        "report_not_ready", f"Run {run_id!r} has no report yet"
                    ) from error
            return report.to_dict()
        raise DaemonError("method_not_found", f"unknown daemon method: {method!r}")

    def _schedule(self, run_id: str) -> None:
        with self._futures_lock:
            existing = self._futures.get(run_id)
            if existing is not None and not existing.done():
                return
            future = self._executor.submit(self._execute, run_id)
            self._futures[run_id] = future
            future.add_done_callback(lambda _: self._forget(run_id))

    def _execute(self, run_id: str) -> None:
        job = self._jobs.get(run_id)
        if job["status"] == "merge_ready":
            return
        self._jobs.mark_running(run_id)
        try:
            report = self._runner.run(Path(job["contract_path"]))
        except Exception as error:
            self._jobs.mark_blocked(run_id, str(error))
            return
        self._jobs.complete(run_id, report)

    def _forget(self, run_id: str) -> None:
        with self._futures_lock:
            self._futures.pop(run_id, None)

    def _recover_jobs(self) -> None:
        for run_id in self._jobs.recoverable_run_ids():
            self._jobs.mark_queued(run_id)
            self._schedule(run_id)

    def _reject_live_or_remove_stale_socket(self) -> None:
        if not self.socket_path.exists():
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(self.socket_path))
        except OSError:
            self.socket_path.unlink()
        else:
            raise RuntimeError(f"daemon socket is already active: {self.socket_path}")
        finally:
            probe.close()


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    agent_daemon: AgentDaemon


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request_bytes = self.rfile.readline(1024 * 1024)
            if not request_bytes.endswith(b"\n"):
                raise DaemonError("invalid_request", "request must end with a newline")
            request = json.loads(request_bytes)
            result = self.server.agent_daemon._dispatch(request)
            response: Mapping[str, object] = {"ok": True, "result": result}
        except DaemonError as error:
            response = {
                "ok": False,
                "error": {"code": error.code, "message": str(error)},
            }
        except json.JSONDecodeError:
            response = {
                "ok": False,
                "error": {"code": "invalid_json", "message": "request is not valid JSON"},
            }
        except Exception as error:
            response = {
                "ok": False,
                "error": {"code": "internal_error", "message": str(error)},
            }
        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))


class _JobStore:
    def __init__(self, database: Path) -> None:
        self._database = database
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daemon_jobs (
                    run_id TEXT PRIMARY KEY,
                    contract_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def submit(self, run_id: str, contract_path: Path) -> RunStatus:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO daemon_jobs (
                    run_id, contract_path, status, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?)
                """,
                (run_id, str(contract_path.resolve()), now, now),
            )
        return self.status(run_id)

    def get(self, run_id: str) -> Mapping[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM daemon_jobs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise DaemonError("run_not_found", f"unknown Run: {run_id}")
        return dict(row)

    def status(self, run_id: str) -> RunStatus:
        record = self.get(run_id)
        return RunStatus(
            run_id=run_id,
            status=record["status"],
            error=record["error"] or "",
        )

    def report(self, run_id: str) -> Optional[RunReport]:
        record = self.get(run_id)
        if not record["report_json"]:
            return None
        value = json.loads(record["report_json"])
        if not isinstance(value, dict):
            raise DaemonError("invalid_report", f"stored report for {run_id!r} is invalid")
        return RunReport.from_dict(value)

    def recoverable_run_ids(self) -> List[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM daemon_jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
        return [row["run_id"] for row in rows]

    def mark_queued(self, run_id: str) -> None:
        self._update(run_id, status="queued", error=None)

    def mark_running(self, run_id: str) -> None:
        self._update(run_id, status="running", error=None)

    def mark_blocked(self, run_id: str, error: str) -> None:
        self._update(run_id, status="blocked", error=error)

    def complete(self, run_id: str, report: RunReport) -> None:
        self._update(
            run_id,
            status="merge_ready",
            error=None,
            report_json=json.dumps(report.to_dict()),
        )

    def _update(self, run_id: str, **values: object) -> None:
        values["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = list(values.values()) + [run_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE daemon_jobs SET {assignments} WHERE run_id = ?",
                parameters,
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection


def _required_parameter(parameters: Mapping[str, object], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value:
        raise DaemonError("invalid_request", f"{name} must be a non-empty string")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
