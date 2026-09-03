from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    ActivityEvent,
    Admission,
    AdmissionRequest,
    AttemptOutcome,
    SQLiteRunLedger,
    VerificationEvidence,
)
from aiwb.harness_native import LeaseConflictError  # noqa: E402
from aiwb.runner import approve_execution  # noqa: E402


def _admitted(root: Path) -> tuple:
    repository = root / "repository"
    repository.mkdir()
    for command in (
        ("git", "init", "-b", "main"),
        ("git", "config", "user.name", "AI Workbench Test"),
        ("git", "config", "user.email", "aiwb@example.test"),
    ):
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    subprocess.run(("git", "commit", "-m", "fixture"), cwd=repository, check=True)
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 5,
                "goal": {
                    "id": "transitions",
                    "title": "Transition coverage",
                    "requirement": "Exercise Run transitions.",
                    "acceptance": [{"id": "AC-1", "statement": "Tests pass."}],
                },
                "approval": {
                    "artifact_path": str(root / "execution-approval.json"),
                },
                "instructions": "Exercise the agreed transition behavior.",
                "agent_harness": {
                    "driver": "codex",
                    "model": "gpt-test",
                    "effort": "high",
                    "permissions": ["workspace-write"],
                    "capability_ceiling": ["git"],
                    "extensions": [],
                    "allowed_paths": ["."],
                    "tools": ["shell"],
                    "input_artifact": "contract.yaml",
                    "output_schema": "attempt-outcome/v1",
                    "timeout_seconds": 60,
                    "max_attempts": 2,
                    "resource_limits": {"tokens": 1000},
                    "native_configuration": {"mode": "test"},
                    "trace_coverage": ["activity"],
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "verification": {
                    "command": [sys.executable, "-c", "raise SystemExit(0)"],
                    "timeout_seconds": 30,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    approve_execution(
        contract,
        approved_by="owner",
        artifact_path=root / "execution-approval.json",
        approved_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
    admitted = Admission(
        ledger,
        engine_version="test-engine",
        transition_policy_version="strict-v2",
    ).admit(AdmissionRequest(contract))
    return ledger, admitted


def _transition_count(root: Path) -> int:
    with sqlite3.connect(root / "state" / "run-ledger.db") as connection:
        return connection.execute("SELECT COUNT(*) FROM run_transitions").fetchone()[0]


def _candidate_run(root: Path):
    ledger, admitted = _admitted(root)
    lease = ledger.claim(admitted.run_id, owner_id="daemon", lease_seconds=30)
    attempt_id = ledger.start_attempt(
        admitted.run_id, worktree=root / "worktree", branch="aiwb/test", lease=lease
    )
    ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"), lease=lease)
    candidate_commit = "a" * 40
    ledger.checkpoint_candidate(admitted.run_id, attempt_id, candidate_commit, lease=lease)
    ledger.record_verification(
        admitted.run_id,
        VerificationEvidence(
            command=("verify",),
            returncode=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.1,
            attempt_id=attempt_id,
            candidate_commit=candidate_commit,
        ),
        lease=lease,
    )
    ledger.accept_candidate(admitted.run_id, candidate_commit, attempt_id=attempt_id, lease=lease)
    return ledger, admitted, attempt_id


def test_allowed_run_transitions_cover_the_complete_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        assert ledger.run(admitted.run_id).status == "queued"
        lease = ledger.claim(admitted.run_id, owner_id="daemon", lease_seconds=30)
        assert ledger.run(admitted.run_id).status == "attempting"
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test", lease=lease
        )
        ledger.record_activity(attempt_id, ActivityEvent.activity("tool", "work"), lease=lease)
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"), lease=lease)
        assert ledger.run(admitted.run_id).status == "verifying"
        candidate_commit = "b" * 40
        ledger.checkpoint_candidate(admitted.run_id, attempt_id, candidate_commit, lease=lease)
        ledger.record_verification(
            admitted.run_id,
            VerificationEvidence(
                command=("verify",),
                returncode=0,
                stdout="ok",
                stderr="",
                duration_seconds=0.1,
                attempt_id=attempt_id,
                candidate_commit=candidate_commit,
            ),
            lease=lease,
        )
        ledger.accept_candidate(admitted.run_id, candidate_commit, attempt_id=attempt_id, lease=lease)
        assert ledger.run(admitted.run_id).status == "candidate"


def test_direct_attempt_start_moves_queued_run_to_attempting_and_retry_requeues() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        assert ledger.run(admitted.run_id).status == "attempting"
        ledger.finish_attempt(attempt_id, AttemptOutcome.failed("boom"))
        assert ledger.run(admitted.run_id).status == "failed"
        retried = ledger.retry(admitted.run_id)
        assert retried.status == "queued"
        lease = ledger.claim(admitted.run_id, owner_id="daemon", lease_seconds=30)
        assert lease is not None
        assert ledger.run(admitted.run_id).status == "attempting"


def test_interrupted_attempt_is_terminal_and_retry_requeues_the_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.interrupted("host stopped"))
        assert ledger.run(admitted.run_id).status == "interrupted"
        assert ledger.retry(admitted.run_id).status == "queued"


def test_lease_expiry_sweeps_the_running_attempt_and_fences_the_stale_lease() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        started = datetime.now(timezone.utc)
        first = ledger.claim(admitted.run_id, owner_id="daemon-a", lease_seconds=5)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test", lease=first
        )
        recovered = ledger.claim(
            admitted.run_id, owner_id="daemon-b", lease_seconds=30,
            now=started + timedelta(seconds=10),
        )
        assert recovered is not None
        assert recovered.generation == first.generation + 1
        assert ledger.run(admitted.run_id).status == "attempting"
        attempts = ledger.projection(admitted.run_id).attempts
        assert attempts[-1].attempt_id == attempt_id
        assert attempts[-1].outcome == "interrupted"
        with pytest.raises(LeaseConflictError, match="stale Lease generation"):
            ledger.renew(first, lease_seconds=30)
        with pytest.raises(RuntimeError, match="already terminal"):
            ledger.record_activity(
                attempt_id, ActivityEvent.activity("status", "late"), lease=recovered
            )


def test_queued_run_can_be_failed_before_any_claim() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        ledger.fail(admitted.run_id, "unsupported engine version in ExecutionSnapshot")
        assert ledger.run(admitted.run_id).status == "failed"
        assert ledger.queued_runs() == ()


def test_fail_on_terminal_candidate_is_rejected_without_durable_effect() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted, _attempt_id = _candidate_run(root)
        before = ledger.projection(admitted.run_id).to_dict()
        transitions_before = _transition_count(root)
        with pytest.raises(RuntimeError, match="invalid Run transition"):
            ledger.fail(admitted.run_id, "late failure")
        assert ledger.projection(admitted.run_id).to_dict() == before
        assert _transition_count(root) == transitions_before


def test_fail_on_failed_run_is_rejected_without_durable_effect() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        ledger.fail(admitted.run_id, "first failure")
        with pytest.raises(RuntimeError, match="already terminal"):
            ledger.fail(admitted.run_id, "second failure")
        assert ledger.run(admitted.run_id).status == "failed"


def test_fail_on_interrupted_run_is_rejected_and_retry_still_works() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.interrupted("host stopped"))
        with pytest.raises(RuntimeError, match="invalid Run transition"):
            ledger.fail(admitted.run_id, "late failure")
        assert ledger.retry(admitted.run_id).status == "queued"


def test_retry_on_terminal_candidate_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted, _attempt_id = _candidate_run(root)
        with pytest.raises(ValueError, match="not retryable"):
            ledger.retry(admitted.run_id)
        assert ledger.run(admitted.run_id).status == "candidate"


def test_attempt_cannot_start_on_verifying_or_terminal_runs() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        assert ledger.run(admitted.run_id).status == "verifying"
        with pytest.raises(RuntimeError, match="Attempt cannot start"):
            ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted, _attempt_id = _candidate_run(root)
        with pytest.raises(RuntimeError, match="Attempt cannot start"):
            ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test")


def test_activity_is_rejected_before_attempt_start_and_after_terminal_outcome() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        with pytest.raises(KeyError):
            ledger.record_activity("unknown-attempt", ActivityEvent.activity("status", "early"))
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        with pytest.raises(RuntimeError, match="already terminal"):
            ledger.record_activity(attempt_id, ActivityEvent.activity("status", "late"))
        with pytest.raises(RuntimeError, match="already terminal"):
            ledger.finish_attempt(attempt_id, AttemptOutcome.completed("again"))


def test_terminal_runs_cannot_be_claimed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted, _attempt_id = _candidate_run(root)
        assert ledger.claim(admitted.run_id, owner_id="daemon", lease_seconds=30) is None
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted = _admitted(root)
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.interrupted("host stopped"))
        assert ledger.claim(admitted.run_id, owner_id="daemon", lease_seconds=30) is None


def test_clear_checkpoint_and_acceptance_are_rejected_on_terminal_runs() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger, admitted, attempt_id = _candidate_run(root)
        with pytest.raises(RuntimeError, match="immutable"):
            ledger.clear_checkpoint(admitted.run_id)
        with pytest.raises(RuntimeError):
            ledger.accept_candidate(admitted.run_id, "a" * 40, attempt_id=attempt_id)
        assert ledger.run(admitted.run_id).status == "candidate"
