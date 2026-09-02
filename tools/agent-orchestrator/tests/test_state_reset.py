from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

import pytest

from aiwb import SQLiteRunLedger  # noqa: E402
from aiwb.state import DurableStateSetup, StateResetError  # noqa: E402


def test_setup_distinguishes_missing_current_and_legacy_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        missing = root / "missing"
        current = root / "current"
        legacy = root / "legacy"
        setup = DurableStateSetup()

        assert setup.inspect(missing).format == "missing"

        current.mkdir()
        SQLiteRunLedger(current / "run-ledger.db")
        before = _tree_snapshot(current)
        current_assessment = setup.inspect(current)
        assert current_assessment.format == "current"
        assert current_assessment.current_database == str(
            (current / "run-ledger.db").resolve()
        )
        assert _tree_snapshot(current) == before

        legacy.mkdir()
        _create_legacy_databases(legacy)
        assessment = setup.inspect(legacy)
        assert assessment.format == "incompatible_legacy"
        assert assessment.legacy_databases == (
            str((legacy / "daemon.db").resolve()),
            str((legacy / "state.db").resolve()),
        )


def test_current_marker_requires_complete_run_ledger_schema() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        ledger = state_dir / "run-ledger.db"
        SQLiteRunLedger(ledger)
        connection = sqlite3.connect(ledger)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DROP TABLE runs")
            connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()

        assessment = DurableStateSetup().inspect(state_dir)

        assert assessment.format == "incompatible_current"
        assert assessment.resettable is False


def test_explicit_reset_accepts_a_previous_run_ledger_schema() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        database = state_dir / "run-ledger.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE run_ledger_schema (singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL)"
            )
            connection.execute("INSERT INTO run_ledger_schema VALUES (1, 1)")

        result = DurableStateSetup().reset(state_dir, confirmed=True)

        assert result.changed is True
        assert result.assessment.format == "missing"
        assert not database.exists()


def test_confirmed_reset_removes_only_legacy_run_owned_state_and_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))
        owned = (
            state_dir / "worktrees" / "run-1",
            state_dir / "image-builds" / "run-1",
        )
        for path in owned:
            path.mkdir(parents=True)
            (path / "owned.txt").write_text("owned", encoding="utf-8")
        owned_lease = state_dir / "kubernetes-leases" / "owned.json"
        owned_lease.parent.mkdir()
        owned_lease.write_text('{"run_id": "run-1"}', encoding="utf-8")
        socket_path = state_dir / "run" / "daemon.sock"
        socket_path.parent.mkdir()
        socket_path.write_text("stale", encoding="utf-8")
        preserved = (
            state_dir / "worktrees" / "harness-setup" / "candidate",
            state_dir / "worktrees" / "unmanaged",
            state_dir / "image-builds" / "unmanaged",
            state_dir / "evidence" / "objects" / "aa",
            state_dir / "logs",
        )
        for path in preserved:
            path.mkdir(parents=True)
            (path / "keep.txt").write_text("keep", encoding="utf-8")
        unowned_lease = state_dir / "kubernetes-leases" / "unowned.json"
        unowned_lease.write_text('{"run_id": "another-run"}', encoding="utf-8")
        setup = DurableStateSetup()

        before = _tree_snapshot(state_dir)
        with pytest.raises(StateResetError, match="explicit confirmation"):
            setup.reset(state_dir, confirmed=False)
        assert _tree_snapshot(state_dir) == before

        first = setup.reset(state_dir, confirmed=True)
        second = setup.reset(state_dir, confirmed=True)

        assert first.changed is True
        assert first.assessment.format == "missing"
        assert second.changed is False
        assert second.assessment.format == "missing"
        assert not (state_dir / "daemon.db").exists()
        assert not (state_dir / "state.db").exists()
        assert all(not path.exists() for path in owned)
        assert not owned_lease.exists()
        assert not socket_path.exists()
        assert all((path / "keep.txt").read_text(encoding="utf-8") == "keep" for path in preserved)
        assert unowned_lease.exists()


def test_interrupted_reset_is_diagnosable_and_safely_retryable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))
        workspace = state_dir / "worktrees" / "run-1"
        workspace.mkdir(parents=True)
        (workspace / "owned.txt").write_text("owned", encoding="utf-8")
        preserved = state_dir / "evidence" / "keep.txt"
        preserved.parent.mkdir()
        preserved.write_text("keep", encoding="utf-8")

        def interrupt(boundary: str) -> None:
            if boundary == "after_legacy_database":
                raise RuntimeError("simulated interruption")

        with pytest.raises(RuntimeError, match="simulated interruption"):
            DurableStateSetup(_fault_injector=interrupt).reset(
                state_dir,
                confirmed=True,
            )

        interrupted = DurableStateSetup().inspect(state_dir)
        assert interrupted.format == "incompatible_legacy"
        assert interrupted.reset_in_progress is True
        assert "interrupted" in interrupted.detail

        result = DurableStateSetup().reset(state_dir, confirmed=True)

        assert result.assessment.format == "missing"
        assert not workspace.exists()
        assert preserved.read_text(encoding="utf-8") == "keep"
        assert not (state_dir / ".legacy-state-reset.json").exists()


def test_reset_unlinks_a_managed_workspace_symlink_without_following_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state_dir = root / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))
        outside = root / "outside"
        outside.mkdir()
        preserved = outside / "keep.txt"
        preserved.write_text("keep", encoding="utf-8")
        workspace = state_dir / "worktrees" / "run-1"
        workspace.parent.mkdir()
        workspace.symlink_to(outside, target_is_directory=True)

        result = DurableStateSetup().reset(state_dir, confirmed=True)

        assert result.assessment.format == "missing"
        assert not workspace.exists()
        assert preserved.read_text(encoding="utf-8") == "keep"


def test_interactive_setup_explains_reset_and_declining_preserves_everything() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        state_dir = root / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))
        workspace = state_dir / "worktrees" / "run-1"
        workspace.mkdir(parents=True)
        (workspace / "owned.txt").write_text("owned", encoding="utf-8")
        before = _tree_snapshot(state_dir)

        completed = _run_setup_cli(repository, state_dir, input_text="n\n")

        assert completed.returncode == 1
        assert "cannot be migrated" in completed.stderr
        assert str((state_dir / "daemon.db").resolve()) in completed.stderr
        assert str((state_dir / "state.db").resolve()) in completed.stderr
        assert str(workspace.resolve()) in completed.stderr
        assert "Reset incompatible legacy state? [y/N]" in completed.stderr
        assert json.loads(completed.stdout)["state_reset"]["decision"] == "declined"
        assert _tree_snapshot(state_dir) == before

        confirmed = _run_setup_cli(repository, state_dir, input_text="yes\n")

        assert confirmed.returncode == 0, confirmed.stderr
        assert json.loads(confirmed.stdout)["state_reset"] == {
            "changed": True,
            "decision": "confirmed",
        }
        assert not (state_dir / "daemon.db").exists()
        assert not (state_dir / "state.db").exists()
        assert not workspace.exists()


def test_noninteractive_reset_option_is_explicit_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        state_dir = root / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))

        first = _run_setup_cli(
            repository,
            state_dir,
            extra=("--reset-incompatible-state",),
        )
        second = _run_setup_cli(
            repository,
            state_dir,
            extra=("--reset-incompatible-state",),
        )

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert first.stderr == ""
        assert second.stderr == ""
        assert json.loads(first.stdout)["state_reset"] == {
            "changed": True,
            "decision": "explicit",
        }
        assert json.loads(second.stdout)["state_reset"] == {
            "changed": False,
            "decision": "explicit",
        }


def test_daemon_startup_reports_stable_incompatible_state_without_modifying_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        _create_legacy_databases(state_dir, run_ids=("run-1",))
        workspace = state_dir / "worktrees" / "run-1"
        workspace.mkdir(parents=True)
        (workspace / "owned.txt").write_text("owned", encoding="utf-8")
        before = _tree_snapshot(state_dir)

        completed = _run_daemon_cli(state_dir)

        assert completed.returncode == 1
        assert completed.stdout == ""
        assert json.loads(completed.stderr) == {
            "error": "incompatible_state",
            "message": (
                "incompatible legacy Run state; no migration is available; "
                "review and reset it with aiwb setup --repo <path> "
                "--state-dir <state-dir>"
            ),
        }
        assert _tree_snapshot(state_dir) == before


def test_daemon_refuses_corrupt_current_ledger_without_modifying_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        ledger = state_dir / "run-ledger.db"
        ledger.write_bytes(b"not a SQLite database")
        before = _tree_snapshot(state_dir)

        assessment = DurableStateSetup().inspect(state_dir)
        completed = _run_daemon_cli(state_dir)

        assert assessment.format == "incompatible_current"
        assert assessment.current_database == str(ledger.resolve())
        assert assessment.resettable is False
        assert completed.returncode == 1
        assert completed.stdout == ""
        assert json.loads(completed.stderr) == {
            "error": "incompatible_state",
            "message": (
                "incompatible current RunLedger state; preserve it for diagnosis; "
                "the explicit legacy reset does not apply"
            ),
        }
        assert _tree_snapshot(state_dir) == before


def test_daemon_refuses_unsupported_current_schema_version_without_modifying_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        ledger = state_dir / "run-ledger.db"
        SQLiteRunLedger(ledger)
        connection = sqlite3.connect(ledger)
        try:
            connection.execute(
                "UPDATE run_ledger_schema SET schema_version = 999 WHERE singleton = 1"
            )
            connection.commit()
        finally:
            connection.close()
        before = _tree_snapshot(state_dir)

        assessment = DurableStateSetup().inspect(state_dir)
        completed = _run_daemon_cli(state_dir)

        assert assessment.format == "incompatible_current"
        assert completed.returncode == 1
        assert json.loads(completed.stderr)["error"] == "incompatible_state"
        assert _tree_snapshot(state_dir) == before


def test_explicit_legacy_reset_refuses_incompatible_current_ledger() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        state_dir = root / "state"
        state_dir.mkdir()
        ledger = state_dir / "run-ledger.db"
        ledger.write_bytes(b"unsupported current ledger")
        before = _tree_snapshot(state_dir)

        with pytest.raises(StateResetError, match="legacy reset does not apply"):
            DurableStateSetup().reset(state_dir, confirmed=True)
        completed = _run_setup_cli(
            repository,
            state_dir,
            extra=("--reset-incompatible-state",),
        )

        assert completed.returncode == 1
        assert completed.stdout == ""
        assert json.loads(completed.stderr) == {
            "error": "operation_error",
            "message": (
                "incompatible current RunLedger state; preserve it for diagnosis; "
                "the explicit legacy reset does not apply"
            ),
        }
        assert _tree_snapshot(state_dir) == before


def test_explicit_legacy_reset_preserves_compatible_current_ledger_with_wal() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir()
        ledger = state_dir / "run-ledger.db"
        SQLiteRunLedger(ledger)
        writer = sqlite3.connect(ledger)
        try:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE hot_writer_probe (value TEXT NOT NULL)")
            writer.execute("INSERT INTO hot_writer_probe VALUES ('active')")
            writer.commit()
            assert (state_dir / "run-ledger.db-wal").exists()

            before = _tree_snapshot(state_dir)
            assessment = DurableStateSetup().inspect(state_dir)
            result = DurableStateSetup().reset(state_dir, confirmed=True)

            assert assessment.format == "current"
            assert result.changed is False
            assert result.assessment.format == "current"
            assert _tree_snapshot(state_dir) == before
        finally:
            writer.close()


def _create_legacy_databases(
    state_dir: Path,
    *,
    run_ids: tuple[str, ...] = (),
) -> None:
    with sqlite3.connect(state_dir / "state.db") as connection:
        connection.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                contract_hash TEXT NOT NULL,
                worktree TEXT NOT NULL
            );
            CREATE TABLE todos (
                run_id TEXT NOT NULL,
                todo_id TEXT NOT NULL,
                worktree TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO runs (run_id, contract_hash, worktree) VALUES (?, ?, ?)",
            (
                (run_id, f"hash-{run_id}", str(state_dir / "worktrees" / run_id / "candidate"))
                for run_id in run_ids
            ),
        )
    with sqlite3.connect(state_dir / "daemon.db") as connection:
        connection.execute(
            "CREATE TABLE daemon_jobs (run_id TEXT PRIMARY KEY, contract_path TEXT)"
        )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_setup_cli(
    repository: Path,
    state_dir: Path,
    *,
    input_text: str = "",
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "aiwb",
            "setup",
            "--repo",
            str(repository),
            "--state-dir",
            str(state_dir),
            *extra,
        ],
        cwd=str(TOOL_ROOT),
        env=environment,
        input=input_text,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _run_daemon_cli(state_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "aiwb",
            "daemon",
            "serve",
            "--state-dir",
            str(state_dir),
        ],
        cwd=str(TOOL_ROOT),
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
