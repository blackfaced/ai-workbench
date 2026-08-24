from __future__ import annotations

import json
import sys
import tempfile
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    AgentResult,
    AgentDaemon,
    DaemonClient,
    DaemonError,
    ExecutionSnapshot,
    GoalRunner,
    LeaseConflictError,
    SQLiteRunLedger,
)
from aiwb.mcp_server import McpServer  # noqa: E402


class UnusedAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError(f"Agent must not run while preparing {request.role}")


def test_expired_claim_is_replaced_with_a_monotonically_fenced_generation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteRunLedger(Path(directory) / "ledger.db")
        admitted = ledger.admit(
            _snapshot(),
            goal_id="fenced-goal",
        )
        start = datetime(2026, 8, 3, tzinfo=timezone.utc)

        first = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=10,
            now=start,
        )
        assert first is not None
        assert first.generation == 1
        assert ledger.claim(
            admitted.run_id,
            owner_id="daemon-b",
            lease_seconds=10,
            now=start + timedelta(seconds=9),
            supported_engine_versions={"other-engine"},
        ) is None
        assert ledger.run(admitted.run_id).status == "running"

        second = ledger.claim(
            admitted.run_id,
            owner_id="daemon-b",
            lease_seconds=10,
            now=start + timedelta(seconds=10),
        )
        assert second is not None
        assert second.generation == 2

        with pytest.raises(LeaseConflictError, match="stale Lease generation"):
            ledger.transition(
                admitted.run_id,
                owner_id="daemon-a",
                generation=first.generation,
                status="merge_ready",
                now=start + timedelta(seconds=11),
            )

        ledger.transition(
            admitted.run_id,
            owner_id="daemon-b",
            generation=second.generation,
            status="merge_ready",
            now=start + timedelta(seconds=11),
        )
        assert ledger.run(admitted.run_id).status == "merge_ready"
        assert ledger.queued_runs() == ()


def test_renewal_extends_the_same_generation_and_rejects_after_expiry() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteRunLedger(Path(directory) / "ledger.db")
        admitted = ledger.admit(_snapshot(), goal_id="fenced-goal")
        start = datetime(2026, 8, 3, tzinfo=timezone.utc)
        lease = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=10,
            now=start,
        )
        assert lease is not None

        renewed = ledger.renew(
            lease,
            lease_seconds=10,
            now=start + timedelta(seconds=9),
        )

        assert renewed.generation == lease.generation == 1
        assert ledger.prove(
            renewed,
            now=start + timedelta(seconds=18),
        ) == renewed
        with pytest.raises(LeaseConflictError, match="expired"):
            ledger.renew(
                renewed,
                lease_seconds=10,
                now=start + timedelta(seconds=19),
            )


def test_paused_projection_is_atomically_resumed_and_requeued() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteRunLedger(Path(directory) / "ledger.db")
        admitted = ledger.admit(_snapshot(), goal_id="fenced-goal")
        lease = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=30,
        )
        assert lease is not None
        ledger.transition(
            admitted.run_id,
            owner_id=lease.owner_id,
            generation=lease.generation,
            status="paused_resource",
        )

        observed = ledger.run(admitted.run_id)
        resumed = ledger.resume(admitted.run_id)

        assert observed.status == "paused_resource"
        assert resumed.status == "queued"
        assert ledger.queued_runs() == (resumed,)


def test_claim_preserves_an_unsupported_snapshot_as_incompatible_engine() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteRunLedger(Path(directory) / "ledger.db")
        admitted = ledger.admit(_snapshot(), goal_id="fenced-goal")

        claimed = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=10,
            supported_engine_versions={"other-engine"},
            supported_admission_schema_versions={1},
            supported_transition_policy_versions={"strict-v1"},
        )

        assert claimed is None
        run = ledger.run(admitted.run_id)
        assert run.status == "incompatible_engine"
        assert "test-engine" in run.error
        assert ledger.queued_runs() == ()


def test_runner_prepares_an_admitted_run_from_only_the_stored_manifest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AIWB Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "fixture")
        commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        snapshot = _snapshot(repository=repository, base_commit=commit)

        report = GoalRunner(root / "runner-state", UnusedAgent()).prepare_snapshot(
            snapshot,
            run_id="admitted-run-1",
        )

        assert report.run_id == "admitted-run-1"
        assert report.goal_id == "fenced-goal"
        assert report.status == "approved"


def test_runner_rejects_a_worker_that_cannot_prove_its_generation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AIWB Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "fixture")
        commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        runner = GoalRunner(root / "runner-state", UnusedAgent())

        with pytest.raises(LeaseConflictError, match="stale worker"):
            runner.run_snapshot(
                _snapshot(repository=repository, base_commit=commit),
                run_id="stale-run",
                mutation_guard=lambda: _reject_stale_worker(),
            )

        with pytest.raises(KeyError):
            runner.report("stale-run")


def test_takeover_between_fence_and_worker_write_leaves_no_durable_effect() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AIWB Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "fixture")
        commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        snapshot = _snapshot(repository=repository, base_commit=commit)

        def take_over(boundary, connection, run_id) -> None:
            if boundary != "after_worker_fence":
                return
            connection.execute(
                """
                UPDATE run_leases
                SET owner_id = 'daemon-b', generation = generation + 1
                WHERE run_id = ?
                """,
                (run_id,),
            )

        ledger = SQLiteRunLedger(
            root / "state" / "run-ledger.db",
            _worker_fault_injector=take_over,
        )
        admitted = ledger.admit(snapshot, goal_id="fenced-goal")
        lease = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=30,
        )
        assert lease is not None
        runner = GoalRunner(root / "state", UnusedAgent(), ledger=ledger)

        with pytest.raises(LeaseConflictError, match="stale Lease generation"):
            runner.prepare_snapshot(
                snapshot,
                run_id=admitted.run_id,
                lease=lease,
            )

        assert ledger.run(admitted.run_id).status == "running"
        assert not (root / "state" / "state.db").exists()


def test_state_directory_allows_only_one_daemon_even_with_another_socket() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        first = AgentDaemon(
            state_dir,
            UnusedAgent(),
            socket_path=state_dir / "run" / "first.sock",
        )
        first_thread = threading.Thread(target=first.serve_forever, daemon=True)
        first_thread.start()
        _wait_until(DaemonClient(first.socket_path).ping)
        second = AgentDaemon(
            state_dir,
            UnusedAgent(),
            socket_path=state_dir / "run" / "second.sock",
        )

        try:
            with pytest.raises(RuntimeError, match="state directory"):
                second.serve_forever()
        finally:
            first.shutdown()
            first_thread.join(timeout=5)


def test_daemon_marks_unsupported_runs_without_starting_an_agent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state_dir = root / "state"
        ledger = SQLiteRunLedger(state_dir / "run-ledger.db")
        admitted = ledger.admit(_snapshot(), goal_id="fenced-goal")
        daemon = AgentDaemon(
            state_dir,
            UnusedAgent(),
            socket_path=state_dir / "run" / "daemon.sock",
            engine_version="supported-engine",
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(daemon.socket_path)

        try:
            _wait_until(client.ping)
            _wait_until(
                lambda: client.status(admitted.run_id).status
                == "incompatible_engine"
            )
            assert "test-engine" in client.status(admitted.run_id).error
        finally:
            daemon.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize(
    ("argument_name", "argument_value", "expected_code"),
    (
        ("workflow_path", "", "admission_error"),
        ("idempotency_key", "", "admission_error"),
        ("workflow_path", 7, "invalid_request"),
        ("idempotency_key", 7, "invalid_request"),
    ),
)
def test_daemon_and_mcp_share_submission_normalization_and_errors(
    argument_name: str,
    argument_value: object,
    expected_code: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        daemon = AgentDaemon(state_dir, UnusedAgent())
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(daemon.socket_path)
        missing_contract = Path(directory) / "missing-contract.yaml"
        try:
            _wait_until(client.ping)
            with pytest.raises(DaemonError) as direct_error:
                client.submit(
                    missing_contract,
                    **{argument_name: argument_value},
                )

            mcp_result = McpServer(daemon.socket_path)._call_tool(
                "aiwb_goal_submit",
                {
                    "contract_path": str(missing_contract),
                    argument_name: argument_value,
                },
            )
            mcp_error = json.loads(mcp_result["content"][0]["text"])

            assert direct_error.value.code == expected_code
            assert mcp_error == {
                "error": direct_error.value.code,
                "message": str(direct_error.value),
            }
        finally:
            daemon.shutdown()
            thread.join(timeout=5)


def _snapshot(
    *,
    repository: Path = Path("/tmp/repository"),
    base_commit: str = "a" * 40,
) -> ExecutionSnapshot:
    from aiwb.admission import _snapshot_id

    source = b"approved source"
    manifest = {
        "schema_version": 1,
        "versions": {
            "admission_schema": 1,
            "engine": "test-engine",
            "transition_policy": "strict-v1",
        },
        "approval_status": "approved",
        "goal": {
            "id": "fenced-goal",
            "title": "Fence workers",
            "requirement": "Reject stale workers.",
            "acceptance": [{"test_id": "AC-1", "statement": "Stale writes fail."}],
        },
        "agent": {"provider": "codex", "model": None},
        "repository": {
            "path": str(repository),
            "base_ref": "main",
            "base_commit": base_commit,
        },
        "todos": [
            {
                "todo_id": "T-1",
                "title": "Implement fencing",
                "depends_on": [],
                "test_ids": ["AC-1"],
                "test_command": ["pytest"],
                "allowed_test_paths": ["tests/**"],
                "timeout_seconds": 60,
                "harness_name": "",
                "harness": None,
            }
        ],
        "resources": {},
        "role_guidance": {},
        "image_profile": None,
        "publish_policy": None,
        "policy": {
            "path": "/tmp/workflow.yaml",
            "source": "repository",
            "candidate_commands": [],
            "approved_commands": [["pytest"]],
        },
        "required_secrets": [],
    }
    return ExecutionSnapshot(
        snapshot_id=_snapshot_id(source, manifest),
        source=source,
        manifest=manifest,
        created_at="2026-08-03T00:00:00+00:00",
    )


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_until(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (ConnectionError, FileNotFoundError):
            pass
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def _reject_stale_worker() -> None:
    raise LeaseConflictError("stale worker generation")
