from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, AbstractSet, Callable, Mapping, Optional, Protocol, Tuple

import yaml

from .runner import ContractError, _RunLedgerExecutionOperations, _load_contract


ADMISSION_SCHEMA_VERSION = 1


class AdmissionError(ValueError):
    pass


class LeaseConflictError(RuntimeError):
    """The worker no longer owns the fenced Lease it presented."""


@dataclass(frozen=True)
class RunLease:
    run_id: str
    owner_id: str
    generation: int
    expires_at: str


@dataclass(frozen=True)
class AdmissionRequest:
    contract_path: Path
    workflow_path: Optional[Path] = None
    idempotency_key: Optional[str] = None


class ExecutionManifest(Mapping[str, object]):
    """Validated, deeply immutable execution authority for an admitted Run."""

    def __init__(self, values: Mapping[str, object]) -> None:
        if values.get("schema_version") != ADMISSION_SCHEMA_VERSION:
            raise AdmissionError(
                "ExecutionManifest schema_version is not supported"
            )
        versions = values.get("versions")
        if not isinstance(versions, Mapping):
            raise AdmissionError("ExecutionManifest versions must be a mapping")
        if versions.get("admission_schema") != ADMISSION_SCHEMA_VERSION:
            raise AdmissionError(
                "ExecutionManifest admission_schema is not supported"
            )
        for name in ("engine", "transition_policy"):
            value = versions.get(name)
            if not isinstance(value, str) or not value:
                raise AdmissionError(
                    f"ExecutionManifest {name} version must be non-empty"
                )
        mapping_fields = (
            "goal",
            "agent",
            "repository",
            "resources",
            "role_guidance",
            "policy",
        )
        for name in mapping_fields:
            if not isinstance(values.get(name), Mapping):
                raise AdmissionError(
                    f"ExecutionManifest {name} must be a mapping"
                )
        if not isinstance(values.get("approval_status"), str):
            raise AdmissionError(
                "ExecutionManifest approval_status must be a string"
            )
        todos = values.get("todos")
        if not isinstance(todos, (tuple, list)) or not todos:
            raise AdmissionError("ExecutionManifest todos must be non-empty")
        for name in ("image_profile", "publish_policy"):
            value = values.get(name)
            if value is not None and not isinstance(value, Mapping):
                raise AdmissionError(
                    f"ExecutionManifest {name} must be a mapping or null"
                )
        required_secrets = values.get("required_secrets")
        if not isinstance(required_secrets, (tuple, list)) or not all(
            isinstance(item, str) for item in required_secrets
        ):
            raise AdmissionError(
                "ExecutionManifest required_secrets must be references"
            )
        _validate_manifest_details(values)
        frozen = _freeze_json(values)
        if not isinstance(frozen, Mapping):  # pragma: no cover - construction guard
            raise AdmissionError("ExecutionManifest must be a mapping")
        self._values = frozen

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"ExecutionManifest({self._values!r})"


@dataclass(frozen=True)
class ExecutionSnapshot:
    snapshot_id: str
    source: bytes
    manifest: ExecutionManifest
    created_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExecutionManifest):
            object.__setattr__(
                self,
                "manifest",
                ExecutionManifest(self.manifest),
            )


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    snapshot_id: str
    goal_id: str
    status: str
    created_at: str
    error: str = ""


@dataclass(frozen=True)
class AdmittedRun:
    run_id: str
    snapshot_id: str
    goal_id: str
    status: str


class RunLedger(Protocol):
    def admit(
        self,
        snapshot: ExecutionSnapshot,
        *,
        goal_id: str,
        idempotency_key: Optional[str] = None,
    ) -> AdmittedRun:
        ...

    def execution_snapshot(self, snapshot_id: str) -> ExecutionSnapshot:
        ...

    def execution_snapshots(self) -> Tuple[ExecutionSnapshot, ...]:
        ...

    def run(self, run_id: str) -> RunRecord:
        ...

    def queued_runs(self) -> Tuple[RunRecord, ...]:
        ...

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
        ...

    def renew(
        self,
        lease: RunLease,
        *,
        lease_seconds: float,
        now: Optional[datetime] = None,
    ) -> RunLease:
        ...

    def prove(
        self,
        lease: RunLease,
        *,
        now: Optional[datetime] = None,
    ) -> RunLease:
        ...

    def transition(
        self,
        run_id: str,
        *,
        owner_id: str,
        generation: int,
        status: str,
        error: str = "",
        now: Optional[datetime] = None,
    ) -> RunRecord:
        ...

    def requeue(self, run_id: str) -> RunRecord:
        ...


class SQLiteRunLedger(_RunLedgerExecutionOperations):
    def __init__(
        self,
        database: Path,
        *,
        _fault_injector: Optional[Callable[[str], None]] = None,
        _worker_fault_injector: Optional[
            Callable[[str, sqlite3.Connection, str], None]
        ] = None,
    ) -> None:
        self._database = Path(database)
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._fault_injector = _fault_injector
        self._worker_fault_injector = _worker_fault_injector
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    source BLOB NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._initialize_execution_state(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS run_queue (
                    run_id TEXT PRIMARY KEY,
                    enqueued_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS run_leases (
                    run_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    renewed_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS run_transitions (
                    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    error TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                """
            )

    def admit(
        self,
        snapshot: ExecutionSnapshot,
        *,
        goal_id: str,
        idempotency_key: Optional[str] = None,
    ) -> AdmittedRun:
        expected_snapshot_id = _snapshot_id(snapshot.source, snapshot.manifest)
        if snapshot.snapshot_id != expected_snapshot_id:
            raise AdmissionError(
                "ExecutionSnapshot snapshot identity does not match its source "
                "and manifest"
            )
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = connection.execute(
                    """
                    SELECT runs.*
                    FROM idempotency_keys
                    JOIN runs USING (run_id)
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["snapshot_id"] != snapshot.snapshot_id:
                        raise AdmissionError(
                            "idempotency key was already used for a different "
                            "ExecutionSnapshot"
                        )
                    return _admitted_run(existing)
            connection.execute(
                """
                INSERT OR IGNORE INTO execution_snapshots (
                    snapshot_id, source, manifest_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.source,
                    _canonical_json(snapshot.manifest),
                    snapshot.created_at,
                ),
            )
            self._inject("after_snapshot")
            run_id = f"{goal_id}-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, snapshot_id, goal_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (run_id, snapshot.snapshot_id, goal_id, now, now),
            )
            self._inject("after_run")
            connection.execute(
                "INSERT INTO run_queue (run_id, enqueued_at) VALUES (?, ?)",
                (run_id, now),
            )
            self._inject("after_enqueue")
            if idempotency_key is not None:
                connection.execute(
                    """
                    INSERT INTO idempotency_keys (idempotency_key, run_id)
                    VALUES (?, ?)
                    """,
                    (idempotency_key, run_id),
                )
                self._inject("after_idempotency")
        return AdmittedRun(
            run_id=run_id,
            snapshot_id=snapshot.snapshot_id,
            goal_id=goal_id,
            status="queued",
        )

    def execution_snapshot(self, snapshot_id: str) -> ExecutionSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown ExecutionSnapshot: {snapshot_id}")
        return _execution_snapshot(row)

    def execution_snapshots(self) -> Tuple[ExecutionSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_snapshots ORDER BY created_at, snapshot_id"
            ).fetchall()
        return tuple(_execution_snapshot(row) for row in rows)

    def run(self, run_id: str) -> RunRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Run: {run_id}")
        return _run_record(row)

    def queued_runs(self) -> Tuple[RunRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT runs.*
                FROM run_queue
                JOIN runs USING (run_id)
                WHERE runs.status IN ('queued', 'running')
                ORDER BY run_queue.enqueued_at, runs.run_id
                """
            ).fetchall()
        return tuple(_run_record(row) for row in rows)

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
        if not owner_id:
            raise ValueError("owner_id must be non-empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        expires_at = instant + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown Run: {run_id}")
            if run["status"] not in {"queued", "running"}:
                return None
            queued = connection.execute(
                "SELECT 1 FROM run_queue WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if queued is None:
                return None
            current = connection.execute(
                "SELECT * FROM run_leases WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if current is not None and _parse_instant(current["expires_at"]) > instant:
                if current["owner_id"] != owner_id:
                    return None
                return _run_lease(current)
            incompatibility = self._incompatible_reason(
                connection,
                run["snapshot_id"],
                supported_engine_versions=supported_engine_versions,
                supported_admission_schema_versions=(
                    supported_admission_schema_versions
                ),
                supported_transition_policy_versions=(
                    supported_transition_policy_versions
                ),
            )
            if incompatibility:
                connection.execute(
                    "UPDATE runs SET status = 'incompatible_engine', error = ? "
                    "WHERE run_id = ?",
                    (incompatibility, run_id),
                )
                connection.execute("DELETE FROM run_queue WHERE run_id = ?", (run_id,))
                connection.execute("DELETE FROM run_leases WHERE run_id = ?", (run_id,))
                connection.execute(
                    """
                    INSERT INTO run_transitions (
                        run_id, generation, from_status, to_status, error, recorded_at
                    ) VALUES (?, ?, ?, 'incompatible_engine', ?, ?)
                    """,
                    (
                        run_id,
                        int(run["lease_generation"]),
                        run["status"],
                        incompatibility,
                        instant.isoformat(),
                    ),
                )
                return None
            generation = int(run["lease_generation"]) + 1
            connection.execute(
                "UPDATE runs SET status = 'running', error = '', lease_generation = ? "
                "WHERE run_id = ?",
                (generation, run_id),
            )
            connection.execute(
                """
                INSERT INTO run_leases (
                    run_id, owner_id, generation, expires_at, renewed_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    generation = excluded.generation,
                    expires_at = excluded.expires_at,
                    renewed_at = excluded.renewed_at
                """,
                (
                    run_id,
                    owner_id,
                    generation,
                    expires_at.isoformat(),
                    instant.isoformat(),
                ),
            )
        return RunLease(
            run_id=run_id,
            owner_id=owner_id,
            generation=generation,
            expires_at=expires_at.isoformat(),
        )

    @staticmethod
    def _incompatible_reason(
        connection: sqlite3.Connection,
        snapshot_id: str,
        *,
        supported_engine_versions: Optional[AbstractSet[str]],
        supported_admission_schema_versions: Optional[AbstractSet[int]],
        supported_transition_policy_versions: Optional[AbstractSet[str]],
    ) -> str:
        if (
            supported_engine_versions is None
            and supported_admission_schema_versions is None
            and supported_transition_policy_versions is None
        ):
            return ""
        row = connection.execute(
            "SELECT manifest_json FROM execution_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by foreign key
            return f"missing ExecutionSnapshot {snapshot_id}"
        value = json.loads(row["manifest_json"])
        versions = value.get("versions", {}) if isinstance(value, dict) else {}
        checks = (
            ("engine", versions.get("engine"), supported_engine_versions),
            (
                "Admission schema",
                versions.get("admission_schema"),
                supported_admission_schema_versions,
            ),
            (
                "transition policy",
                versions.get("transition_policy"),
                supported_transition_policy_versions,
            ),
        )
        unsupported = [
            f"{name} version {version!r}"
            for name, version, supported in checks
            if supported is not None and version not in supported
        ]
        if not unsupported:
            return ""
        return "unsupported " + ", ".join(unsupported)

    def renew(
        self,
        lease: RunLease,
        *,
        lease_seconds: float,
        now: Optional[datetime] = None,
    ) -> RunLease:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        expires_at = instant + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._prove_lease(connection, lease, instant)
            connection.execute(
                "UPDATE run_leases SET expires_at = ?, renewed_at = ? "
                "WHERE run_id = ? AND owner_id = ? AND generation = ?",
                (
                    expires_at.isoformat(),
                    instant.isoformat(),
                    lease.run_id,
                    lease.owner_id,
                    lease.generation,
                ),
            )
        return RunLease(
            run_id=current["run_id"],
            owner_id=current["owner_id"],
            generation=int(current["generation"]),
            expires_at=expires_at.isoformat(),
        )

    def prove(
        self,
        lease: RunLease,
        *,
        now: Optional[datetime] = None,
    ) -> RunLease:
        instant = _instant(now)
        with self._connect() as connection:
            current = self._prove_lease(connection, lease, instant)
        return _run_lease(current)

    def transition(
        self,
        run_id: str,
        *,
        owner_id: str,
        generation: int,
        status: str,
        error: str = "",
        now: Optional[datetime] = None,
    ) -> RunRecord:
        if not status:
            raise ValueError("status must be non-empty")
        instant = _instant(now)
        lease = RunLease(run_id, owner_id, generation, instant.isoformat())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prove_lease(connection, lease, instant)
            previous = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if previous is None:  # pragma: no cover - protected by foreign keys
                raise KeyError(f"unknown Run: {run_id}")
            connection.execute(
                "UPDATE runs SET status = ?, error = ? WHERE run_id = ?",
                (status, error, run_id),
            )
            connection.execute(
                """
                INSERT INTO run_transitions (
                    run_id, generation, from_status, to_status, error, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    generation,
                    previous["status"],
                    status,
                    error,
                    instant.isoformat(),
                ),
            )
            if status not in {"queued", "running"}:
                connection.execute("DELETE FROM run_queue WHERE run_id = ?", (run_id,))
                connection.execute("DELETE FROM run_leases WHERE run_id = ?", (run_id,))
        return self.run(run_id)

    def requeue(self, run_id: str) -> RunRecord:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown Run: {run_id}")
            if not str(run["status"]).startswith("paused_"):
                raise ValueError(f"Run {run_id!r} is not paused")
            connection.execute(
                "UPDATE runs SET status = 'queued', error = '' WHERE run_id = ?",
                (run_id,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO run_queue (run_id, enqueued_at) VALUES (?, ?)",
                (run_id, now),
            )
            connection.execute("DELETE FROM run_leases WHERE run_id = ?", (run_id,))
        return self.run(run_id)

    @staticmethod
    def _prove_lease(
        connection: sqlite3.Connection,
        lease: RunLease,
        now: datetime,
    ) -> sqlite3.Row:
        current = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (lease.run_id,),
        ).fetchone()
        if current is None:
            raise LeaseConflictError(f"Run {lease.run_id!r} has no active Lease")
        if (
            current["owner_id"] != lease.owner_id
            or int(current["generation"]) != lease.generation
        ):
            raise LeaseConflictError(
                f"stale Lease generation for Run {lease.run_id!r}"
            )
        if _parse_instant(current["expires_at"]) <= now:
            raise LeaseConflictError(f"Lease for Run {lease.run_id!r} has expired")
        return current

    def _assert_worker_lease(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        owner_id: str,
        generation: int,
    ) -> None:
        self._prove_lease(
            connection,
            RunLease(run_id, owner_id, generation, _now()),
            _instant(None),
        )

    def _inject_worker_fault(
        self,
        boundary: str,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> None:
        if self._worker_fault_injector is not None:
            self._worker_fault_injector(boundary, connection, run_id)

    def _inject(self, boundary: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(boundary)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection


class Admission:
    def __init__(
        self,
        ledger: RunLedger,
        *,
        engine_version: str,
        transition_policy_version: str,
        contract_reader: Callable[[Path], bytes] = Path.read_bytes,
    ) -> None:
        self._ledger = ledger
        self._engine_version = engine_version
        self._transition_policy_version = transition_policy_version
        self._contract_reader = contract_reader

    def admit(self, request: AdmissionRequest) -> AdmittedRun:
        contract_path = Path(request.contract_path).expanduser().resolve()
        try:
            source = self._contract_reader(contract_path)
            contract = _load_contract(
                contract_path,
                workflow_path=request.workflow_path,
                raw=source,
            )
        except (ContractError, OSError) as error:
            raise AdmissionError(str(error)) from error
        base_commit = _clean_pinned_commit(
            contract.repository,
            contract.base_ref,
        )
        manifest = _manifest(
            contract,
            base_commit=base_commit,
            engine_version=self._engine_version,
            transition_policy_version=self._transition_policy_version,
        )
        _reject_secret_material(source, manifest)
        snapshot = ExecutionSnapshot(
            snapshot_id=_snapshot_id(source, manifest),
            source=source,
            manifest=manifest,
            created_at=_now(),
        )
        return self._ledger.admit(
            snapshot,
            goal_id=contract.goal_id,
            idempotency_key=request.idempotency_key,
        )


def _manifest(
    contract: Any,
    *,
    base_commit: str,
    engine_version: str,
    transition_policy_version: str,
) -> ExecutionManifest:
    return ExecutionManifest({
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "versions": {
            "admission_schema": ADMISSION_SCHEMA_VERSION,
            "engine": engine_version,
            "transition_policy": transition_policy_version,
        },
        "approval_status": contract.approval_status,
        "goal": {
            "id": contract.goal_id,
            "title": contract.goal_title,
            "requirement": contract.requirement,
            "acceptance": _json_value(contract.acceptance),
        },
        "agent": {
            "provider": contract.agent_provider,
            "model": contract.agent_model,
        },
        "repository": {
            "path": str(contract.repository.resolve()),
            "base_ref": contract.base_ref,
            "base_commit": base_commit,
        },
        "todos": _json_value(contract.todos),
        "resources": _json_value(contract.resources),
        "role_guidance": _json_value(contract.role_skill_texts),
        "image_profile": _json_value(contract.image_profile),
        "publish_policy": _resolved_publish_policy(contract),
        "policy": _json_value(contract.policy),
        "required_secrets": contract.required_secrets,
    })


def _resolved_publish_policy(contract: Any) -> Optional[Mapping[str, object]]:
    if contract.candidate_publish is None:
        return None
    remote_url = _git(
        contract.repository,
        "remote",
        "get-url",
        contract.candidate_publish.remote,
    ).stdout.strip()
    return {
        **_json_value(contract.candidate_publish),
        "remote_url": remote_url,
    }


def _clean_pinned_commit(repository: Path, base_ref: str) -> str:
    status = _git(repository, "status", "--porcelain", "--untracked-files=all")
    if status.stdout:
        raise AdmissionError("Admission requires a clean repository")
    commit = _git(repository, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    return commit.stdout.strip()


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AdmissionError(f"Git Admission check failed: {detail}")
    return completed


def _snapshot_id(source: bytes, manifest: Mapping[str, object]) -> str:
    identity = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "manifest": manifest,
    }
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def _reject_secret_material(
    source: bytes,
    manifest: Mapping[str, object],
) -> None:
    try:
        source_value = yaml.safe_load(source)
    except yaml.YAMLError as error:  # pragma: no cover - Contract parsed first
        raise AdmissionError(f"invalid Contract YAML: {error}") from error
    _reject_literal_secret_values(source_value, path="Contract")
    _reject_literal_secret_values(manifest, path="ExecutionManifest")
    manifest_bytes = _canonical_json(manifest).encode("utf-8")
    markers = (
        "API_KEY",
        "CREDENTIAL",
        "PASSWORD",
        "PASSWD",
        "PRIVATE_KEY",
        "SECRET",
        "TOKEN",
    )
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        normalized = name.upper()
        if not any(marker in normalized for marker in markers):
            continue
        encoded = value.encode("utf-8")
        if encoded in source or encoded in manifest_bytes:
            raise AdmissionError(
                f"Admission input contains secret material from {name}"
            )
    _validate_contract_source_schema(source_value)


def _reject_literal_secret_values(value: object, *, path: str) -> None:
    secret_field = re.compile(
        r"(?:^|_)(?:api_key|credential|password|passwd|private_key|secret|token)$",
        re.IGNORECASE,
    )
    secret_text = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(
            r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S{8,}",
            re.IGNORECASE,
        ),
        re.compile(
            r"--(?:api-key|token|secret|password)(?:=|\s+)\S+",
            re.IGNORECASE,
        ),
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if secret_field.search(str(key)):
                raise AdmissionError(
                    f"Admission input contains a literal secret field at {item_path}; "
                    "use required_secrets references"
                )
            _reject_literal_secret_values(item, path=item_path)
        return
    if isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _reject_literal_secret_values(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in secret_text):
        raise AdmissionError(
            f"Admission input contains literal secret material at {path}; "
            "use required_secrets references"
        )


def _validate_contract_source_schema(value: object) -> None:
    contract = _closed_mapping(
        value,
        "Contract",
        {
            "schema_version",
            "goal",
            "approval",
            "agent",
            "project",
            "todo",
            "test",
            "todos",
            "candidate",
            "resources",
            "required_secrets",
        },
    )
    goal = _closed_mapping(
        contract.get("goal"),
        "Contract.goal",
        {"id", "title", "requirement", "acceptance"},
    )
    acceptance = goal.get("acceptance")
    if isinstance(acceptance, list):
        for index, item in enumerate(acceptance):
            _closed_mapping(
                item,
                f"Contract.goal.acceptance[{index}]",
                {"id", "statement"},
            )
    _closed_mapping(
        contract.get("approval"),
        "Contract.approval",
        {"status", "approved_by", "approved_at"},
    )
    _closed_mapping(
        contract.get("agent", {}),
        "Contract.agent",
        {"provider", "model"},
    )
    _closed_mapping(
        contract.get("project"),
        "Contract.project",
        {"repo", "base_ref", "workflow"},
    )
    _closed_mapping(
        contract.get("candidate", {}),
        "Contract.candidate",
        {"image_profile"},
    )
    _closed_mapping(
        contract.get("resources", {}),
        "Contract.resources",
        {
            "agent_attempts",
            "wall_clock_seconds",
            "harness_seconds",
            "provider_tokens",
        },
    )
    if "todos" in contract and ("todo" in contract or "test" in contract):
        raise AdmissionError(
            "Contract todos and legacy todo/test forms are mutually exclusive"
        )
    if "todos" in contract:
        todos = contract.get("todos")
        if isinstance(todos, list):
            for index, item in enumerate(todos):
                todo = _closed_mapping(
                    item,
                    f"Contract.todos[{index}]",
                    {"id", "title", "depends_on", "test_ids", "test"},
                )
                _validate_contract_test_schema(
                    todo.get("test"),
                    f"Contract.todos[{index}].test",
                )
    else:
        _closed_mapping(
            contract.get("todo"),
            "Contract.todo",
            {"id", "title"},
        )
        _validate_contract_test_schema(contract.get("test"), "Contract.test")


def _validate_contract_test_schema(value: object, path: str) -> None:
    _closed_mapping(
        value,
        path,
        {"command", "allowed_paths", "timeout_seconds", "harness"},
    )


def _closed_mapping(
    value: object,
    path: str,
    allowed: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AdmissionError(f"{path} must be a mapping")
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise AdmissionError(
            f"unsupported Contract field at {path}: {', '.join(unknown)}"
        )
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _validate_manifest_details(values: Mapping[str, object]) -> None:
    goal = _manifest_mapping(values, "goal")
    for name in ("id", "title", "requirement"):
        _manifest_text(goal, name, prefix="goal")
    acceptance = goal.get("acceptance")
    if not isinstance(acceptance, (tuple, list)) or not acceptance:
        raise AdmissionError("ExecutionManifest goal.acceptance must be non-empty")
    for index, item in enumerate(acceptance):
        acceptance_item = _manifest_item_mapping(
            item,
            f"goal.acceptance[{index}]",
        )
        _manifest_text(
            acceptance_item,
            "test_id",
            prefix=f"goal.acceptance[{index}]",
        )
        _manifest_text(
            acceptance_item,
            "statement",
            prefix=f"goal.acceptance[{index}]",
        )

    agent = _manifest_mapping(values, "agent")
    _manifest_text(agent, "provider", prefix="agent")
    model = agent.get("model")
    if model is not None and (not isinstance(model, str) or not model):
        raise AdmissionError("ExecutionManifest agent.model must be text or null")

    repository = _manifest_mapping(values, "repository")
    for name in ("path", "base_ref", "base_commit"):
        _manifest_text(repository, name, prefix="repository")
    base_commit = repository["base_commit"]
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", str(base_commit)):
        raise AdmissionError(
            "ExecutionManifest repository.base_commit must be a Git object id"
        )

    todos = values["todos"]
    assert isinstance(todos, (tuple, list))
    for index, item in enumerate(todos):
        todo = _manifest_item_mapping(item, f"todos[{index}]")
        for name in ("todo_id", "title", "harness_name"):
            _manifest_text(todo, name, prefix=f"todos[{index}]", allow_empty=name == "harness_name")
        for name in (
            "depends_on",
            "test_ids",
            "test_command",
            "allowed_test_paths",
        ):
            _manifest_string_sequence(todo, name, prefix=f"todos[{index}]")
        timeout = todo.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise AdmissionError(
                f"ExecutionManifest todos[{index}].timeout_seconds must be positive"
            )
        harness = todo.get("harness")
        if harness is not None and not isinstance(harness, Mapping):
            raise AdmissionError(
                f"ExecutionManifest todos[{index}].harness must be a mapping or null"
            )
        if isinstance(harness, Mapping):
            _validate_harness_manifest(harness, prefix=f"todos[{index}].harness")

    resources = _manifest_mapping(values, "resources")
    _reject_unknown_manifest_fields(
        resources,
        "resources",
        {
            "agent_attempts",
            "wall_clock_seconds",
            "harness_seconds",
            "provider_tokens",
        },
    )
    for name, item in resources.items():
        if item is not None and (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or item <= 0
        ):
            raise AdmissionError(
                f"ExecutionManifest resources.{name} must be positive or null"
            )

    role_guidance = _manifest_mapping(values, "role_guidance")
    for role, entries in role_guidance.items():
        if not isinstance(role, str) or not isinstance(entries, (tuple, list)):
            raise AdmissionError(
                "ExecutionManifest role_guidance must map roles to guidance entries"
            )
        for entry in entries:
            if (
                not isinstance(entry, (tuple, list))
                or len(entry) != 2
                or not all(isinstance(item, str) for item in entry)
            ):
                raise AdmissionError(
                    f"ExecutionManifest role_guidance.{role} entries must be path/text pairs"
                )

    image_profile = values.get("image_profile")
    if isinstance(image_profile, Mapping):
        _reject_unknown_manifest_fields(
            image_profile,
            "image_profile",
            {
                "name",
                "environment",
                "start_command",
                "status_command",
                "result_command",
            },
        )
        for name in ("name", "environment"):
            _manifest_text(image_profile, name, prefix="image_profile")
        for name in ("start_command", "status_command", "result_command"):
            _manifest_string_sequence(image_profile, name, prefix="image_profile")

    publish_policy = values.get("publish_policy")
    if isinstance(publish_policy, Mapping):
        _reject_unknown_manifest_fields(
            publish_policy,
            "publish_policy",
            {"remote", "branch_prefix", "remote_url"},
        )
        for name in ("remote", "branch_prefix", "remote_url"):
            _manifest_text(publish_policy, name, prefix="publish_policy")

    policy = _manifest_mapping(values, "policy")
    _reject_unknown_manifest_fields(
        policy,
        "policy",
        {"path", "source", "candidate_commands", "approved_commands"},
    )
    for name in ("path", "source"):
        _manifest_text(policy, name, prefix="policy")
    _validate_policy_commands(policy)

    required_secrets = values["required_secrets"]
    assert isinstance(required_secrets, (tuple, list))
    if not all(_valid_secret_reference(item) for item in required_secrets):
        raise AdmissionError(
            "ExecutionManifest required_secrets contains an unsupported reference"
        )


def _validate_harness_manifest(
    harness: Mapping[str, object],
    *,
    prefix: str,
) -> None:
    _reject_unknown_manifest_fields(
        harness,
        prefix,
        {
            "name",
            "kind",
            "environment",
            "start_command",
            "ready_url",
            "ready_timeout_seconds",
            "browser_gate",
            "browser_diagnostic",
            "kubernetes_context",
            "namespace_prefix",
            "ttl_seconds",
            "provision_command",
            "collect_command",
            "cleanup_command",
        },
    )
    for name in (
        "name",
        "kind",
        "environment",
        "ready_url",
        "browser_gate",
        "kubernetes_context",
        "namespace_prefix",
    ):
        _manifest_text(harness, name, prefix=prefix, allow_empty=name not in {"name", "kind", "environment"})
    for name in (
        "start_command",
        "provision_command",
        "collect_command",
        "cleanup_command",
    ):
        _manifest_string_sequence(harness, name, prefix=prefix)
    for name in ("ready_timeout_seconds", "ttl_seconds"):
        item = harness.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise AdmissionError(
                f"ExecutionManifest {prefix}.{name} must be non-negative"
            )
    browser = harness.get("browser_diagnostic")
    if browser is not None:
        browser_mapping = _manifest_item_mapping(
            browser,
            f"{prefix}.browser_diagnostic",
        )
        _reject_unknown_manifest_fields(
            browser_mapping,
            f"{prefix}.browser_diagnostic",
            {"adapter", "command", "timeout_seconds"},
        )
        _manifest_text(
            browser_mapping,
            "adapter",
            prefix=f"{prefix}.browser_diagnostic",
        )
        _manifest_string_sequence(
            browser_mapping,
            "command",
            prefix=f"{prefix}.browser_diagnostic",
        )
        timeout = browser_mapping.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise AdmissionError(
                f"ExecutionManifest {prefix}.browser_diagnostic.timeout_seconds must be positive"
            )


def _validate_policy_commands(policy: Mapping[str, object]) -> None:
    candidates = policy.get("candidate_commands")
    if not isinstance(candidates, (tuple, list)):
        raise AdmissionError(
            "ExecutionManifest policy.candidate_commands must be a sequence"
        )
    for index, candidate in enumerate(candidates):
        item = _manifest_item_mapping(
            candidate,
            f"policy.candidate_commands[{index}]",
        )
        _reject_unknown_manifest_fields(
            item,
            f"policy.candidate_commands[{index}]",
            {"name", "argv", "reason"},
        )
        _manifest_text(item, "name", prefix=f"policy.candidate_commands[{index}]")
        _manifest_text(item, "reason", prefix=f"policy.candidate_commands[{index}]", allow_empty=True)
        _manifest_string_sequence(
            item,
            "argv",
            prefix=f"policy.candidate_commands[{index}]",
        )
    approved = policy.get("approved_commands")
    if not isinstance(approved, (tuple, list)):
        raise AdmissionError(
            "ExecutionManifest policy.approved_commands must be a sequence"
        )
    for index, command in enumerate(approved):
        if not isinstance(command, (tuple, list)) or not all(
            isinstance(item, str) for item in command
        ):
            raise AdmissionError(
                f"ExecutionManifest policy.approved_commands[{index}] must contain text"
            )


def _reject_unknown_manifest_fields(
    values: Mapping[str, object],
    path: str,
    allowed: set[str],
) -> None:
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise AdmissionError(
            f"ExecutionManifest {path} has unknown fields: {', '.join(unknown)}"
        )


def _valid_secret_reference(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"(?:env:[A-Za-z_][A-Za-z0-9_]*|"
        r"keychain:[A-Za-z0-9_][A-Za-z0-9._/@:-]*)",
        value,
    ) is not None


def _manifest_mapping(
    values: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    value = values.get(name)
    if not isinstance(value, Mapping):
        raise AdmissionError(f"ExecutionManifest {name} must be a mapping")
    return value


def _manifest_item_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AdmissionError(f"ExecutionManifest {path} must be a mapping")
    return value


def _manifest_text(
    values: Mapping[str, object],
    name: str,
    *,
    prefix: str,
    allow_empty: bool = False,
) -> str:
    value = values.get(name)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise AdmissionError(
            f"ExecutionManifest {prefix}.{name} must be non-empty text"
        )
    return value


def _manifest_string_sequence(
    values: Mapping[str, object],
    name: str,
    *,
    prefix: str,
) -> None:
    value = values.get(name)
    if not isinstance(value, (tuple, list)) or not all(
        isinstance(item, str) for item in value
    ):
        raise AdmissionError(
            f"ExecutionManifest {prefix}.{name} must contain text values"
        )


def _admitted_run(row: sqlite3.Row) -> AdmittedRun:
    return AdmittedRun(
        run_id=row["run_id"],
        snapshot_id=row["snapshot_id"],
        goal_id=row["goal_id"],
        status=row["status"],
    )


def _execution_snapshot(row: sqlite3.Row) -> ExecutionSnapshot:
    manifest = json.loads(row["manifest_json"])
    if not isinstance(manifest, dict):
        raise ValueError(
            f"invalid ExecutionSnapshot manifest: {row['snapshot_id']}"
        )
    return ExecutionSnapshot(
        snapshot_id=row["snapshot_id"],
        source=bytes(row["source"]),
        manifest=ExecutionManifest(manifest),
        created_at=row["created_at"],
    )


def _run_record(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        snapshot_id=row["snapshot_id"],
        goal_id=row["goal_id"],
        status=row["status"],
        created_at=row["created_at"],
        error=row["error"] if "error" in row.keys() else "",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _instant(value: Optional[datetime]) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("Lease time must be timezone-aware")
    return instant.astimezone(timezone.utc)


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _run_lease(row: sqlite3.Row) -> RunLease:
    return RunLease(
        run_id=row["run_id"],
        owner_id=row["owner_id"],
        generation=int(row["generation"]),
        expires_at=row["expires_at"],
    )
