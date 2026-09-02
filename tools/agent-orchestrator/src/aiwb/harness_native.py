"""Harness-native Admission, durable ledger, and one-Attempt Run execution."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import pickle
import queue
import re
import signal
import sqlite3
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from multiprocessing.connection import wait as wait_for_connections
from multiprocessing.reduction import DupFd
from pathlib import Path
from types import MappingProxyType
from typing import AbstractSet, Any, Callable, Optional, Protocol, Sequence, Tuple

import yaml

from .agent_harness import (
    ActivityEvent,
    AgentHarnessDriver,
    AgentHarnessProfile,
    AttemptOutcome,
    AttemptSpec,
)
from .evidence import EvidenceReference, EvidenceStore
from .harness import CommandHarness, HarnessAdapter, HarnessExecution, HarnessRequest, LocalProcessHarness
from .image import CommandImageBuilder, ImageBuildRequest
from .kubernetes import KubernetesHarness, KubernetesJanitor
from .project import (
    BrowserDiagnosticProfile,
    CandidatePublishProfile,
    HarnessProfile,
    ImageProfile,
    ProjectConfigError,
    ProjectPolicy,
)
from .publish import CandidatePublishRequest, CandidatePublisher
from .skills import AGENT_SKILL_ROOTS


ADMISSION_SCHEMA_VERSION = 5
RUN_LEDGER_SCHEMA_VERSION = 5
_ACTIVITY_QUEUE_CAPACITY = 64
_ACTIVITY_DRAIN_BATCH = 64
_MAX_ACTIVITY_EVENTS_PER_ATTEMPT = 256
_PARENT_DEATH_TERM_GRACE_SECONDS = 1.0


class CheckpointStage:
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    IMAGE_STARTING = "image_starting"
    IMAGE_RUNNING = "image_running"
    IMAGE_COMPLETE = "image_complete"
    PUBLISH_STARTING = "publish_starting"
    PUBLISHED = "published"
    ACCEPTED = "accepted"
    ALL = frozenset((CANDIDATE, VERIFIED, VERIFICATION_FAILED, IMAGE_STARTING, IMAGE_RUNNING, IMAGE_COMPLETE, PUBLISH_STARTING, PUBLISHED, ACCEPTED))


class AdmissionError(ValueError):
    pass


class LeaseConflictError(RuntimeError):
    pass


class ContractError(ValueError):
    pass


def _interrupt_on_termination(*_: object) -> None:
    raise KeyboardInterrupt()


def _activity_budget_exceeded(events: object, recorded_events: int) -> bool:
    if recorded_events < _MAX_ACTIVITY_EVENTS_PER_ATTEMPT:
        return False
    try:
        events.get_nowait()
    except queue.Empty:
        return False
    return True


def _monitor_parent_liveness(
    parent_liveness: object,
    worker_pid: object,
    worker_done: Optional[object] = None,
    ready: Optional[object] = None,
) -> None:
    """Kill the worker process group when its parent connection disappears."""
    os.setsid()
    pid = worker_pid.value if hasattr(worker_pid, "value") else worker_pid
    parent_is_gone = False
    try:
        if parent_liveness.poll():
            parent_liveness.recv_bytes()
            return
    except (EOFError, OSError):
        parent_is_gone = True
    if not parent_is_gone and ready is not None:
        ready.set()
    try:
        if not parent_is_gone:
            watched = [parent_liveness]
            if worker_done is not None:
                watched.append(worker_done)
            connection = wait_for_connections(watched)[0]
            if connection is worker_done:
                try:
                    worker_done.recv_bytes()
                    return
                except (EOFError, OSError):
                    pass
            else:
                try:
                    parent_liveness.recv_bytes()
                    return
                except (EOFError, OSError):
                    pass
    except (EOFError, OSError):
        pass
    if pid == 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + _PARENT_DEATH_TERM_GRACE_SECONDS
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except (PermissionError, ProcessLookupError):
                return
            time.sleep(0.05)
        os.killpg(pid, signal.SIGKILL)
    except (PermissionError, ProcessLookupError):
        pass


def _supervised_process_entry(
    target: Callable[..., None],
    arguments: Tuple[object, ...],
    worker_pid: object,
    parent_liveness: object,
) -> None:
    """Own the process group and parent watchdog before external execution."""
    os.setsid()
    worker_pid.value = os.getpid()
    try:
        if parent_liveness.poll():
            parent_liveness.recv_bytes()
            return
    except (EOFError, OSError):
        return
    context = multiprocessing.get_context("spawn")
    watchdog_done, worker_done = context.Pipe(duplex=False)
    ready = context.Event()
    watchdog = context.Process(
        target=_monitor_parent_liveness,
        args=(parent_liveness, os.getpid(), watchdog_done, ready),
        name="aiwb-parent-watchdog",
    )
    watchdog.start()
    watchdog_done.close()
    parent_liveness.close()
    ready.wait()
    try:
        target(*arguments)
    finally:
        try:
            worker_done.send_bytes(b"done")
        except (BrokenPipeError, OSError):
            pass
        worker_done.close()
        watchdog.join()


def _attempt_process_entry(
    driver: AgentHarnessDriver,
    spec: AttemptSpec,
    events: object,
    result: object,
) -> None:
    """Run one driver in a fresh interpreter, never a forked daemon worker."""
    try:
        result.put(("outcome", driver.execute(spec, events.put)))
    except BaseException as error:  # Driver failures must terminalize the Attempt.
        result.put(("error", f"{type(error).__name__}: {error}"))


def _image_process_entry(
    builder: Any,
    method: str,
    request: ImageBuildRequest,
    operation_id: str,
    result: object,
) -> None:
    """Run one admitted image operation in a fresh interpreter."""
    try:
        if method == "start":
            value = builder.start(request)
        elif method == "status":
            value = builder.status(request, operation_id)
        elif method == "result":
            value = builder.result(request, operation_id)
        else:
            raise ValueError(f"unknown image operation method: {method}")
        result.put(("value", value))
    except BaseException as error:
        result.put(("error", f"{type(error).__name__}: {error}"))


def _verification_process_entry(adapter: Any, request: HarnessRequest, result: object) -> None:
    try:
        signal.signal(signal.SIGTERM, _interrupt_on_termination)
        result.put(("value", adapter.execute(request)))
    except BaseException as error:
        result.put(("error", f"{type(error).__name__}: {error}"))


def _publish_process_entry(
    publisher: Any,
    request: CandidatePublishRequest,
    result: object,
) -> None:
    try:
        result.put(("value", publisher.publish(request)))
    except BaseException as error:
        result.put(("error", f"{type(error).__name__}: {error}"))


def _git_write_process_entry(
    worktree: Path,
    arguments: Tuple[str, ...],
    result: object,
) -> None:
    """Run one worktree-mutating Git command inside the admitted boundary."""
    try:
        completed = subprocess.run(
            ("git", "-C", str(worktree), *arguments),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result.put(
            ("value", (completed.returncode, completed.stdout, completed.stderr))
        )
    except BaseException as error:
        result.put(("error", f"{type(error).__name__}: {error}"))


@dataclass
class _ProcessResultSpool:
    descriptor: int

    @classmethod
    def create(cls) -> "_ProcessResultSpool":
        descriptor, path = tempfile.mkstemp(
            prefix="aiwb-process-result-", suffix=".pickle"
        )
        os.unlink(path)
        return cls(descriptor)

    def __reduce__(self) -> object:
        return (_rebuild_process_result_spool, (DupFd(self.descriptor),))

    def put(self, value: object) -> None:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        os.ftruncate(self.descriptor, 0)
        with os.fdopen(os.dup(self.descriptor), "wb") as stream:
            pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)

    def get(self) -> object:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(self.descriptor), "rb") as stream:
            return pickle.load(stream)

    def close(self) -> None:
        os.close(self.descriptor)


def _rebuild_process_result_spool(duplicated_descriptor: object) -> _ProcessResultSpool:
    return _ProcessResultSpool(duplicated_descriptor.detach())


@dataclass
class _SupervisedProcess:
    worker: multiprocessing.Process
    parent_liveness: object
    worker_pid: object

    def close(self) -> None:
        _terminate_process(self.worker)
        _stop_parent_watchdog(self.parent_liveness)


def _start_supervised_process(
    context: multiprocessing.context.BaseContext,
    operation: str,
    target: Callable[..., None],
    arguments: Tuple[object, ...],
    lease_provider: Callable[[], Optional["RunLease"]],
) -> _SupervisedProcess:
    """Start one child with the shared lease and parent-death boundary."""
    child_liveness = parent_liveness = worker = None
    try:
        child_liveness, parent_liveness = context.Pipe(duplex=False)
        worker_pid = context.Value("q", 0)
        worker = context.Process(
            target=_supervised_process_entry,
            args=(target, arguments, worker_pid, child_liveness),
            name=f"aiwb-{operation}",
        )
        lease_provider()
        worker.start()
        child_liveness.close()
        return _SupervisedProcess(worker, parent_liveness, worker_pid)
    except BaseException:
        if worker is not None and worker.pid is not None:
            _terminate_process(worker)
        if parent_liveness is not None:
            _stop_parent_watchdog(parent_liveness)
        if child_liveness is not None:
            child_liveness.close()
        raise


def _terminate_process(worker: multiprocessing.Process) -> None:
    sent_group_signal = False
    if worker.pid is not None:
        try:
            os.killpg(worker.pid, signal.SIGTERM)
            sent_group_signal = True
        except (PermissionError, ProcessLookupError):
            pass
    if not sent_group_signal and worker.is_alive():
        worker.terminate()
    worker.join(1)
    if sent_group_signal:
        time.sleep(0.1)
    if worker.pid is not None:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
    if worker.is_alive():
        worker.kill()
    worker.join(1)


def _stop_parent_watchdog(parent_liveness: object) -> None:
    try:
        parent_liveness.send_bytes(b"done")
    except (BrokenPipeError, OSError):
        pass
    parent_liveness.close()


@dataclass(frozen=True)
class AdmissionRequest:
    contract_path: Path
    workflow_path: Optional[Path] = None
    idempotency_key: Optional[str] = None


class ExecutionManifest(Mapping[str, object]):
    """The deeply immutable, behavior-complete execution authority."""

    def __init__(self, values: Mapping[str, object]) -> None:
        if values.get("schema_version") != ADMISSION_SCHEMA_VERSION:
            raise AdmissionError("ExecutionManifest schema_version is not supported")
        versions = _mapping(values, "versions")
        if versions.get("admission_schema") != ADMISSION_SCHEMA_VERSION:
            raise AdmissionError("ExecutionManifest admission_schema is not supported")
        _text(versions, "engine")
        _text(versions, "transition_policy")
        _goal(_mapping(values, "goal"))
        _text(values, "instructions")
        _profile(_mapping(values, "agent_harness"))
        repository = _mapping(values, "repository")
        for name in ("path", "base_ref", "base_commit"):
            _text(repository, name)
        if len(str(repository["base_commit"])) < 40:
            raise AdmissionError("ExecutionManifest repository.base_commit must be a Git object id")
        verification = _mapping(values, "verification")
        command = verification.get("command")
        if not isinstance(command, (tuple, list)) or not command or not all(isinstance(item, str) and item for item in command):
            raise AdmissionError("ExecutionManifest verification.command must be a non-empty command")
        timeout = verification.get("timeout_seconds")
        if not isinstance(timeout, int) or timeout <= 0:
            raise AdmissionError("ExecutionManifest verification.timeout_seconds must be positive")
        candidate = _mapping(values, "candidate")
        if "image" in candidate:
            _image_from_value(_mapping(candidate, "image"))
        if "publish" in candidate:
            CandidatePublishProfile(**dict(_mapping(candidate, "publish")))
        required_secrets = values.get("required_secrets", ())
        if not isinstance(required_secrets, (tuple, list)) or not all(_valid_secret_reference(value) for value in required_secrets):
            raise AdmissionError("ExecutionManifest required_secrets must be references")
        self._values = _freeze(values)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


@dataclass(frozen=True)
class ExecutionSnapshot:
    snapshot_id: str
    source: bytes
    manifest: ExecutionManifest
    created_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExecutionManifest):
            object.__setattr__(self, "manifest", ExecutionManifest(self.manifest))


@dataclass(frozen=True)
class RunLease:
    run_id: str
    owner_id: str
    generation: int
    expires_at: str


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    snapshot_id: str
    goal_id: str
    status: str
    created_at: str
    error: str = ""


@dataclass(frozen=True)
class RunCheckpoint:
    stage: str = ""
    attempt_id: str = ""
    candidate_commit: str = ""
    operation_id: str = ""
    publish_result: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class AdmittedRun:
    run_id: str
    snapshot_id: str
    goal_id: str
    status: str


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    status: str
    outcome: str = ""
    summary: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class ActivityRecord:
    attempt_id: str
    kind: str
    summary: str
    session_id: str
    usage_tokens: Optional[int]


@dataclass(frozen=True)
class VerificationEvidence:
    command: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    stdout_ref: Optional[EvidenceReference] = None
    stderr_ref: Optional[EvidenceReference] = None
    artifacts: Tuple[str, ...] = ()
    environment: str = ""
    artifact_refs: Tuple[EvidenceReference, ...] = ()
    attempt_id: str = ""
    candidate_commit: str = ""
    stage: str = "verification"


@dataclass(frozen=True)
class RunReport:
    run_id: str
    goal_id: str
    status: str
    branch: str
    worktree: str
    attempts: Tuple[AttemptRecord, ...]
    activity: Tuple[ActivityRecord, ...]
    evidence: Tuple[VerificationEvidence, ...]
    candidate_commit: str = ""
    error: str = ""
    checkpoint: str = ""
    publish_result: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return _json_value(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunReport":
        return cls(
            run_id=str(value["run_id"]), goal_id=str(value["goal_id"]),
            status=str(value["status"]), branch=str(value.get("branch", "")),
            worktree=str(value.get("worktree", "")),
            attempts=tuple(AttemptRecord(**item) for item in value.get("attempts", ()) if isinstance(item, dict)),
            activity=tuple(ActivityRecord(**item) for item in value.get("activity", ()) if isinstance(item, dict)),
            evidence=tuple(_evidence_from_value(item) for item in value.get("evidence", ()) if isinstance(item, dict)),
            candidate_commit=str(value.get("candidate_commit", "")), error=str(value.get("error", "")),
            checkpoint=str(value.get("checkpoint", "")),
            publish_result=dict(value.get("publish_result", {})),
        )


class RunLedger(Protocol):
    def admit(self, snapshot: ExecutionSnapshot, *, goal_id: str, idempotency_key: Optional[str] = None) -> AdmittedRun: ...
    def execution_snapshot(self, snapshot_id: str) -> ExecutionSnapshot: ...
    def run(self, run_id: str) -> RunRecord: ...
    def queued_runs(self) -> Tuple[RunRecord, ...]: ...
    def claim(self, run_id: str, *, owner_id: str, lease_seconds: float, now: Optional[datetime] = None, supported_engine_versions: Optional[AbstractSet[str]] = None, supported_admission_schema_versions: Optional[AbstractSet[int]] = None, supported_transition_policy_versions: Optional[AbstractSet[str]] = None) -> Optional[RunLease]: ...
    def renew(self, lease: RunLease, *, lease_seconds: float, now: Optional[datetime] = None) -> RunLease: ...
    def prove(self, lease: RunLease, *, now: Optional[datetime] = None) -> RunLease: ...
    def start_attempt(self, run_id: str, *, worktree: Path, branch: str, lease: Optional[RunLease] = None) -> str: ...
    def record_activity(self, attempt_id: str, event: ActivityEvent, *, lease: Optional[RunLease] = None) -> None: ...
    def finish_attempt(self, attempt_id: str, outcome: AttemptOutcome, *, lease: Optional[RunLease] = None) -> None: ...
    def retry(self, run_id: str) -> RunRecord: ...
    def checkpoint(self, run_id: str) -> RunCheckpoint: ...
    def clear_checkpoint(self, run_id: str, *, lease: Optional[RunLease] = None) -> None: ...
    def checkpoint_candidate(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None: ...
    def checkpoint_image_starting(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None: ...
    def checkpoint_image_running(self, run_id: str, attempt_id: str, candidate_commit: str, operation_id: str, *, lease: Optional[RunLease] = None) -> None: ...
    def checkpoint_publish_starting(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None: ...
    def checkpoint_published(self, run_id: str, attempt_id: str, candidate_commit: str, result: Mapping[str, object], *, lease: Optional[RunLease] = None) -> None: ...
    def record_verification(self, run_id: str, evidence: VerificationEvidence, *, lease: Optional[RunLease] = None) -> None: ...
    def accept_candidate(self, run_id: str, candidate_commit: str, *, attempt_id: str, lease: Optional[RunLease] = None) -> None: ...
    def fail(self, run_id: str, error: str, *, lease: Optional[RunLease] = None) -> None: ...
    def projection(self, run_id: str) -> RunReport: ...


class SQLiteRunLedger:
    """The sole durable authority for Runs, Attempts, Activity and Evidence."""

    def __init__(self, database: Path) -> None:
        self._database = Path(database)
        self._database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(journal_mode=False) as connection:
            existing_schema = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'run_ledger_schema'"
            ).fetchone()
            if existing_schema is not None:
                version = connection.execute(
                    "SELECT schema_version FROM run_ledger_schema WHERE singleton = 1"
                ).fetchone()
                if version is None or version[0] != RUN_LEDGER_SCHEMA_VERSION:
                    raise RuntimeError(
                        "incompatible current RunLedger state; explicit reset is required"
                    )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS run_ledger_schema (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO run_ledger_schema VALUES (1, 5);
                CREATE TABLE IF NOT EXISTS execution_snapshots (
                    snapshot_id TEXT PRIMARY KEY, source BLOB NOT NULL,
                    manifest_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    repository TEXT NOT NULL DEFAULT '', worktree TEXT NOT NULL DEFAULT '',
                    branch TEXT NOT NULL DEFAULT '', candidate_commit TEXT NOT NULL DEFAULT '',
                    lease_generation INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_queue (
                    run_id TEXT PRIMARY KEY, enqueued_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS run_leases (
                    run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    expires_at TEXT NOT NULL, renewed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_transitions (
                    transition_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    generation INTEGER NOT NULL, from_status TEXT NOT NULL, to_status TEXT NOT NULL,
                    error TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS activity_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL,
                    kind TEXT NOT NULL, summary TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
                    usage_tokens INTEGER, recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS verification_evidence (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL, candidate_commit TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    command_json TEXT NOT NULL, returncode INTEGER NOT NULL, stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL, duration_seconds REAL NOT NULL, stdout_ref_json TEXT,
                    stderr_ref_json TEXT, artifacts_json TEXT NOT NULL DEFAULT '[]',
                    environment TEXT NOT NULL DEFAULT '', artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    run_id TEXT PRIMARY KEY, stage TEXT NOT NULL DEFAULT '',
                    attempt_id TEXT NOT NULL DEFAULT '', candidate_commit TEXT NOT NULL DEFAULT '',
                    operation_id TEXT NOT NULL DEFAULT '', publish_result_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                """
            )

    def admit(self, snapshot: ExecutionSnapshot, *, goal_id: str, idempotency_key: Optional[str] = None) -> AdmittedRun:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = connection.execute("SELECT run_id, snapshot_id, goal_id, status FROM runs JOIN idempotency_keys USING (run_id) WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if existing["snapshot_id"] != snapshot.snapshot_id:
                        raise AdmissionError("idempotency key was already used for a different ExecutionSnapshot")
                    return AdmittedRun(existing["run_id"], existing["snapshot_id"], existing["goal_id"], existing["status"])
            connection.execute("INSERT OR IGNORE INTO execution_snapshots VALUES (?, ?, ?, ?)", (snapshot.snapshot_id, snapshot.source, _canonical_json(snapshot.manifest), snapshot.created_at))
            run_id = f"{goal_id}-{uuid.uuid4().hex}"
            connection.execute("INSERT INTO runs (run_id, snapshot_id, goal_id, status, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)", (run_id, snapshot.snapshot_id, goal_id, now, now))
            connection.execute("INSERT INTO run_checkpoints (run_id, updated_at) VALUES (?, ?)", (run_id, now))
            connection.execute("INSERT INTO run_queue VALUES (?, ?)", (run_id, now))
            if idempotency_key:
                connection.execute("INSERT INTO idempotency_keys VALUES (?, ?)", (idempotency_key, run_id))
        return AdmittedRun(run_id, snapshot.snapshot_id, goal_id, "queued")

    def execution_snapshot(self, snapshot_id: str) -> ExecutionSnapshot:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM execution_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown ExecutionSnapshot: {snapshot_id}")
        return ExecutionSnapshot(row["snapshot_id"], row["source"], ExecutionManifest(json.loads(row["manifest_json"])), row["created_at"])

    def run(self, run_id: str) -> RunRecord:
        row = self._row(run_id)
        return RunRecord(row["run_id"], row["snapshot_id"], row["goal_id"], row["status"], row["created_at"], row["error"])

    def queued_runs(self) -> Tuple[RunRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT runs.* FROM runs JOIN run_queue USING (run_id) ORDER BY enqueued_at").fetchall()
        return tuple(RunRecord(row["run_id"], row["snapshot_id"], row["goal_id"], row["status"], row["created_at"], row["error"]) for row in rows)

    def claim(
        self,
        run_id: str,
        *,
        owner_id: str,
        lease_seconds: float,
        now: Optional[datetime] = None,
        supported_engine_versions: Optional[AbstractSet[str]] = None,
        supported_admission_schema_versions: Optional[AbstractSet[int]] = None,
        supported_transition_policy_versions: Optional[AbstractSet[str]] = None,
    ) -> Optional[RunLease]:
        instant = _instant(now)
        expiry = _instant((now or datetime.now(timezone.utc)) + timedelta(seconds=lease_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT runs.status, runs.lease_generation, execution_snapshots.manifest_json FROM runs JOIN execution_snapshots USING (snapshot_id) WHERE run_id = ?", (run_id,)).fetchone()
            if row is None or row["status"] not in {"queued", "attempting", "verifying"}:
                return None
            versions = _mapping(ExecutionManifest(json.loads(row["manifest_json"])), "versions")
            if supported_engine_versions is not None and versions["engine"] not in supported_engine_versions:
                raise RuntimeError("unsupported engine version in ExecutionSnapshot")
            if supported_admission_schema_versions is not None and versions["admission_schema"] not in supported_admission_schema_versions:
                raise RuntimeError("unsupported admission schema version in ExecutionSnapshot")
            if supported_transition_policy_versions is not None and versions["transition_policy"] not in supported_transition_policy_versions:
                raise RuntimeError("unsupported transition policy version in ExecutionSnapshot")
            lease = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()
            if lease is not None and lease["expires_at"] > instant:
                return None
            if lease is not None:
                connection.execute(
                    "UPDATE attempts SET status = 'terminal', outcome = 'interrupted', summary = 'Daemon Lease expired; a fresh Attempt will be started', finished_at = ? WHERE run_id = ? AND status = 'running'",
                    (instant, run_id),
                )
            generation = int(row["lease_generation"]) + 1
            next_status = "verifying" if row["status"] == "verifying" else "attempting"
            connection.execute("UPDATE runs SET status = ?, lease_generation = ?, updated_at = ? WHERE run_id = ?", (next_status, generation, instant, run_id))
            if row["status"] != next_status:
                connection.execute("INSERT INTO run_transitions (run_id, generation, from_status, to_status, error, recorded_at) VALUES (?, ?, ?, ?, '', ?)", (run_id, generation, row["status"], next_status, instant))
            connection.execute("INSERT OR REPLACE INTO run_leases VALUES (?, ?, ?, ?, ?)", (run_id, owner_id, generation, expiry, instant))
        return RunLease(run_id, owner_id, generation, expiry)

    def renew(self, lease: RunLease, *, lease_seconds: float, now: Optional[datetime] = None) -> RunLease:
        expiry = _instant((now or datetime.now(timezone.utc)) + timedelta(seconds=lease_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_lease_in(connection, lease, now)
            connection.execute("UPDATE run_leases SET expires_at = ?, renewed_at = ? WHERE run_id = ?", (expiry, _instant(now), lease.run_id))
        return RunLease(lease.run_id, lease.owner_id, lease.generation, expiry)

    def prove(self, lease: RunLease, *, now: Optional[datetime] = None) -> RunLease:
        self._assert_lease(lease, now)
        return lease

    def start_attempt(self, run_id: str, *, worktree: Path, branch: str, lease: Optional[RunLease] = None) -> str:
        attempt_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            connection.execute("UPDATE runs SET worktree = ?, branch = ?, error = '', updated_at = ? WHERE run_id = ?", (str(worktree), branch, _now(), run_id))
            connection.execute("INSERT INTO attempts (attempt_id, run_id, status, started_at) VALUES (?, ?, 'running', ?)", (attempt_id, run_id, _now()))
        return attempt_id

    def record_activity(self, attempt_id: str, event: ActivityEvent, *, lease: Optional[RunLease] = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT run_id, status FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown Attempt: {attempt_id}")
            if row["status"] != "running":
                raise RuntimeError("Attempt is already terminal")
            self._guard_run_in(connection, lease, row["run_id"])
            connection.execute("INSERT INTO activity_events (attempt_id, kind, summary, session_id, usage_tokens, recorded_at) VALUES (?, ?, ?, ?, ?, ?)", (attempt_id, event.kind, event.summary, event.session_id, event.usage_tokens, _now()))

    def finish_attempt(self, attempt_id: str, outcome: AttemptOutcome, *, lease: Optional[RunLease] = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT run_id, status FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown Attempt: {attempt_id}")
            if row["status"] != "running":
                raise RuntimeError("Attempt is already terminal")
            self._guard_run_in(connection, lease, row["run_id"])
            connection.execute("UPDATE attempts SET status = 'terminal', outcome = ?, summary = ?, session_id = ?, finished_at = ? WHERE attempt_id = ?", (outcome.status, outcome.summary, outcome.session_id, _now(), attempt_id))
            status = "verifying" if outcome.status == "completed" else outcome.status
            self._update_in(connection, row["run_id"], lease, status=status, error="" if outcome.status == "completed" else outcome.summary)

    def retry(self, run_id: str) -> RunRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown Run: {run_id}")
            if row["status"] not in {"interrupted", "failed"}:
                raise ValueError(f"Run {run_id!r} is not retryable")
            checkpoint = connection.execute(
                "SELECT stage FROM run_checkpoints WHERE run_id = ?", (run_id,)
            ).fetchone()
            if checkpoint is not None and checkpoint["stage"] in {
                CheckpointStage.IMAGE_STARTING,
                CheckpointStage.PUBLISH_STARTING,
            }:
                raise ValueError("external operation outcome is unknown; reset is required before retry")
            now = _now()
            self._update_in(connection, run_id, None, status="queued", error="")
            connection.execute("INSERT OR REPLACE INTO run_queue VALUES (?, ?)", (run_id, now))
            connection.execute("DELETE FROM run_leases WHERE run_id = ?", (run_id,))
            if checkpoint is None or checkpoint["stage"] not in {
                CheckpointStage.CANDIDATE,
                CheckpointStage.VERIFIED,
                CheckpointStage.VERIFICATION_FAILED,
                CheckpointStage.IMAGE_RUNNING,
                CheckpointStage.IMAGE_COMPLETE,
                CheckpointStage.PUBLISHED,
            }:
                connection.execute("UPDATE run_checkpoints SET stage = '', attempt_id = '', candidate_commit = '', operation_id = '', publish_result_json = '{}', updated_at = ? WHERE run_id = ?", (now, run_id))
        return self.run(run_id)

    def checkpoint(self, run_id: str) -> RunCheckpoint:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM run_checkpoints WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown Run checkpoint: {run_id}")
        return RunCheckpoint(
            row["stage"], row["attempt_id"], row["candidate_commit"], row["operation_id"],
            MappingProxyType(json.loads(row["publish_result_json"])),
        )

    def clear_checkpoint(self, run_id: str, *, lease: Optional[RunLease] = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            connection.execute(
                "UPDATE run_checkpoints SET stage = '', attempt_id = '', candidate_commit = '', operation_id = '', publish_result_json = '{}', updated_at = ? WHERE run_id = ?",
                (_now(), run_id),
            )

    def checkpoint_candidate(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None:
        self._checkpoint(run_id, CheckpointStage.CANDIDATE, attempt_id, candidate_commit, lease=lease)

    def checkpoint_image_starting(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None:
        self._checkpoint(run_id, CheckpointStage.IMAGE_STARTING, attempt_id, candidate_commit, lease=lease)

    def checkpoint_image_running(self, run_id: str, attempt_id: str, candidate_commit: str, operation_id: str, *, lease: Optional[RunLease] = None) -> None:
        self._checkpoint(run_id, CheckpointStage.IMAGE_RUNNING, attempt_id, candidate_commit, operation_id, lease=lease)

    def checkpoint_publish_starting(self, run_id: str, attempt_id: str, candidate_commit: str, *, lease: Optional[RunLease] = None) -> None:
        self._checkpoint(run_id, CheckpointStage.PUBLISH_STARTING, attempt_id, candidate_commit, lease=lease)

    def checkpoint_published(self, run_id: str, attempt_id: str, candidate_commit: str, result: Mapping[str, object], *, lease: Optional[RunLease] = None) -> None:
        self._checkpoint(run_id, CheckpointStage.PUBLISHED, attempt_id, candidate_commit, publish_result=result, lease=lease)

    def _checkpoint(self, run_id: str, stage: str, attempt_id: str, candidate_commit: str, operation_id: str = "", publish_result: Optional[Mapping[str, object]] = None, *, lease: Optional[RunLease] = None) -> None:
        if stage not in CheckpointStage.ALL:
            raise ValueError(f"unknown Run Checkpoint stage: {stage}")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            attempt = self._attempt_in(connection, attempt_id, run_id)
            if attempt["status"] != "terminal" or attempt["outcome"] != "completed":
                raise RuntimeError("Checkpoint requires a completed Attempt")
            current = connection.execute(
                "SELECT stage, attempt_id, candidate_commit FROM run_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            expected = {
                CheckpointStage.CANDIDATE: {""},
                CheckpointStage.IMAGE_STARTING: {CheckpointStage.VERIFIED},
                CheckpointStage.IMAGE_RUNNING: {CheckpointStage.IMAGE_STARTING},
                CheckpointStage.PUBLISHED: {CheckpointStage.PUBLISH_STARTING},
            }.get(stage)
            if stage == CheckpointStage.PUBLISH_STARTING:
                snapshot = connection.execute(
                    "SELECT execution_snapshots.manifest_json FROM runs JOIN execution_snapshots USING (snapshot_id) WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                candidate = _mapping(
                    ExecutionManifest(json.loads(snapshot["manifest_json"])), "candidate"
                )
                expected = {
                    CheckpointStage.IMAGE_COMPLETE
                    if isinstance(candidate.get("image"), Mapping)
                    else CheckpointStage.VERIFIED
                }
            if expected is not None and (current is None or current["stage"] not in expected):
                raise RuntimeError(f"invalid Run Checkpoint transition to {stage}")
            if stage != CheckpointStage.CANDIDATE and (
                current["attempt_id"] != attempt_id
                or current["candidate_commit"] != candidate_commit
            ):
                raise RuntimeError("Run Checkpoint transition must preserve Attempt and Candidate")
            connection.execute("UPDATE run_checkpoints SET stage = ?, attempt_id = ?, candidate_commit = ?, operation_id = ?, publish_result_json = ?, updated_at = ? WHERE run_id = ?", (stage, attempt_id, candidate_commit, operation_id, _canonical_json(publish_result or {}), _now(), run_id))

    def record_verification(self, run_id: str, evidence: VerificationEvidence, *, lease: Optional[RunLease] = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            attempt = self._attempt_in(connection, evidence.attempt_id, run_id)
            run = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if attempt["status"] != "terminal" or attempt["outcome"] != "completed" or run is None or run["status"] != "verifying":
                raise RuntimeError("Verification Evidence requires a completed Attempt in verification")
            checkpoint = connection.execute("SELECT stage, attempt_id, candidate_commit FROM run_checkpoints WHERE run_id = ?", (run_id,)).fetchone()
            expected_stage = CheckpointStage.CANDIDATE if evidence.stage == "verification" else CheckpointStage.IMAGE_RUNNING
            if checkpoint is None or checkpoint["stage"] != expected_stage or checkpoint["attempt_id"] != evidence.attempt_id or checkpoint["candidate_commit"] != evidence.candidate_commit:
                raise RuntimeError("Verification Evidence must match the durable Candidate Checkpoint")
            connection.execute("INSERT INTO verification_evidence (run_id, attempt_id, candidate_commit, stage, command_json, returncode, stdout, stderr, duration_seconds, stdout_ref_json, stderr_ref_json, artifacts_json, environment, artifact_refs_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, evidence.attempt_id, evidence.candidate_commit, evidence.stage, json.dumps(evidence.command), evidence.returncode, evidence.stdout, evidence.stderr, evidence.duration_seconds, _reference_json(evidence.stdout_ref), _reference_json(evidence.stderr_ref), json.dumps(evidence.artifacts), evidence.environment, _references_json(evidence.artifact_refs), _now()))
            if evidence.stage == "verification":
                stage = CheckpointStage.VERIFIED if evidence.returncode == 0 else CheckpointStage.VERIFICATION_FAILED
                connection.execute("UPDATE run_checkpoints SET stage = ?, attempt_id = ?, candidate_commit = ?, operation_id = '', updated_at = ? WHERE run_id = ?", (stage, evidence.attempt_id, evidence.candidate_commit, _now(), run_id))
            elif evidence.stage == "image":
                if evidence.returncode != 0:
                    raise RuntimeError("failed image Evidence cannot complete the image Checkpoint")
                connection.execute("UPDATE run_checkpoints SET stage = ?, attempt_id = ?, candidate_commit = ?, updated_at = ? WHERE run_id = ?", (CheckpointStage.IMAGE_COMPLETE, evidence.attempt_id, evidence.candidate_commit, _now(), run_id))

    def accept_candidate(self, run_id: str, candidate_commit: str, *, attempt_id: str, lease: Optional[RunLease] = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            attempt = self._attempt_in(connection, attempt_id, run_id)
            run = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if attempt["status"] != "terminal" or attempt["outcome"] != "completed" or run is None or run["status"] != "verifying":
                raise RuntimeError("Candidate acceptance requires a completed Attempt in verification")
            checkpoint = connection.execute("SELECT stage, attempt_id, candidate_commit FROM run_checkpoints WHERE run_id = ?", (run_id,)).fetchone()
            if checkpoint is None or checkpoint["attempt_id"] != attempt_id or checkpoint["candidate_commit"] != candidate_commit:
                raise RuntimeError("Candidate acceptance must match the durable Candidate Checkpoint")
            snapshot = connection.execute("SELECT execution_snapshots.manifest_json FROM runs JOIN execution_snapshots USING (snapshot_id) WHERE run_id = ?", (run_id,)).fetchone()
            candidate = _mapping(ExecutionManifest(json.loads(snapshot["manifest_json"])), "candidate")
            expected_stage = CheckpointStage.PUBLISHED if isinstance(candidate.get("publish"), Mapping) else CheckpointStage.IMAGE_COMPLETE if isinstance(candidate.get("image"), Mapping) else CheckpointStage.VERIFIED
            if checkpoint["stage"] != expected_stage:
                raise RuntimeError("Candidate acceptance requires all admitted image and publish Checkpoints")
            passed = connection.execute("SELECT 1 FROM verification_evidence WHERE run_id = ? AND attempt_id = ? AND candidate_commit = ? AND stage = 'verification' AND returncode = 0", (run_id, attempt_id, candidate_commit)).fetchone()
            if passed is None:
                raise RuntimeError("Verification Harness Evidence for the current Attempt and Candidate commit is required before accepting Candidate")
            self._update_in(connection, run_id, lease, status="candidate", candidate_commit=candidate_commit, error="")
            connection.execute("UPDATE run_checkpoints SET stage = ?, updated_at = ? WHERE run_id = ?", (CheckpointStage.ACCEPTED, _now(), run_id))

    def fail(self, run_id: str, error: str, *, lease: Optional[RunLease] = None) -> None:
        self._update(run_id, lease=lease, status="failed", error=error)

    def projection(self, run_id: str) -> RunReport:
        with self._connect() as connection:
            connection.execute("BEGIN")
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"unknown Run: {run_id}")
            checkpoint_row = connection.execute(
                "SELECT * FROM run_checkpoints WHERE run_id = ?", (run_id,)
            ).fetchone()
            if checkpoint_row is None:
                raise KeyError(f"unknown Run checkpoint: {run_id}")
            attempts = connection.execute("SELECT * FROM attempts WHERE run_id = ? ORDER BY started_at", (run_id,)).fetchall()
            activity = connection.execute("SELECT activity_events.* FROM activity_events JOIN attempts USING (attempt_id) WHERE attempts.run_id = ? ORDER BY event_id", (run_id,)).fetchall()
            evidence = connection.execute("SELECT * FROM verification_evidence WHERE run_id = ? ORDER BY evidence_id", (run_id,)).fetchall()
        checkpoint = RunCheckpoint(
            checkpoint_row["stage"], checkpoint_row["attempt_id"], checkpoint_row["candidate_commit"],
            checkpoint_row["operation_id"], MappingProxyType(json.loads(checkpoint_row["publish_result_json"])),
        )
        return RunReport(
            run_id=run_id, goal_id=run["goal_id"], status=run["status"], branch=run["branch"], worktree=run["worktree"], candidate_commit=run["candidate_commit"], error=run["error"],
            attempts=tuple(AttemptRecord(row["attempt_id"], row["status"], row["outcome"], row["summary"], row["session_id"]) for row in attempts),
            activity=tuple(ActivityRecord(row["attempt_id"], row["kind"], row["summary"], row["session_id"], row["usage_tokens"]) for row in activity),
            evidence=tuple(_evidence_from_row(row) for row in evidence),
            checkpoint=checkpoint.stage, publish_result=dict(checkpoint.publish_result),
        )

    def _row(self, run_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown Run: {run_id}")
        return row

    def _update(self, run_id: str, *, lease: Optional[RunLease] = None, **values: object) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._guard_run_in(connection, lease, run_id)
            self._update_in(connection, run_id, lease, **values)

    def _update_in(self, connection: sqlite3.Connection, run_id: str, lease: Optional[RunLease], **values: object) -> None:
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        previous = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        connection.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", (*values.values(), run_id))
        if previous is not None and "status" in values and previous["status"] != values["status"]:
            connection.execute("INSERT INTO run_transitions (run_id, generation, from_status, to_status, error, recorded_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, lease.generation if lease else 0, previous["status"], values["status"], str(values.get("error", "")), _now()))
        if values.get("status") in {"candidate", "failed", "interrupted"}:
            connection.execute("DELETE FROM run_queue WHERE run_id = ?", (run_id,))

    def _guard(self, lease: Optional[RunLease]) -> None:
        if lease is not None:
            self._assert_lease(lease, None)

    def _guard_in(self, connection: sqlite3.Connection, lease: Optional[RunLease]) -> None:
        if lease is not None:
            self._assert_lease_in(connection, lease, None)

    def _guard_run_in(self, connection: sqlite3.Connection, lease: Optional[RunLease], run_id: str) -> None:
        self._guard_in(connection, lease)
        if lease is not None and lease.run_id != run_id:
            raise LeaseConflictError("Lease does not own this Run")

    @staticmethod
    def _attempt_in(connection: sqlite3.Connection, attempt_id: str, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT run_id, status, outcome FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None or row["run_id"] != run_id:
            raise RuntimeError("Evidence and Checkpoint must belong to the Run's Attempt")
        return row

    def _assert_lease(self, lease: RunLease, now: Optional[datetime]) -> None:
        with self._connect() as connection:
            self._assert_lease_in(connection, lease, now)

    @staticmethod
    def _assert_lease_in(connection: sqlite3.Connection, lease: RunLease, now: Optional[datetime]) -> None:
        row = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (lease.run_id,)).fetchone()
        if row is None or row["owner_id"] != lease.owner_id or row["generation"] != lease.generation:
            raise LeaseConflictError("stale Lease generation")
        if row["expires_at"] <= _instant(now):
            raise LeaseConflictError("Lease expired")

    def _connect(self, *, journal_mode: bool = True) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database), timeout=30)
        connection.row_factory = sqlite3.Row
        if journal_mode:
            connection.execute("PRAGMA journal_mode=WAL")
        return connection


class Admission:
    def __init__(self, ledger: RunLedger, *, engine_version: str, transition_policy_version: str) -> None:
        self._ledger = ledger
        self._engine_version = engine_version
        self._transition_policy_version = transition_policy_version

    def admit(self, request: AdmissionRequest) -> AdmittedRun:
        path = Path(request.contract_path).expanduser().resolve()
        source, data, approved_execution = _resolve_execution_input(
            path, request.workflow_path
        )
        _load_execution_approval(data, path, approved_execution)
        manifest = ExecutionManifest({
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "versions": {"admission_schema": ADMISSION_SCHEMA_VERSION, "engine": self._engine_version, "transition_policy": self._transition_policy_version},
            **approved_execution,
        })
        _reject_secret_material(source, manifest)
        snapshot = ExecutionSnapshot(_snapshot_id(source, manifest), source, manifest, _now())
        return self._ledger.admit(snapshot, goal_id=_text(_mapping(data, "goal"), "id"), idempotency_key=request.idempotency_key)


class GoalRunner:
    def __init__(
        self,
        state_dir: Path,
        driver: AgentHarnessDriver,
        *,
        ledger: RunLedger,
        local_harness: Optional[HarnessAdapter] = None,
        kubernetes_harness: Optional[HarnessAdapter] = None,
        image_builder: Optional[CommandImageBuilder] = None,
        publisher: Optional[CandidatePublisher] = None,
        command_harness: Optional[HarnessAdapter] = None,
    ) -> None:
        self._state_dir = Path(state_dir).expanduser().resolve()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._driver = driver
        self._ledger = ledger
        self._evidence = EvidenceStore(self._state_dir)
        self._local_harness = local_harness or LocalProcessHarness()
        self._kubernetes_harness = kubernetes_harness or KubernetesHarness(self._state_dir)
        self._image_builder = image_builder or CommandImageBuilder()
        self._publisher = publisher or CandidatePublisher()
        self._command_harness = command_harness or CommandHarness()

    def run_snapshot(
        self,
        snapshot: ExecutionSnapshot,
        *,
        run_id: str,
        lease: Optional[RunLease] = None,
        lease_provider: Optional[Callable[[], RunLease]] = None,
    ) -> RunReport:
        bound_run = self._ledger.run(run_id)
        if bound_run.snapshot_id != snapshot.snapshot_id:
            raise RuntimeError("Run is bound to a different ExecutionSnapshot")
        snapshot = self._ledger.execution_snapshot(bound_run.snapshot_id)
        manifest = snapshot.manifest
        profile = _profile(_mapping(manifest, "agent_harness"))
        self._driver.validate(profile)
        current_lease = lease_provider or (lambda: lease)
        previous = self._ledger.projection(run_id)
        checkpoint = self._ledger.checkpoint(run_id)
        if checkpoint.stage or bound_run.status == "verifying":
            worktree, branch = Path(previous.worktree), previous.branch
            if not (worktree / ".git").exists():
                self._ledger.fail(run_id, "checkpoint worktree is unavailable", lease=lease)
                return self.report(run_id)
        else:
            worktree, branch = self._worktree(
                run_id,
                _mapping(manifest, "repository"),
                profile.timeout_seconds,
                current_lease,
            )
        candidate_created_here = False
        if bound_run.status == "queued" and checkpoint.stage in {
            CheckpointStage.CANDIDATE,
            CheckpointStage.VERIFIED,
            CheckpointStage.VERIFICATION_FAILED,
        }:
            current_lease()
            self._discard_worktree_pollution(
                worktree,
                checkpoint.candidate_commit,
                profile.timeout_seconds,
                current_lease,
            )
            self._ledger.clear_checkpoint(run_id, lease=current_lease())
            checkpoint = self._ledger.checkpoint(run_id)
        if not checkpoint.stage:
            attempts = previous.attempts
            if bound_run.status == "verifying" and attempts and attempts[-1].outcome == "completed":
                attempt_id = attempts[-1].attempt_id
                self._freeze_candidate(
                    worktree, run_id, profile.timeout_seconds, current_lease
                )
                candidate_commit = _git(worktree, "rev-parse", "HEAD")
                self._ledger.checkpoint_candidate(run_id, attempt_id, candidate_commit, lease=current_lease())
                checkpoint = self._ledger.checkpoint(run_id)
                candidate_created_here = True
            else:
                if len(attempts) >= profile.max_attempts:
                    raise RuntimeError("Agent Harness Profile max_attempts is exhausted")
                attempt_id = self._ledger.start_attempt(run_id, worktree=worktree, branch=branch, lease=current_lease())
                spec = AttemptSpec(run_id, attempt_id, worktree, _text(manifest, "instructions"), profile)
                outcome = self._execute_attempt(spec, current_lease)
                self._ledger.finish_attempt(attempt_id, outcome, lease=current_lease())
                if outcome.status != "completed":
                    return self.report(run_id)
                self._freeze_candidate(
                    worktree, run_id, profile.timeout_seconds, current_lease
                )
                candidate_commit = _git(worktree, "rev-parse", "HEAD")
                self._ledger.checkpoint_candidate(run_id, attempt_id, candidate_commit, lease=current_lease())
                checkpoint = self._ledger.checkpoint(run_id)
                candidate_created_here = True
        attempt_id = checkpoint.attempt_id
        candidate_commit = checkpoint.candidate_commit
        if checkpoint.stage == CheckpointStage.VERIFICATION_FAILED:
            self._ledger.fail(run_id, "Verification Harness failed", lease=current_lease())
            return self.report(run_id)
        if checkpoint.stage == CheckpointStage.CANDIDATE:
            if not candidate_created_here:
                current_lease()
                self._restore_candidate_commit(
                    worktree,
                    candidate_commit,
                    profile.timeout_seconds,
                    current_lease,
                )
            try:
                evidence = self._verify(
                    worktree, _mapping(manifest, "verification"), run_id, attempt_id,
                    candidate_commit, current_lease,
                )
            except Exception as error:
                if isinstance(error, LeaseConflictError):
                    raise
                self._ledger.fail(
                    run_id, f"Verification Harness failed: {error}", lease=current_lease()
                )
                return self.report(run_id)
            self._ledger.record_verification(run_id, evidence, lease=current_lease())
            if evidence.returncode != 0:
                self._ledger.fail(run_id, "Verification Harness failed", lease=current_lease())
                return self.report(run_id)
        if _git(worktree, "status", "--porcelain"):
            self._ledger.fail(run_id, "Verification Harness modified the candidate worktree", lease=current_lease())
            return self.report(run_id)
        if _git(worktree, "rev-parse", "HEAD") != candidate_commit:
            self._ledger.fail(run_id, "Verification Harness changed the candidate commit", lease=current_lease())
            return self.report(run_id)
        candidate = _mapping(manifest, "candidate")
        try:
            self._build_image(worktree, run_id, attempt_id, candidate_commit, candidate, profile.timeout_seconds, current_lease)
            self._publish(worktree, run_id, attempt_id, candidate_commit, candidate, profile.timeout_seconds, current_lease)
        except Exception as error:
            if isinstance(error, LeaseConflictError):
                raise
            self._ledger.fail(run_id, f"Candidate image or publication failed: {error}", lease=current_lease())
            return self.report(run_id)
        self._ledger.accept_candidate(run_id, candidate_commit, attempt_id=attempt_id, lease=current_lease())
        return self.report(run_id)

    def _execute_attempt(self, spec: AttemptSpec, lease_provider: Callable[[], Optional[RunLease]]) -> AttemptOutcome:
        try:
            context = multiprocessing.get_context("spawn")
        except ValueError:
            return AttemptOutcome.failed("Agent Harness Attempt isolation is unavailable on this host")
        events = result = supervised = None
        try:
            events = context.Queue(maxsize=_ACTIVITY_QUEUE_CAPACITY)
            result = _ProcessResultSpool.create()
            supervised = _start_supervised_process(
                context,
                f"attempt-{spec.attempt_id}",
                _attempt_process_entry,
                (self._driver, spec, events, result),
                lease_provider,
            )
        except Exception as error:
            for resource in (events, result):
                if resource is not None:
                    resource.close()
            if isinstance(error, LeaseConflictError):
                raise
            return AttemptOutcome.failed(f"Agent Harness Attempt isolation is unsupported: {error}")
        worker = supervised.worker
        try:
            deadline = time.monotonic() + spec.profile.timeout_seconds
            recorded_events = 0
            while worker.is_alive() and time.monotonic() < deadline:
                lease_provider()
                recorded_events += self._drain_attempt_events(
                    events,
                    spec,
                    lease_provider,
                    min(
                        _ACTIVITY_DRAIN_BATCH,
                        _MAX_ACTIVITY_EVENTS_PER_ATTEMPT - recorded_events,
                    ),
                )
                if _activity_budget_exceeded(events, recorded_events):
                    return AttemptOutcome.interrupted(
                        "Agent Harness Attempt exceeded its ActivityEvent budget"
                    )
                worker.join(min(0.05, max(0.0, deadline - time.monotonic())))
            recorded_events += self._drain_attempt_events(
                events,
                spec,
                lease_provider,
                min(
                    _ACTIVITY_DRAIN_BATCH,
                    _MAX_ACTIVITY_EVENTS_PER_ATTEMPT - recorded_events,
                ),
            )
            if _activity_budget_exceeded(events, recorded_events):
                return AttemptOutcome.interrupted(
                    "Agent Harness Attempt exceeded its ActivityEvent budget"
                )
            if worker.is_alive():
                return AttemptOutcome.interrupted(f"Agent Harness Attempt exceeded {spec.profile.timeout_seconds} seconds")
            try:
                kind, value = result.get()
            except (EOFError, FileNotFoundError, pickle.UnpicklingError):
                return AttemptOutcome.failed("Agent Harness Driver exited without an AttemptOutcome")
            if kind == "error":
                return AttemptOutcome.failed(f"Agent Harness Driver failed: {value}")
            if not isinstance(value, AttemptOutcome):
                return AttemptOutcome.failed("Agent Harness Driver returned an invalid AttemptOutcome")
            return value
        finally:
            supervised.close()
            events.close()
            events.join_thread()
            result.close()

    def _drain_attempt_events(
        self,
        events: object,
        spec: AttemptSpec,
        lease_provider: Callable[[], Optional[RunLease]],
        limit: int,
    ) -> int:
        drained = 0
        while drained < limit:
            try:
                event = events.get_nowait()
            except queue.Empty:
                return drained
            if isinstance(event, ActivityEvent) and _trace_covered(spec.profile, event):
                self._ledger.record_activity(spec.attempt_id, event, lease=lease_provider())
            drained += 1
        return drained

    def _run_external(
        self,
        deadline: float,
        operation: str,
        target: Callable[..., None],
        arguments: Tuple[object, ...],
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> Any:
        result = supervised = None
        try:
            context = multiprocessing.get_context("spawn")
            result = _ProcessResultSpool.create()
            supervised = _start_supervised_process(
                context,
                operation,
                target,
                (*arguments, result),
                lease_provider,
            )
        except Exception as error:
            for resource in (result,):
                if resource is not None:
                    resource.close()
            if isinstance(error, LeaseConflictError):
                raise
            raise RuntimeError(
                f"{operation} isolation is unsupported: {error}"
            ) from error
        worker = supervised.worker
        try:
            while worker.is_alive() and time.monotonic() < deadline:
                lease_provider()
                worker.join(min(0.05, max(0.0, deadline - time.monotonic())))
            if worker.is_alive():
                raise RuntimeError(f"{operation} exceeded its admitted timeout")
            lease_provider()
            try:
                kind, value = result.get()
            except (EOFError, FileNotFoundError, pickle.UnpicklingError) as error:
                raise RuntimeError(f"{operation} exited without a result") from error
            if kind == "error":
                raise RuntimeError(f"{operation} failed: {value}")
            return value
        finally:
            supervised.close()
            result.close()

    def report(self, run_id: str) -> RunReport:
        return self._ledger.projection(run_id)

    def evidence(self, run_id: str, artifact_id: str):
        report = self.report(run_id)
        references = tuple(
            reference
            for evidence in report.evidence
            for reference in (evidence.stdout_ref, evidence.stderr_ref, *evidence.artifact_refs)
            if reference is not None
        )
        reference = next((item for item in references if item.artifact_id == artifact_id), None)
        if reference is None:
            raise KeyError(f"Evidence artifact is not referenced by Run {run_id!r}")
        return self._evidence.read(artifact_id, reference=reference)

    def prune_evidence(self, older_than_days: int):
        return self._evidence.prune(older_than_days)

    def resume(self, run_id: str) -> RunReport:
        self._ledger.retry(run_id)
        return self.report(run_id)

    def _worktree(
        self,
        run_id: str,
        repository: Mapping[str, object],
        timeout_seconds: int,
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> Tuple[Path, str]:
        worktree = self._state_dir / "worktrees" / run_id
        branch = f"aiwb/{run_id}"
        if not (worktree / ".git").exists():
            worktree.parent.mkdir(parents=True, exist_ok=True)
            returncode, _stdout, stderr = self._run_external(
                time.monotonic() + timeout_seconds,
                "worktree-git-add",
                _git_write_process_entry,
                (
                    Path(str(repository["path"])),
                    (
                        "worktree",
                        "add",
                        "-B",
                        branch,
                        str(worktree),
                        str(repository["base_commit"]),
                    ),
                ),
                lease_provider,
            )
            if returncode:
                raise RuntimeError(stderr.strip() or "cannot prepare the Run worktree")
        return worktree, branch

    def _verify(self, worktree: Path, definition: Mapping[str, object], run_id: str, attempt_id: str, candidate_commit: str, lease_provider: Callable[[], Optional[RunLease]]) -> VerificationEvidence:
        command = tuple(str(item) for item in definition["command"])
        started = time.monotonic()
        profile_value = definition.get("harness")
        if isinstance(profile_value, Mapping):
            profile = _harness_from_value(profile_value)
            request = HarnessRequest(
                profile=profile, command=command, cwd=worktree,
                timeout_seconds=int(definition["timeout_seconds"]), run_id=run_id,
                artifact_dir=self._state_dir / "artifacts" / run_id / "verification",
                execution_id=attempt_id, stage="verification",
            )
            adapter = self._local_harness if profile.kind == "local_process" else self._kubernetes_harness
            completed = self._run_external(
                started + request.timeout_seconds, "verification", _verification_process_entry,
                (adapter, request), lease_provider,
            )
            return self._retain_execution(command, completed, started, attempt_id, candidate_commit)
        request = HarnessRequest(
            profile=HarnessProfile(name="command", kind="command", environment="local"),
            command=command, cwd=worktree, timeout_seconds=int(definition["timeout_seconds"]),
            run_id=run_id, artifact_dir=self._state_dir / "artifacts" / run_id / "verification",
            execution_id=attempt_id, stage="verification",
        )
        execution = self._run_external(
            started + request.timeout_seconds, "verification", _verification_process_entry,
            (self._command_harness, request), lease_provider,
        )
        return self._retain_execution(command, execution, started, attempt_id, candidate_commit)

    def _freeze_candidate(
        self,
        worktree: Path,
        run_id: str,
        timeout_seconds: int,
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> None:
        if not _git(worktree, "status", "--porcelain"):
            return
        for operation, arguments, fallback in (
            ("candidate-git-add", ("add", "--all"), "cannot stage Harness changes"),
            (
                "candidate-git-commit",
                ("commit", "-m", f"aiwb: candidate {run_id}"),
                "cannot freeze Harness changes",
            ),
        ):
            completed = self._run_external(
                time.monotonic() + timeout_seconds,
                operation,
                _git_write_process_entry,
                (worktree, arguments),
                lease_provider,
            )
            returncode, _stdout, stderr = completed
            if returncode:
                raise RuntimeError(stderr.strip() or fallback)

    def _restore_candidate_commit(
        self,
        worktree: Path,
        candidate_commit: str,
        timeout_seconds: int,
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> None:
        for operation, arguments in (
            ("candidate-git-reset", ("reset", "--hard", candidate_commit)),
            ("candidate-git-clean", ("clean", "-fd")),
        ):
            returncode, _stdout, stderr = self._run_external(
                time.monotonic() + timeout_seconds,
                operation,
                _git_write_process_entry,
                (worktree, arguments),
                lease_provider,
            )
            if returncode:
                raise RuntimeError(
                    stderr.strip() or "cannot restore the Candidate worktree"
                )

    def _discard_worktree_pollution(
        self,
        worktree: Path,
        candidate_commit: str,
        timeout_seconds: int,
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> None:
        self._restore_candidate_commit(
            worktree, candidate_commit, timeout_seconds, lease_provider
        )
        returncode, _stdout, stderr = self._run_external(
            time.monotonic() + timeout_seconds,
            "candidate-git-clean",
            _git_write_process_entry,
            (worktree, ("clean", "-fdx")),
            lease_provider,
        )
        if returncode:
            raise RuntimeError(
                stderr.strip() or "cannot clean the Candidate worktree"
            )

    def _retain_execution(self, command: Tuple[str, ...], execution: HarnessExecution, started: float, attempt_id: str, candidate_commit: str) -> VerificationEvidence:
        stdout, stdout_ref = self._evidence.retain_text(execution.stdout, label="verification stdout")
        stderr, stderr_ref = self._evidence.retain_text(execution.stderr, label="verification stderr")
        artifact_refs = tuple(self._retain_artifact(path, "verification") for path in execution.artifacts)
        return VerificationEvidence(command, execution.returncode, stdout, stderr, time.monotonic() - started, stdout_ref, stderr_ref, execution.artifacts, execution.environment, artifact_refs, attempt_id, candidate_commit, "verification")

    def _retain_artifact(self, value: str, source: str) -> EvidenceReference:
        path = Path(value)
        if path.is_file():
            return self._evidence.retain_file(path, label=f"{source} artifact: {path.name}")
        return self._evidence.retain_bytes(
            value.encode("utf-8"),
            label=f"{source} artifact reference",
            media_type="text/plain; charset=utf-8",
        )

    def _build_image(self, worktree: Path, run_id: str, attempt_id: str, candidate_commit: str, candidate: Mapping[str, object], timeout_seconds: int, lease_provider: Callable[[], Optional[RunLease]]) -> None:
        image_value = candidate.get("image")
        if not isinstance(image_value, Mapping):
            return
        profile = _image_from_value(image_value)
        request = ImageBuildRequest(profile, worktree, run_id, self._state_dir / "artifacts" / run_id / "image")
        checkpoint = self._ledger.checkpoint(run_id)
        deadline = time.monotonic() + timeout_seconds
        if checkpoint.stage == CheckpointStage.IMAGE_STARTING:
            raise RuntimeError("image start outcome is unknown; refusing to repeat the external build")
        if checkpoint.stage == CheckpointStage.IMAGE_RUNNING:
            operation_id = checkpoint.operation_id
        elif checkpoint.stage in {CheckpointStage.IMAGE_COMPLETE, CheckpointStage.PUBLISH_STARTING, CheckpointStage.PUBLISHED, CheckpointStage.ACCEPTED}:
            return
        else:
            self._ledger.checkpoint_image_starting(run_id, attempt_id, candidate_commit, lease=lease_provider())
            operation_id = self._image_call(deadline, "image-start", "start", request, lease_provider=lease_provider)
            self._ledger.checkpoint_image_running(run_id, attempt_id, candidate_commit, operation_id, lease=lease_provider())
        while self._image_call(
            deadline, "image-status", "status", request, operation_id,
            lease_provider=lease_provider,
        ) in {"queued", "running"}:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"image build exceeded {timeout_seconds} seconds")
            time.sleep(0.01)
        result = self._image_call(
            deadline, "image-result", "result", request, operation_id,
            lease_provider=lease_provider,
        )
        stdout, stdout_ref = self._evidence.retain_text(result.digest, label="image digest")
        artifact_refs = tuple(self._retain_artifact(path, "image") for path in result.artifacts)
        self._ledger.record_verification(run_id, VerificationEvidence(("image", profile.name), 0, stdout, "", 0.0, stdout_ref, None, result.artifacts, profile.environment, artifact_refs, attempt_id, candidate_commit, "image"), lease=lease_provider())

    def _image_call(
        self,
        deadline: float,
        operation: str,
        method: str,
        request: ImageBuildRequest,
        operation_id: str = "",
        *,
        lease_provider: Callable[[], Optional[RunLease]],
    ) -> Any:
        return self._run_external(
            deadline, operation, _image_process_entry,
            (self._image_builder, method, request, operation_id), lease_provider,
        )

    def _publish(self, worktree: Path, run_id: str, attempt_id: str, commit: str, candidate: Mapping[str, object], timeout_seconds: int, lease_provider: Callable[[], Optional[RunLease]]) -> None:
        publish_value = candidate.get("publish")
        if not isinstance(publish_value, Mapping):
            return
        checkpoint = self._ledger.checkpoint(run_id)
        if checkpoint.stage == CheckpointStage.PUBLISH_STARTING:
            raise RuntimeError("publication outcome is unknown; refusing to repeat the external publish")
        if checkpoint.stage in {CheckpointStage.PUBLISHED, CheckpointStage.ACCEPTED}:
            return
        profile = CandidatePublishProfile(**dict(publish_value))
        branch = f"{profile.branch_prefix}{Path(worktree).name}"
        self._ledger.checkpoint_publish_starting(run_id, attempt_id, commit, lease=lease_provider())
        result = self._run_external(
            time.monotonic() + timeout_seconds, "publication", _publish_process_entry,
            (self._publisher, CandidatePublishRequest(worktree, branch, commit, profile)), lease_provider,
        )
        self._ledger.checkpoint_published(run_id, attempt_id, commit, asdict(result), lease=lease_provider())

    def sweep_kubernetes(self) -> None:
        KubernetesJanitor(self._state_dir).sweep()


def _contract(source: bytes) -> Mapping[str, object]:
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise AdmissionError(f"invalid Contract YAML: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != ADMISSION_SCHEMA_VERSION:
        raise AdmissionError(f"Contract schema_version must be {ADMISSION_SCHEMA_VERSION}")
    _mapping(data, "approval")
    profile_value = _mapping(data, "agent_harness")
    _goal(_mapping(data, "goal")); _text(data, "instructions"); _profile(profile_value); _mapping(data, "project"); _verification(_mapping(data, "verification"), Path("."), None, validate_harness=False)
    return data


def _resolve_execution_input(
    contract_path: Path,
    workflow_path: Optional[Path] = None,
) -> Tuple[bytes, Mapping[str, object], Mapping[str, object]]:
    """Resolve every behavior-affecting Contract input before owner approval."""
    path = Path(contract_path).expanduser().resolve()
    source = path.read_bytes()
    data = _contract(source)
    _reject_secret_material(source, data)
    project = _mapping(data, "project")
    repository = Path(_text(project, "repo")).expanduser().resolve()
    if not repository.is_dir():
        raise AdmissionError(f"project.repo is not a directory: {repository}")
    base_ref = _text(project, "base_ref")
    base_commit = _git(
        repository, "rev-parse", "--verify", f"{base_ref}^{{commit}}"
    )
    profile = _profile(_mapping(data, "agent_harness"))
    profile = replace(
        profile,
        resolved_extensions=_validate_harness_extensions(
            repository, base_commit, profile
        ),
    )
    policy = _policy_for(project, workflow_path, path)
    required_secrets = data.get("required_secrets", ())
    if not isinstance(required_secrets, (tuple, list)) or not all(
        _valid_secret_reference(value) for value in required_secrets
    ):
        raise AdmissionError("ExecutionManifest required_secrets must be references")
    execution = {
        "goal": _json_value(_mapping(data, "goal")),
        "instructions": _text(data, "instructions"),
        "agent_harness": _profile_value(profile),
        "repository": {
            "path": str(repository),
            "base_ref": base_ref,
            "base_commit": base_commit,
        },
        "verification": _verification(
            _mapping(data, "verification"), repository, policy
        ),
        "candidate": _candidate(data.get("candidate"), repository, policy),
        "required_secrets": tuple(required_secrets),
    }
    _reject_secret_material(source, execution)
    return source, data, MappingProxyType(execution)


def _execution_digest(execution: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(execution).encode("utf-8")).hexdigest()


def _approval_artifact_path(
    data: Mapping[str, object], contract_path: Path
) -> Path:
    value = Path(_text(_mapping(data, "approval"), "artifact_path")).expanduser()
    if not value.is_absolute():
        value = Path(contract_path).resolve().parent / value
    return value.resolve()


def _load_execution_approval(
    data: Mapping[str, object],
    contract_path: Path,
    execution: Mapping[str, object],
) -> Mapping[str, object]:
    artifact_path = _approval_artifact_path(data, contract_path)
    try:
        approval = json.loads(artifact_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AdmissionError("Contract requires an external execution approval artifact") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdmissionError(f"cannot read execution approval artifact: {error}") from error
    expected_execution = _json_value(execution)
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise AdmissionError("Execution approval artifact is not approved")
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
        raise AdmissionError("Execution approval artifact requires an approver")
    if approval.get("artifact_path") != str(artifact_path):
        raise AdmissionError("Execution approval artifact path does not match its content")
    if (
        approval.get("execution_digest") != _execution_digest(execution)
        or approval.get("execution") != expected_execution
    ):
        raise AdmissionError(
            "Execution approval artifact does not match the complete execution"
        )
    return MappingProxyType(approval)


def _validate_harness_extensions(
    repository: Path, base_commit: str, profile: AgentHarnessProfile
) -> Tuple[Mapping[str, object], ...]:
    """Resolve supported project-local extensions at the frozen base commit."""
    resolved = []
    for extension in profile.extensions:
        match = re.fullmatch(
            r"(skill|mcp|plugin|hook|command):([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+)",
            extension,
        )
        if match is None:
            raise AdmissionError(f"Harness extension is unsupported or unresolved: {extension}")
        kind, name, version = match.groups()
        source = None
        selected_path = ""
        if kind == "skill":
            skill_root = AGENT_SKILL_ROOTS.get(profile.driver)
            if skill_root is None:
                raise AdmissionError(
                    f"Harness Driver does not declare a Skill install root: {profile.driver}"
                )
            candidates = (
                f"{skill_root}/{name}/SKILL.md",
                f".agents/skills/{name}/SKILL.md",
                f"skills/{name}/SKILL.md",
            )
        else:
            candidates = (f".ai-workbench/extensions/{kind}/{name}.yaml",)
        for relative in candidates:
            completed = subprocess.run(
                ["git", "-C", str(repository), "show", f"{base_commit}:{relative}"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode == 0:
                source = completed.stdout
                selected_path = relative
                break
        if source is None:
            raise AdmissionError(f"Harness extension is not installed at the frozen base commit: {extension}")
        try:
            text = source.decode("utf-8")
            if kind == "skill":
                if not text.startswith("---\n"):
                    raise ValueError("missing metadata")
                end = text.find("\n---\n", 4)
                if end == -1:
                    raise ValueError("unterminated metadata")
                metadata = yaml.safe_load(text[4:end])
            else:
                metadata = yaml.safe_load(text)
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
            raise AdmissionError(f"Harness extension metadata is invalid: {extension}: {error}") from error
        if not isinstance(metadata, Mapping):
            raise AdmissionError(f"Harness extension metadata is invalid: {extension}")
        if (
            metadata.get("name") != name
            or str(metadata.get("version", "")) != version
            or (kind != "skill" and metadata.get("kind") != kind)
        ):
            raise AdmissionError(f"Harness extension identity or version does not match: {extension}")
        if kind != "skill" and metadata.get("driver") != profile.driver:
            raise AdmissionError(
                f"Harness extension is not registered for Agent Harness Driver {profile.driver}: {extension}"
            )
        if kind != "skill" and (
            not isinstance(metadata.get("configuration"), Mapping)
            or not metadata["configuration"]
        ):
            raise AdmissionError(f"Harness extension configuration is unavailable: {extension}")
        resolved_extension = {
            "identity": extension,
            "path": selected_path,
            "sha256": hashlib.sha256(source).hexdigest(),
            "descriptor": _json_value(metadata),
        }
        if kind != "skill":
            entrypoint = metadata["configuration"].get("entrypoint")
            entrypoint_path = Path(entrypoint) if isinstance(entrypoint, str) else Path()
            if (
                not isinstance(entrypoint, str)
                or not entrypoint
                or entrypoint_path.is_absolute()
                or ".." in entrypoint_path.parts
            ):
                raise AdmissionError(
                    f"Harness extension has no callable entrypoint: {extension}"
                )
            tree = subprocess.run(
                (
                    "git",
                    "-C",
                    str(repository),
                    "ls-tree",
                    base_commit,
                    "--",
                    entrypoint,
                ),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            fields = tree.stdout.strip().split(maxsplit=3)
            if tree.returncode or len(fields) != 4 or fields[:2] != ["100755", "blob"]:
                raise AdmissionError(
                    f"Harness extension has no callable entrypoint at the frozen base commit: {extension}"
                )
            entrypoint_source = subprocess.run(
                (
                    "git",
                    "-C",
                    str(repository),
                    "show",
                    f"{base_commit}:{entrypoint}",
                ),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if entrypoint_source.returncode:
                raise AdmissionError(
                    f"Harness extension has no callable entrypoint at the frozen base commit: {extension}"
                )
            resolved_extension["entrypoint"] = {
                "path": entrypoint,
                "sha256": hashlib.sha256(entrypoint_source.stdout).hexdigest(),
            }
        resolved.append(MappingProxyType(resolved_extension))
    return tuple(resolved)


def _goal(value: Mapping[str, object]) -> None:
    for name in ("id", "title", "requirement"):
        _text(value, name)
    acceptance = value.get("acceptance")
    if not isinstance(acceptance, (tuple, list)) or not acceptance:
        raise AdmissionError("goal.acceptance must be non-empty")


def _profile(value: Mapping[str, object]) -> AgentHarnessProfile:
    def strings(name: str) -> Tuple[str, ...]:
        raw = value.get(name)
        if not isinstance(raw, (tuple, list)):
            raise AdmissionError(f"agent_harness.{name} must be a sequence")
        if not all(isinstance(item, str) and item for item in raw):
            raise AdmissionError(f"agent_harness.{name} must contain non-empty strings")
        return tuple(raw)
    try:
        resolved = value.get("resolved_extensions", ())
        if not isinstance(resolved, (tuple, list)) or not all(
            isinstance(item, Mapping) for item in resolved
        ):
            raise AdmissionError("agent_harness.resolved_extensions must be mappings")
        return AgentHarnessProfile(
            _text(value, "driver"), _text(value, "model"), _text(value, "effort"),
            strings("permissions"), strings("capability_ceiling"), strings("extensions"),
            strings("allowed_paths"), strings("tools"), _text(value, "input_artifact"),
            _text(value, "output_schema"), _positive(value, "timeout_seconds"),
            _positive(value, "max_attempts"), _mapping(value, "resource_limits"),
            _mapping(value, "native_configuration"), strings("trace_coverage"),
            tuple(resolved),
        )
    except ValueError as error:
        raise AdmissionError(str(error)) from error


def _verification(value: Mapping[str, object], repository: Path, policy: Optional[ProjectPolicy], *, validate_harness: bool = True) -> Mapping[str, object]:
    command = value.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise AdmissionError("verification.command must be a non-empty string list")
    timeout = value.get("timeout_seconds", 600)
    if not isinstance(timeout, int) or timeout <= 0:
        raise AdmissionError("verification.timeout_seconds must be positive")
    harness_name = value.get("harness", "")
    if not isinstance(harness_name, str):
        raise AdmissionError("verification.harness must be a string")
    if harness_name and policy is None and validate_harness:
        raise AdmissionError("verification Harness requires an approved project policy")
    try:
        profile = policy.authorize(repository, tuple(command), harness_name) if policy else None
    except ProjectConfigError as error:
        raise AdmissionError(str(error)) from error
    result: dict[str, object] = {"command": tuple(command), "timeout_seconds": timeout}
    if profile is not None:
        result["harness"] = _harness_value(profile)
    return result


def _policy_for(project: Mapping[str, object], workflow_path: Optional[Path], contract_path: Path) -> Optional[ProjectPolicy]:
    configured = project.get("policy")
    if configured is not None and not isinstance(configured, str):
        raise AdmissionError("project.policy must be a path string")
    selected = Path(configured) if configured else workflow_path
    if selected is None:
        return None
    path = selected if selected.is_absolute() else (contract_path.parent / selected)
    try:
        return ProjectPolicy.load(path)
    except ProjectConfigError as error:
        raise AdmissionError(str(error)) from error


def _candidate(value: object, repository: Path, policy: Optional[ProjectPolicy]) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AdmissionError("candidate must be a mapping")
    image_name = value.get("image_profile", "")
    publish = value.get("publish", False)
    if not isinstance(image_name, str) or not isinstance(publish, bool):
        raise AdmissionError("candidate image_profile and publish are invalid")
    if (image_name or publish) and policy is None:
        raise AdmissionError("candidate image or publication requires an approved project policy")
    result: dict[str, object] = {}
    try:
        image = policy.authorize_image(image_name) if policy else None
        if image is not None:
            result["image"] = _image_value(image)
        publication = policy.authorize_publish(repository) if publish and policy else None
        if publication is not None:
            result["publish"] = asdict(publication)
    except ProjectConfigError as error:
        raise AdmissionError(str(error)) from error
    return result


def _positive(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        raise AdmissionError(f"agent_harness.{name} must be positive")
    return result


def _profile_value(profile: AgentHarnessProfile) -> Mapping[str, object]:
    return {
        "driver": profile.driver, "model": profile.model, "effort": profile.effort,
        "permissions": profile.permissions, "capability_ceiling": profile.capability_ceiling,
        "extensions": profile.extensions, "allowed_paths": profile.allowed_paths,
        "tools": profile.tools, "input_artifact": profile.input_artifact,
        "output_schema": profile.output_schema, "timeout_seconds": profile.timeout_seconds,
        "max_attempts": profile.max_attempts, "resource_limits": profile.resource_limits,
        "native_configuration": profile.native_configuration, "trace_coverage": profile.trace_coverage,
        "resolved_extensions": profile.resolved_extensions,
    }


def _harness_value(profile: HarnessProfile) -> Mapping[str, object]:
    value = asdict(profile)
    return _json_value(value)


def _harness_from_value(value: Mapping[str, object]) -> HarnessProfile:
    copied = dict(value)
    diagnostic = copied.get("browser_diagnostic")
    if isinstance(diagnostic, Mapping):
        copied["browser_diagnostic"] = BrowserDiagnosticProfile(
            adapter=str(diagnostic["adapter"]), command=tuple(diagnostic["command"]),
            timeout_seconds=int(diagnostic["timeout_seconds"]),
        )
    for name in ("start_command", "provision_command", "collect_command", "cleanup_command"):
        if name in copied:
            copied[name] = tuple(copied[name])
    return HarnessProfile(**copied)


def _image_value(profile: ImageProfile) -> Mapping[str, object]:
    return _json_value(asdict(profile))


def _image_from_value(value: Mapping[str, object]) -> ImageProfile:
    copied = dict(value)
    for name in ("start_command", "status_command", "result_command"):
        copied[name] = tuple(copied[name])
    return ImageProfile(**copied)


def _mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    result = value.get(name)
    if not isinstance(result, Mapping):
        raise AdmissionError(f"{name} must be a mapping")
    return result


def _text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise AdmissionError(f"{name} must be a non-empty string")
    return result


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_value(value: object) -> Any:
    if isinstance(value, EvidenceReference):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def _snapshot_id(source: bytes, manifest: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json({"source": hashlib.sha256(source).hexdigest(), "manifest": manifest}).encode("utf-8")).hexdigest()


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(path), *args], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise AdmissionError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _instant(value: Optional[datetime]) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _reference_json(value: Optional[EvidenceReference]) -> Optional[str]:
    return json.dumps(asdict(value), sort_keys=True) if value is not None else None


def _reference(value: Optional[str]) -> Optional[EvidenceReference]:
    return EvidenceReference(**json.loads(value)) if value else None


def _references_json(values: Sequence[EvidenceReference]) -> str:
    return json.dumps([asdict(value) for value in values], sort_keys=True)


def _references(value: str) -> Tuple[EvidenceReference, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise AdmissionError("Evidence artifact references are invalid")
    return tuple(EvidenceReference(**item) for item in decoded if isinstance(item, dict))


def _evidence_from_row(row: sqlite3.Row) -> VerificationEvidence:
    return VerificationEvidence(tuple(json.loads(row["command_json"])), row["returncode"], row["stdout"], row["stderr"], row["duration_seconds"], _reference(row["stdout_ref_json"]), _reference(row["stderr_ref_json"]), tuple(json.loads(row["artifacts_json"])), row["environment"], _references(row["artifact_refs_json"]), row["attempt_id"], row["candidate_commit"], row["stage"])


def _evidence_from_value(value: Mapping[str, object]) -> VerificationEvidence:
    def reference(item: object) -> Optional[EvidenceReference]:
        return EvidenceReference(**item) if isinstance(item, dict) else None
    artifact_refs = tuple(
        EvidenceReference(**item)
        for item in value.get("artifact_refs", ())
        if isinstance(item, dict)
    )
    return VerificationEvidence(tuple(value["command"]), int(value["returncode"]), str(value["stdout"]), str(value["stderr"]), float(value["duration_seconds"]), reference(value.get("stdout_ref")), reference(value.get("stderr_ref")), tuple(value.get("artifacts", ())), str(value.get("environment", "")), artifact_refs, str(value.get("attempt_id", "")), str(value.get("candidate_commit", "")), str(value.get("stage", "verification")))


def _trace_covered(profile: AgentHarnessProfile, event: ActivityEvent) -> bool:
    coverage = {
        "activity": "activity", "edit": "activity", "error": "activity",
        "status": "activity", "extension": "extension", "tool": "tool",
        "lifecycle": "lifecycle", "session": "session", "terminal": "terminal",
        "usage": "usage",
    }[event.kind]
    return coverage in profile.trace_coverage


def _reject_secret_material(source: bytes, manifest: Mapping[str, object]) -> None:
    _reject_literal_secret_values(manifest, path="Contract")
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if any(marker in name.upper() for marker in ("API_KEY", "CREDENTIAL", "PASSWORD", "PASSWD", "PRIVATE_KEY", "SECRET", "TOKEN")) and value.encode("utf-8") in source:
            raise AdmissionError(f"Admission input contains secret material from {name}")


def _reject_literal_secret_values(value: object, *, path: str) -> None:
    secret_field = re.compile(r"(?:^|_)(?:api_key|credential|password|passwd|private_key|secret|token)$", re.IGNORECASE)
    secret_text = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S{8,}", re.IGNORECASE),
        re.compile(r"--(?:api-key|token|secret|password)(?:=|\s+)\S+", re.IGNORECASE),
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if secret_field.search(str(key)):
                raise AdmissionError(f"Admission input contains a literal secret field at {item_path}; use required_secrets references")
            _reject_literal_secret_values(item, path=item_path)
        return
    if isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _reject_literal_secret_values(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in secret_text):
        raise AdmissionError(f"Admission input contains literal secret material at {path}; use required_secrets references")


def _valid_secret_reference(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"(?:env:[A-Za-z_][A-Za-z0-9_]*|keychain:[A-Za-z0-9_][A-Za-z0-9._/@:-]*)",
        value,
    ) is not None
