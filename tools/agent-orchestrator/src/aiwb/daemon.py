from __future__ import annotations

import json
import os
import fcntl
import socket
import socketserver
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .agent import AgentAdapter
from .admission import (
    ADMISSION_SCHEMA_VERSION,
    Admission,
    AdmissionError,
    AdmissionRequest,
    LeaseConflictError,
    RunLease,
    SQLiteRunLedger,
)
from .evidence import EvidencePayload, EvidencePruneReport
from .runner import GoalRunner, RunReport
from .state import DurableStateSetup, StateFormat, StateResetError


_INCOMPATIBLE_STATE_MESSAGE = (
    "incompatible legacy Run state; no migration is available; review and reset "
    "it with aiwb setup --repo <path> --state-dir <state-dir>"
)


ENGINE_VERSION = "0.1.0"
TRANSITION_POLICY_VERSION = "strict-v1"


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    status: str
    error: str = ""
    reason: str = ""
    boundary: str = ""
    todo_id: str = ""
    role: str = ""
    stage: str = ""
    provider: str = ""
    model: str = ""
    resumable: bool = False
    snapshot_id: str = ""
    goal_id: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunStatus":
        return cls(
            run_id=str(value["run_id"]),
            status=str(value["status"]),
            error=str(value.get("error", "")),
            reason=str(value.get("reason", "")),
            boundary=str(value.get("boundary", "")),
            todo_id=str(value.get("todo_id", "")),
            role=str(value.get("role", "")),
            stage=str(value.get("stage", "")),
            provider=str(value.get("provider", "")),
            model=str(value.get("model", "")),
            resumable=bool(value.get("resumable", False)),
            snapshot_id=str(value.get("snapshot_id", "")),
            goal_id=str(value.get("goal_id", "")),
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

    def submit(
        self,
        contract_path: Path,
        *,
        workflow_path: object = None,
        idempotency_key: object = None,
    ) -> RunStatus:
        result = self._request(
            "submit",
            contract_path=str(Path(contract_path).expanduser().resolve()),
            workflow_path=(
                str(Path(workflow_path).expanduser().resolve())
                if isinstance(workflow_path, Path)
                else workflow_path
            ),
            idempotency_key=idempotency_key,
        )
        return RunStatus.from_dict(result)

    def status(self, run_id: str) -> RunStatus:
        return RunStatus.from_dict(self._request("status", run_id=run_id))

    def resume(self, run_id: str) -> RunStatus:
        return RunStatus.from_dict(self._request("resume", run_id=run_id))

    def report(self, run_id: str) -> RunReport:
        return RunReport.from_dict(self._request("report", run_id=run_id))

    def evidence(self, run_id: str, artifact_id: str) -> EvidencePayload:
        return EvidencePayload.from_dict(
            self._request(
                "evidence",
                run_id=run_id,
                artifact_id=artifact_id,
            )
        )

    def prune_evidence(self, older_than_days: int) -> EvidencePruneReport:
        value = self._request(
            "evidence_prune",
            older_than_days=older_than_days,
        )
        return EvidencePruneReport(
            scanned=int(value["scanned"]),
            deleted=int(value["deleted"]),
            retained=int(value["retained"]),
            older_than_days=int(value["older_than_days"]),
        )

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
        lease_seconds: float = 2.0,
        engine_version: str = ENGINE_VERSION,
        transition_policy_version: str = TRANSITION_POLICY_VERSION,
    ) -> None:
        if (
            max_workers <= 0
            or todo_workers <= 0
            or image_poll_interval_seconds <= 0
            or janitor_interval_seconds <= 0
            or lease_seconds <= 0
        ):
            raise ValueError("worker counts and intervals must be positive")
        self._state_dir = Path(state_dir).expanduser().resolve()
        try:
            state_assessment = DurableStateSetup().inspect(self._state_dir)
        except StateResetError as error:
            raise DaemonError(
                "incompatible_state",
                _INCOMPATIBLE_STATE_MESSAGE,
            ) from error
        if state_assessment.format == StateFormat.INCOMPATIBLE_LEGACY:
            raise DaemonError(
                "incompatible_state",
                _INCOMPATIBLE_STATE_MESSAGE,
            )
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.socket_path = (
            Path(socket_path).expanduser().resolve()
            if socket_path
            else self._state_dir / "run" / "daemon.sock"
        )
        self._ledger = SQLiteRunLedger(self._state_dir / "run-ledger.db")
        self._runner = GoalRunner(
            self._state_dir,
            agent,
            max_workers=todo_workers,
            image_poll_interval_seconds=image_poll_interval_seconds,
            ledger=self._ledger,
        )
        self._admission = Admission(
            self._ledger,
            engine_version=engine_version,
            transition_policy_version=transition_policy_version,
        )
        self._engine_version = engine_version
        self._transition_policy_version = transition_policy_version
        self._lease_seconds = lease_seconds
        self._owner_id = f"daemon-{os.getpid()}-{uuid.uuid4().hex}"
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="aiwb-run",
        )
        self._futures: Dict[str, Future[None]] = {}
        self._futures_lock = threading.Lock()
        self._janitor_interval_seconds = janitor_interval_seconds
        self._janitor_stop = threading.Event()
        self._janitor_thread: Optional[threading.Thread] = None
        self._queue_thread: Optional[threading.Thread] = None
        self._server: Optional[_ThreadingUnixServer] = None
        self._process_lock_file: Optional[Any] = None

    def serve_forever(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_process_lock()
        try:
            self._reject_live_or_remove_stale_socket()
            server = _ThreadingUnixServer(str(self.socket_path), _RequestHandler)
        except Exception:
            self._release_process_lock()
            raise
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
        self._queue_thread = threading.Thread(
            target=self._queue_loop,
            name="aiwb-run-queue",
            daemon=True,
        )
        self._queue_thread.start()
        self._schedule_queued_runs()
        try:
            server.serve_forever(poll_interval=0.05)
        finally:
            self._janitor_stop.set()
            if self._janitor_thread is not None:
                self._janitor_thread.join(timeout=5)
            if self._queue_thread is not None:
                self._queue_thread.join(timeout=5)
            server.server_close()
            self._executor.shutdown(wait=True)
            self._server = None
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass
            self._release_process_lock()

    def shutdown(self) -> None:
        self._janitor_stop.set()
        server = self._server
        if server is not None:
            server.shutdown()

    def _janitor_loop(self) -> None:
        while not self._janitor_stop.wait(self._janitor_interval_seconds):
            self._runner.sweep_kubernetes()

    def _queue_loop(self) -> None:
        interval = min(0.2, self._lease_seconds / 4)
        while not self._janitor_stop.wait(interval):
            self._schedule_queued_runs()

    def _schedule_queued_runs(self) -> None:
        for run in self._ledger.queued_runs():
            self._schedule(run.run_id)

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
            workflow_value = parameters.get("workflow_path")
            idempotency_value = parameters.get("idempotency_key")
            if workflow_value is not None and not isinstance(workflow_value, str):
                raise DaemonError("invalid_request", "workflow_path must be text or null")
            if idempotency_value is not None and not isinstance(idempotency_value, str):
                raise DaemonError("invalid_request", "idempotency_key must be text or null")
            try:
                admitted = self._admission.admit(
                    AdmissionRequest(
                        contract_path=Path(contract_path),
                        workflow_path=(Path(workflow_value) if workflow_value else None),
                        idempotency_key=idempotency_value or None,
                    )
                )
            except AdmissionError as error:
                raise DaemonError("admission_error", str(error)) from error
            self._schedule(admitted.run_id)
            return asdict(self._status(admitted.run_id))
        if method == "status":
            return asdict(self._status(_required_parameter(parameters, "run_id")))
        if method == "resume":
            run_id = _required_parameter(parameters, "run_id")
            try:
                self._runner.resume(run_id)
                self._ledger.requeue(run_id)
            except (KeyError, ValueError) as error:
                raise DaemonError("run_not_resumable", str(error)) from error
            self._schedule(run_id)
            return asdict(self._status(run_id))
        if method == "report":
            run_id = _required_parameter(parameters, "run_id")
            try:
                report = self._runner.report(run_id)
            except KeyError as error:
                raise DaemonError(
                    "report_not_ready", f"Run {run_id!r} has no report yet"
                ) from error
            return report.to_dict()
        if method == "evidence":
            run_id = _required_parameter(parameters, "run_id")
            artifact_id = _required_parameter(parameters, "artifact_id")
            try:
                return self._runner.evidence(run_id, artifact_id).to_dict()
            except KeyError as error:
                raise DaemonError("evidence_not_found", str(error)) from error
        if method == "evidence_prune":
            older_than_days = parameters.get("older_than_days")
            if (
                isinstance(older_than_days, bool)
                or not isinstance(older_than_days, int)
                or older_than_days <= 0
            ):
                raise DaemonError(
                    "invalid_request",
                    "older_than_days must be a positive integer",
                )
            return asdict(self._runner.prune_evidence(older_than_days))
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
        lease = self._ledger.claim(
            run_id,
            owner_id=self._owner_id,
            lease_seconds=self._lease_seconds,
            supported_engine_versions={self._engine_version},
            supported_admission_schema_versions={ADMISSION_SCHEMA_VERSION},
            supported_transition_policy_versions={self._transition_policy_version},
        )
        if lease is None:
            return
        run = self._ledger.run(run_id)
        snapshot = self._ledger.execution_snapshot(run.snapshot_id)
        heartbeat_stop = threading.Event()
        lease_state: List[RunLease] = [lease]
        heartbeat = threading.Thread(
            target=self._renew_lease,
            args=(lease_state, heartbeat_stop),
            name=f"aiwb-lease-{run_id}",
            daemon=True,
        )
        heartbeat.start()
        report: Optional[RunReport] = None
        error_text = ""
        try:
            report = self._runner.run_snapshot(
                snapshot,
                run_id=run_id,
                lease=lease,
                mutation_guard=lambda: self._ledger.prove(lease_state[0]),
            )
        except Exception as error:
            error_text = str(error)
            try:
                report = self._runner.report(run_id)
            except KeyError:
                report = None
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(1.0, self._lease_seconds))
        status = (
            report.status
            if report is not None and report.status != "running"
            else "blocked"
        )
        try:
            self._ledger.transition(
                run_id,
                owner_id=self._owner_id,
                generation=lease_state[0].generation,
                status=status,
                error=error_text,
            )
        except LeaseConflictError:
            # A superseded worker must not write durable Run state.
            return

    def _renew_lease(
        self,
        lease_state: List[RunLease],
        stop: threading.Event,
    ) -> None:
        interval = self._lease_seconds / 3
        while not stop.wait(interval):
            try:
                lease_state[0] = self._ledger.renew(
                    lease_state[0],
                    lease_seconds=self._lease_seconds,
                )
            except LeaseConflictError:
                return

    def _forget(self, run_id: str) -> None:
        with self._futures_lock:
            self._futures.pop(run_id, None)

    def _status(self, run_id: str) -> RunStatus:
        try:
            run = self._ledger.run(run_id)
        except KeyError as error:
            raise DaemonError("run_not_found", str(error)) from error
        stop: Mapping[str, object] = {}
        try:
            report = self._runner.report(run_id)
        except KeyError:
            pass
        else:
            if report.stop is not None:
                stop = asdict(report.stop)
        return RunStatus(
            run_id=run.run_id,
            status=run.status,
            error=run.error,
            reason=str(stop.get("reason", "")),
            boundary=str(stop.get("boundary", "")),
            todo_id=str(stop.get("todo_id", "")),
            role=str(stop.get("role", "")),
            stage=str(stop.get("stage", "")),
            provider=str(stop.get("provider", "")),
            model=str(stop.get("model", "")),
            resumable=bool(stop.get("resumable", False)),
            snapshot_id=run.snapshot_id,
            goal_id=run.goal_id,
        )

    def _acquire_process_lock(self) -> None:
        lock_path = self._state_dir / "run" / "daemon.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock_file.close()
            raise RuntimeError(
                f"daemon is already active for state directory: {self._state_dir}"
            ) from error
        self._process_lock_file = lock_file

    def _release_process_lock(self) -> None:
        lock_file = self._process_lock_file
        self._process_lock_file = None
        if lock_file is None:
            return
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

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


def _required_parameter(parameters: Mapping[str, object], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value:
        raise DaemonError("invalid_request", f"{name} must be a non-empty string")
    return value
