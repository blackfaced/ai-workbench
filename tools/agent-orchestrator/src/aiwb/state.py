from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple
from urllib.parse import quote


_CURRENT_TABLES = frozenset(
    {"execution_snapshots", "runs", "run_queue", "idempotency_keys"}
)
_RESET_MARKER = ".legacy-state-reset.json"
_RESET_MARKER_TEMPORARY = ".legacy-state-reset.json.tmp"


class StateResetError(RuntimeError):
    pass


class StateFormat(str, Enum):
    MISSING = "missing"
    CURRENT = "current"
    INCOMPATIBLE_LEGACY = "incompatible_legacy"


@dataclass(frozen=True)
class StateAssessment:
    format: StateFormat
    state_dir: str
    legacy_databases: Tuple[str, ...] = ()
    managed_paths: Tuple[str, ...] = ()
    reset_in_progress: bool = False
    resettable: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "format": self.format.value,
            "state_dir": self.state_dir,
            "legacy_databases": list(self.legacy_databases),
            "managed_paths": list(self.managed_paths),
            "reset_in_progress": self.reset_in_progress,
            "resettable": self.resettable,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StateResetResult:
    changed: bool
    assessment: StateAssessment
    removed: Tuple[str, ...] = ()


class DurableStateSetup:
    """Inspect and explicitly reset incompatible local durable state."""

    def __init__(
        self,
        *,
        _fault_injector: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._fault_injector = _fault_injector

    def inspect(self, state_dir: Path) -> StateAssessment:
        root = Path(state_dir).expanduser().resolve()
        marker = root / _RESET_MARKER
        if marker.exists():
            return _assessment_from_marker(root, marker)
        state_database = root / "state.db"
        daemon_database = root / "daemon.db"
        if not state_database.exists() and not daemon_database.exists():
            return StateAssessment(format=StateFormat.MISSING, state_dir=str(root))

        try:
            state_tables = (
                _sqlite_tables(state_database) if state_database.exists() else set()
            )
            daemon_tables = (
                _sqlite_tables(daemon_database) if daemon_database.exists() else set()
            )
            run_columns = (
                _table_columns(state_database, "runs")
                if state_database.exists() and "runs" in state_tables
                else set()
            )
        except sqlite3.DatabaseError as error:
            return StateAssessment(
                format=StateFormat.INCOMPATIBLE_LEGACY,
                state_dir=str(root),
                resettable=False,
                detail=f"state database cannot be safely inspected: {error}",
            )
        current_run_columns = {"snapshot_id", "goal_id", "status", "created_at"}
        if (
            _CURRENT_TABLES.issubset(state_tables)
            and current_run_columns.issubset(run_columns)
            and "contract_hash" not in run_columns
            and "todos" not in state_tables
            and not daemon_database.exists()
        ):
            return StateAssessment(format=StateFormat.CURRENT, state_dir=str(root))

        legacy = []
        if daemon_database.exists() and "daemon_jobs" in daemon_tables:
            legacy.append(str(daemon_database))
        if state_database.exists() and (
            "todos" in state_tables or "contract_hash" in run_columns
        ):
            legacy.append(str(state_database))
        resettable = bool(legacy) and len(legacy) == sum(
            int(path.exists()) for path in (daemon_database, state_database)
        )
        try:
            managed_paths = _managed_legacy_paths(root, state_database)
        except sqlite3.DatabaseError as error:
            return StateAssessment(
                format=StateFormat.INCOMPATIBLE_LEGACY,
                state_dir=str(root),
                legacy_databases=tuple(legacy),
                resettable=False,
                detail=f"legacy Run state cannot be safely inspected: {error}",
            )
        return StateAssessment(
            format=StateFormat.INCOMPATIBLE_LEGACY,
            state_dir=str(root),
            legacy_databases=tuple(legacy),
            managed_paths=managed_paths,
            resettable=resettable,
            detail=(
                "legacy Run state has no supported migration"
                if resettable
                else "state database format is not recognized and cannot be safely reset"
            ),
        )

    def reset(self, state_dir: Path, *, confirmed: bool) -> StateResetResult:
        assessment = self.inspect(state_dir)
        if assessment.format in {StateFormat.MISSING, StateFormat.CURRENT}:
            return StateResetResult(changed=False, assessment=assessment)
        if not confirmed:
            raise StateResetError("legacy state reset requires explicit confirmation")
        if not assessment.resettable:
            raise StateResetError(assessment.detail)

        root = Path(assessment.state_dir)
        marker = root / _RESET_MARKER
        if not assessment.reset_in_progress:
            root.mkdir(parents=True, exist_ok=True)
            _write_reset_marker(
                marker,
                databases=assessment.legacy_databases,
                managed_paths=assessment.managed_paths,
            )
        self._inject("after_reset_recorded")
        _reject_live_daemon(root / "run" / "daemon.sock")

        manifest = _load_reset_marker(marker)
        removed = []
        for value in manifest["managed_paths"]:
            path = _validated_managed_path(root, str(value))
            if _remove_path(path):
                removed.append(str(path))
            self._inject("after_managed_path")
        for value in manifest["legacy_databases"]:
            database = _validated_database_path(root, str(value))
            for path in _database_files(database):
                if _remove_path(path):
                    removed.append(str(path))
            self._inject("after_legacy_database")
        self._inject("before_reset_completed")
        marker.unlink(missing_ok=True)
        (root / _RESET_MARKER_TEMPORARY).unlink(missing_ok=True)
        _remove_empty_managed_parents(root)
        return StateResetResult(
            changed=bool(removed),
            assessment=self.inspect(root),
            removed=tuple(removed),
        )

    def _inject(self, boundary: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(boundary)


def _sqlite_tables(database: Path) -> set[str]:
    with _readonly_connection(database) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(database: Path, table: str) -> set[str]:
    if table not in _sqlite_tables(database):
        return set()
    with _readonly_connection(database) as connection:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {str(row[1]) for row in rows}


def _readonly_connection(database: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(database))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _managed_legacy_paths(root: Path, state_database: Path) -> Tuple[str, ...]:
    run_ids = _legacy_run_ids(state_database) if state_database.exists() else ()
    paths = []
    for run_id in run_ids:
        for path in (
            root / "worktrees" / run_id,
            root / "image-builds" / run_id,
        ):
            if path.exists() or path.is_symlink():
                paths.append(path)
    lease_dir = root / "kubernetes-leases"
    if lease_dir.is_dir():
        for lease in sorted(lease_dir.glob("*.json")):
            try:
                value = json.loads(lease.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, Mapping) and value.get("run_id") in run_ids:
                paths.append(lease)
    socket_path = root / "run" / "daemon.sock"
    if socket_path.exists() or socket_path.is_symlink():
        paths.append(socket_path)
    return tuple(str(path) for path in paths)


def _legacy_run_ids(database: Path) -> Tuple[str, ...]:
    if "runs" not in _sqlite_tables(database):
        return ()
    with _readonly_connection(database) as connection:
        rows = connection.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    result = []
    for row in rows:
        run_id = str(row[0])
        if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
            raise StateResetError("legacy Run contains an unsafe run_id")
        result.append(run_id)
    return tuple(result)


def _write_reset_marker(
    marker: Path,
    *,
    databases: Tuple[str, ...],
    managed_paths: Tuple[str, ...],
) -> None:
    temporary = marker.with_name(_RESET_MARKER_TEMPORARY)
    payload = {
        "schema_version": 1,
        "status": "in_progress",
        "legacy_databases": list(databases),
        "managed_paths": list(managed_paths),
    }
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(marker)


def _assessment_from_marker(root: Path, marker: Path) -> StateAssessment:
    manifest = _load_reset_marker(marker)
    databases = tuple(str(item) for item in manifest["legacy_databases"])
    managed_paths = tuple(str(item) for item in manifest["managed_paths"])
    for value in databases:
        _validated_database_path(root, value)
    for value in managed_paths:
        _validated_managed_path(root, value)
    return StateAssessment(
        format=StateFormat.INCOMPATIBLE_LEGACY,
        state_dir=str(root),
        legacy_databases=databases,
        managed_paths=managed_paths,
        reset_in_progress=True,
        resettable=True,
        detail="a legacy state reset was interrupted and can be safely retried",
    )


def _load_reset_marker(marker: Path) -> Mapping[str, object]:
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateResetError(f"cannot read interrupted reset record: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise StateResetError("interrupted reset record has an unsupported format")
    databases = value.get("legacy_databases")
    managed_paths = value.get("managed_paths")
    if not isinstance(databases, list) or not all(
        isinstance(item, str) for item in databases
    ):
        raise StateResetError("interrupted reset record has invalid databases")
    if not isinstance(managed_paths, list) or not all(
        isinstance(item, str) for item in managed_paths
    ):
        raise StateResetError("interrupted reset record has invalid managed paths")
    return value


def _validated_database_path(root: Path, value: str) -> Path:
    path = Path(os.path.abspath(str(Path(value).expanduser())))
    if path.parent != root or path.name not in {"daemon.db", "state.db"}:
        raise StateResetError("reset record contains an unsafe database path")
    return path


def _validated_managed_path(root: Path, value: str) -> Path:
    path = Path(os.path.abspath(str(Path(value).expanduser())))
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise StateResetError(
            "reset record contains an unsafe managed path"
        ) from error
    valid = (
        len(relative.parts) == 2
        and relative.parts[0] in {"worktrees", "image-builds", "kubernetes-leases"}
        and relative.parts[1] != "harness-setup"
    ) or relative.parts == ("run", "daemon.sock")
    if not valid or (root / relative.parts[0]).is_symlink():
        raise StateResetError("reset record contains an unsafe managed path")
    return path


def _database_files(database: Path) -> Tuple[Path, ...]:
    return (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
        database.with_name(database.name + "-journal"),
    )


def _remove_path(path: Path) -> bool:
    if path.is_symlink() or path.is_file() or path.is_socket():
        path.unlink(missing_ok=True)
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _remove_empty_managed_parents(root: Path) -> None:
    for name in ("worktrees", "image-builds", "kubernetes-leases", "run"):
        path = root / name
        try:
            path.rmdir()
        except (FileNotFoundError, OSError):
            pass


def _reject_live_daemon(socket_path: Path) -> None:
    if not socket_path.is_socket():
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(socket_path))
    except OSError:
        return
    finally:
        probe.close()
    raise StateResetError("cannot reset state while the Daemon is running")
