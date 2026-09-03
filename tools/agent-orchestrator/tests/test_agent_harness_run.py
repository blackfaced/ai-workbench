from __future__ import annotations

import json
import multiprocessing
import os
import signal
import sys
import tempfile
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
import pytest


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    ActivityEvent,
    Admission,
    AdmissionRequest,
    AttemptOutcome,
    GoalRunner,
    GoalIntake,
    RunLease,
    RunReport,
    SQLiteRunLedger,
    VerificationEvidence,
)
from aiwb import AgentDaemon  # noqa: E402
from aiwb.runner import approve_execution, preview_execution  # noqa: E402
from aiwb import AgentHarnessProfile, AttemptSpec  # noqa: E402
from aiwb.harness import HarnessExecution  # noqa: E402
from aiwb.image import ImageBuildResult  # noqa: E402
from aiwb.publish import CandidatePublishResult  # noqa: E402
from aiwb import cli as cli_module  # noqa: E402
from aiwb import harness_native as harness_native  # noqa: E402
from aiwb.harness_native import LeaseConflictError  # noqa: E402


@dataclass
class FakeAgentHarnessDriver:
    """Strict fake kept beside the behavior tests that consume it."""

    outcome: AttemptOutcome = field(default_factory=AttemptOutcome.completed)
    events: tuple[ActivityEvent, ...] = ()
    supported_capabilities: tuple[str, ...] = ("git",)
    specs: list[AttemptSpec] = field(default_factory=list)

    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        self.specs.append(attempt_spec)
        for event in self.events:
            event_sink(event)
        return self.outcome

    def validate(self, profile):
        expected = {
            "driver": "codex",
            "model": "gpt-test",
            "effort": "high",
            "permissions": ("workspace-write",),
            "extensions": ("skill:focused@1",),
            "allowed_paths": (".",),
            "tools": ("shell",),
            "trace_coverage": ("activity",),
            "input_artifact": "contract.yaml",
            "output_schema": "attempt-outcome/v1",
        }
        for name, value in expected.items():
            if getattr(profile, name) != value:
                raise ValueError(f"unsupported Agent Harness {name}")
        unsupported = sorted(
            set(profile.capability_ceiling) - set(self.supported_capabilities)
        )
        if unsupported:
            raise ValueError(f"unsupported capability: {', '.join(unsupported)}")
        if dict(profile.resource_limits) != {"tokens": 1000}:
            raise ValueError("unsupported Agent Harness resource limits")
        if dict(profile.native_configuration) != {"mode": "test"}:
            raise ValueError("unsupported Agent Harness native configuration")
        if profile.extensions and not profile.resolved_extensions:
            raise ValueError("Harness Extensions were not resolved before external execution")


def test_completed_harness_attempt_requires_verification_evidence_to_accept_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v2",
        ).admit(AdmissionRequest(contract))
        driver = FakeAgentHarnessDriver(
            outcome=AttemptOutcome.completed("Harness completed."),
            events=(ActivityEvent.activity("edit", "Updated greeting."),),
        )

        report = GoalRunner(root / "state", driver, ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id),
            run_id=admitted.run_id,
        )

        assert report.status == "candidate"
        assert len(report.attempts) == 1
        assert report.attempts[0].outcome == "completed"
        assert [event.kind for event in report.activity] == ["edit"]
        assert len(report.evidence) == 1


def test_interrupted_attempt_is_terminal_and_retry_starts_a_fresh_attempt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v2",
        ).admit(AdmissionRequest(contract))
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)

        interrupted = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(outcome=AttemptOutcome.interrupted("host stopped")),
            ledger=ledger,
        ).run_snapshot(snapshot, run_id=admitted.run_id)
        resumed = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(),
            ledger=ledger,
        )
        resumed.resume(admitted.run_id)
        accepted = resumed.run_snapshot(snapshot, run_id=admitted.run_id)

        assert interrupted.status == "interrupted"
        assert accepted.status == "candidate"
        assert [attempt.outcome for attempt in accepted.attempts] == [
            "interrupted",
            "completed",
        ]
        assert interrupted.worktree == accepted.worktree


def test_run_rejects_a_snapshot_not_bound_at_admission_before_external_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admission = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3")
        first = admission.admit(AdmissionRequest(contract))
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["goal"]["id"] = "other"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        second = admission.admit(AdmissionRequest(contract))
        driver = FakeAgentHarnessDriver()

        with pytest.raises(RuntimeError, match="different ExecutionSnapshot"):
            GoalRunner(root / "state", driver, ledger=ledger).run_snapshot(
                ledger.execution_snapshot(second.snapshot_id), run_id=first.run_id
            )
        assert driver.specs == []


def test_admitted_harness_profile_is_executed_by_the_verification_harness() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        command = [sys.executable, "-c", "raise SystemExit(0)"]
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved",
            "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {
                "gate": {"argv": command, "approved": True},
                "serve": {"argv": [sys.executable, "-c", "pass"], "approved": True},
            }, "skills": {}},
            "harness": {"profiles": {"local": {
                "kind": "local_process", "environment": "local",
                "start": {"command": [sys.executable, "-c", "pass"]},
                "ready": {"url": "http://127.0.0.1:{port}/health", "timeout_seconds": 1},
            }}}, "images": {"profiles": {}},
        }, sort_keys=False), encoding="utf-8")
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["policy"] = str(workflow)
        value["verification"]["harness"] = "local"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(AdmissionRequest(contract))
        harness = _RecordingHarness()

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, local_harness=harness).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"
        assert len(report.evidence[0].artifact_refs) == 1
        assert report.evidence[0].artifact_refs[0].label == "verification artifact: verification.log"


def test_image_and_candidate_publication_follow_verified_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        remote = root / "remote.git"
        import subprocess
        subprocess.run(("git", "init", "--bare", str(remote)), check=True, capture_output=True)
        subprocess.run(("git", "remote", "add", "origin", str(remote)), cwd=repository, check=True)
        contract = _contract(root, repository)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        command = [sys.executable, "-c", "raise SystemExit(0)"]
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved", "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {name: {"argv": command, "approved": True} for name in ("gate", "image_start", "image_status", "image_result")}, "skills": {}},
            "harness": {"profiles": {}},
            "images": {"profiles": {"candidate-image": {
                "environment": "non-production", "start": {"command": command},
                "status": {"command": command}, "result": {"command": command},
            }}},
            "publishing": {"candidate": {"approved": True, "remote": "origin", "branch_prefix": "aiwb/"}},
        }, sort_keys=False), encoding="utf-8")
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["policy"] = str(workflow)
        value["candidate"] = {"image_profile": "candidate-image", "publish": True}
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(AdmissionRequest(contract))
        subprocess.run(("git", "remote", "set-url", "origin", "https://changed.example.test/repository.git"), cwd=repository, check=True)
        builder, publisher = _RecordingImageBuilder(), _RecordingPublisher()
        requested_contexts = []
        original_context = harness_native.multiprocessing.get_context

        def record_context(name=None):
            requested_contexts.append(name)
            return original_context(name)

        monkeypatch.setattr(harness_native.multiprocessing, "get_context", record_context)

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, image_builder=builder, publisher=publisher).run_snapshot(ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id)

        assert report.status == "candidate"
        assert requested_contexts == ["spawn"] * 7
        assert any(item.command == ("image", "candidate-image") for item in report.evidence)
        assert report.to_dict()["publish_result"]["commit"] == report.candidate_commit


def test_fake_driver_rejects_an_unapproved_capability_before_starting_attempt() -> None:
    driver = FakeAgentHarnessDriver(supported_capabilities=())
    spec = AttemptSpec(
        run_id="run-1",
        attempt_id="attempt-1",
        worktree=Path("/tmp/worktree"),
        instructions="Implement the agreed behavior.",
        profile=AgentHarnessProfile(
            driver="codex",
            model="gpt-test",
            effort="high",
            permissions=("workspace-write",),
            capability_ceiling=("git",),
            extensions=("skill:focused@1",),
            allowed_paths=(".",),
            tools=("shell",),
            input_artifact="contract.yaml",
            output_schema="attempt-outcome/v1",
            timeout_seconds=60,
            max_attempts=1,
            resource_limits={"tokens": 1000},
            native_configuration={"mode": "test"},
            trace_coverage=("activity",),
        ),
    )

    with pytest.raises(ValueError, match="unsupported capability"):
        driver.execute(spec, lambda _: None)
    assert driver.specs == []


def test_admission_rejects_an_approved_contract_when_its_profile_changed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        contract = _contract(root, _repository(root))
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["model"] = "other-model"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="does not match the complete execution"):
            Admission(SQLiteRunLedger(root / "state" / "run-ledger.db"), engine_version="test-engine", transition_policy_version="strict-v3").admit(
                AdmissionRequest(contract)
            )

        assert preview_execution(contract).approval_status == "stale"


def test_runner_fails_closed_before_creating_a_worktree_for_an_unsupported_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v2",
        ).admit(AdmissionRequest(contract))
        runner = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(supported_capabilities=()),
            ledger=ledger,
        )

        with pytest.raises(ValueError, match="unsupported capability"):
            runner.run_snapshot(
                ledger.execution_snapshot(admitted.snapshot_id),
                run_id=admitted.run_id,
            )

        assert not (root / "state" / "worktrees" / admitted.run_id).exists()


def test_attempt_is_terminal_when_process_isolation_cannot_be_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))
        runner = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger)
        manifest = ledger.execution_snapshot(admitted.snapshot_id).manifest
        runner._worktree(  # noqa: SLF001
            admitted.run_id, manifest["repository"], 60, lambda: None
        )
        original_context = multiprocessing.get_context("spawn")

        class BrokenIsolationContext:
            def Queue(self):
                return original_context.Queue()

            def Pipe(self, *, duplex):
                raise OSError("cannot create liveness pipe")

        monkeypatch.setattr(
            harness_native.multiprocessing,
            "get_context",
            lambda _name: BrokenIsolationContext(),
        )

        report = runner.run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "failed"
        assert report.attempts[0].outcome == "failed"
        assert "isolation is unsupported" in report.attempts[0].summary


def test_completed_attempt_cannot_leave_a_background_descendant_running() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))

        report = GoalRunner(
            root / "state", _BackgroundWritingDriver(), ledger=ledger
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )
        time.sleep(2.5)

        assert report.status == "candidate"
        assert not (Path(report.worktree) / "background-driver-write.txt").exists()


def test_new_run_ledger_schema_has_attempts_and_no_todo_authority() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "run-ledger.db"
        SQLiteRunLedger(database)
        with sqlite3.connect(database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            version = connection.execute(
                "SELECT schema_version FROM run_ledger_schema WHERE singleton = 1"
            ).fetchone()[0]

        assert version == 5
        assert {"runs", "attempts", "activity_events"} <= tables
        assert "todos" not in tables


def test_incompatible_ledger_schema_fails_without_creating_new_tables() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "run-ledger.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE run_ledger_schema (singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL)"
            )
            connection.execute("INSERT INTO run_ledger_schema VALUES (1, 1)")

        with pytest.raises(RuntimeError, match="explicit reset"):
            SQLiteRunLedger(database)
        with sqlite3.connect(database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        assert tables == {"run_ledger_schema"}


def test_stale_lease_cannot_start_an_attempt_or_write_a_transition() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v2",
        ).admit(AdmissionRequest(contract))
        lease = ledger.claim(
            admitted.run_id,
            owner_id="daemon-a",
            lease_seconds=30,
        )
        assert lease is not None
        stale = RunLease(
            run_id=lease.run_id,
            owner_id=lease.owner_id,
            generation=lease.generation + 1,
            expires_at=lease.expires_at,
        )

        with pytest.raises(RuntimeError, match="stale Lease generation"):
            ledger.start_attempt(
                admitted.run_id,
                worktree=root / "worktree",
                branch="aiwb/test",
                lease=stale,
            )


def test_driver_exception_finishes_the_attempt_and_fails_the_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        report = GoalRunner(root / "state", _ExplodingDriver(), ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "failed"
        assert [(attempt.status, attempt.outcome) for attempt in report.attempts] == [
            ("terminal", "failed")
        ]


def test_attempt_timeout_terminalizes_the_run_without_waiting_for_a_blocked_driver() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["timeout_seconds"] = 1
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(contract)
        )
        driver = _BlockingDriver()
        started = time.monotonic()

        report = GoalRunner(root / "state", driver, ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert time.monotonic() - started < 8  # Interpreter boot time is environment-dependent; the blocked driver would hold the Run for 10 seconds.
        assert report.status == "interrupted"
        assert report.attempts[0].outcome == "interrupted"


def test_activity_flood_cannot_prevent_the_attempt_deadline() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["timeout_seconds"] = 1
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v3",
        ).admit(AdmissionRequest(contract))
        report_path = root / "flood-report.txt"
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_run_flooding_attempt,
            args=(root / "state", root / "state" / "run-ledger.db", admitted.run_id, report_path),
        )

        process.start()
        process.join(15)
        finished_before_cleanup = not process.is_alive()
        if process.is_alive():
            process.kill()
            process.join(2)

        assert finished_before_cleanup
        assert report_path.read_text(encoding="utf-8") == "interrupted\n"
        assert len(ledger.projection(admitted.run_id).activity) <= 512


def test_attempt_can_complete_at_the_declared_activity_event_budget() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v3",
        ).admit(AdmissionRequest(_contract(root, _repository(root))))

        report = GoalRunner(
            root / "state", _MaximumActivityDriver(), ledger=ledger
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"
        assert len(report.activity) == 256


def test_attempt_rejects_an_activity_event_after_the_declared_budget() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v3",
        ).admit(AdmissionRequest(_contract(root, _repository(root))))

        report = GoalRunner(
            root / "state", _OverflowingActivityDriver(), ledger=ledger
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "interrupted"
        assert len(report.activity) == 256


def test_attempt_timeout_terminates_the_driver_before_it_can_write_late_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["timeout_seconds"] = 1
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(contract)
        )

        report = GoalRunner(root / "state", _LateWritingDriver(), ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )
        time.sleep(1.0)

        assert report.status == "interrupted"
        assert not (Path(report.worktree) / "late-driver-write.txt").exists()


def test_attempt_uses_a_fresh_interpreter_not_a_forked_daemon_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_contexts = []
    original_context = harness_native.multiprocessing.get_context

    def record_context(name=None):
        requested_contexts.append(name)
        return original_context(name)

    monkeypatch.setattr(harness_native.multiprocessing, "get_context", record_context)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, _repository(root)))
        )

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"
        assert requested_contexts == ["spawn", "spawn", "spawn"]


def test_lease_loss_terminates_the_driver_before_it_can_write_late_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        lease_provider = _LeaseLostAfterAttemptStart()

        with pytest.raises(LeaseConflictError, match="lease was lost"):
            GoalRunner(root / "state", _ActivityThenLateWritingDriver(), ledger=ledger).run_snapshot(
                ledger.execution_snapshot(admitted.snapshot_id),
                run_id=admitted.run_id,
                lease_provider=lease_provider,
            )
        time.sleep(1.0)

        assert not (root / "state" / "worktrees" / admitted.run_id / "late-lease-write.txt").exists()


def test_trace_coverage_filters_events_outside_the_admitted_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        report = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(events=(
                ActivityEvent.activity("edit", "kept"),
                ActivityEvent.activity("usage", "dropped"),
            )),
            ledger=ledger,
        ).run_snapshot(ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id)

        assert report.status == "candidate"
        assert [event.summary for event in report.activity] == ["kept"]


def test_only_evidence_for_the_current_attempt_and_candidate_commit_accepts_a_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, _repository(root)))
        )
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test")
        evidence = _verification_evidence(attempt_id, "a" * 40)
        with pytest.raises(RuntimeError, match="completed Attempt"):
            ledger.record_verification(admitted.run_id, evidence)
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        ledger.checkpoint_candidate(admitted.run_id, attempt_id, "a" * 40)
        ledger.record_verification(admitted.run_id, evidence)

        with pytest.raises(RuntimeError, match="durable Candidate Checkpoint"):
            ledger.accept_candidate(admitted.run_id, "b" * 40, attempt_id=attempt_id)

        ledger.accept_candidate(admitted.run_id, "a" * 40, attempt_id=attempt_id)
        assert ledger.run(admitted.run_id).status == "candidate"


def test_run_report_round_trip_keeps_publish_result_serializable() -> None:
    original = RunReport(
        run_id="run", goal_id="goal", status="candidate", branch="aiwb/run",
        worktree="/tmp/worktree", attempts=(), activity=(), evidence=(),
        publish_result={"commit": "a" * 40},
    )

    assert RunReport.from_dict(original.to_dict()).to_dict()["publish_result"] == {"commit": "a" * 40}


def test_projection_reads_one_ledger_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, _repository(root)))
        )
        connections = []
        original_connect = ledger._connect  # noqa: SLF001

        def connect_once():
            connections.append(True)
            return original_connect()

        monkeypatch.setattr(ledger, "_connect", connect_once)

        assert ledger.projection(admitted.run_id).status == "queued"
        assert len(connections) == 1


def test_claim_preserves_verifying_for_a_completed_attempt_without_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, _repository(root)))
        )
        started = datetime.now(timezone.utc)
        first = ledger.claim(admitted.run_id, owner_id="daemon-a", lease_seconds=1, now=started)
        assert first is not None
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test", lease=first)
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"), lease=first)

        recovered = ledger.claim(admitted.run_id, owner_id="daemon-b", lease_seconds=1, now=started + timedelta(seconds=2))

        assert recovered is not None
        assert ledger.run(admitted.run_id).status == "verifying"


@pytest.mark.parametrize("checkpoint", ("image", "publish"))
def test_retry_refuses_to_clear_an_unknown_external_operation_checkpoint(checkpoint: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, _repository(root)))
        )
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test")
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        ledger.checkpoint_candidate(admitted.run_id, attempt_id, "a" * 40)
        ledger.record_verification(
            admitted.run_id, _verification_evidence(attempt_id, "a" * 40)
        )
        if checkpoint == "image":
            ledger.checkpoint_image_starting(admitted.run_id, attempt_id, "a" * 40)
        else:
            ledger.checkpoint_publish_starting(admitted.run_id, attempt_id, "a" * 40)
        ledger.fail(admitted.run_id, "simulated daemon crash")

        with pytest.raises(ValueError, match="outcome is unknown"):
            ledger.retry(admitted.run_id)

        assert ledger.checkpoint(admitted.run_id).stage == f"{checkpoint}_starting"


def test_run_ledger_rejects_out_of_order_candidate_product_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, _repository(root))))
        attempt_id = ledger.start_attempt(
            admitted.run_id, worktree=root / "worktree", branch="aiwb/test"
        )
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        ledger.checkpoint_candidate(admitted.run_id, attempt_id, "a" * 40)

        with pytest.raises(RuntimeError, match="invalid Run Checkpoint transition"):
            ledger.checkpoint_publish_starting(
                admitted.run_id, attempt_id, "a" * 40
            )

        ledger.record_verification(
            admitted.run_id, _verification_evidence(attempt_id, "a" * 40)
        )
        ledger.checkpoint_image_starting(admitted.run_id, attempt_id, "a" * 40)
        ledger.checkpoint_image_running(
            admitted.run_id, attempt_id, "a" * 40, "operation-1"
        )
        failed_image = VerificationEvidence(
            command=("image",), returncode=1, stdout="", stderr="failed",
            duration_seconds=0.0, attempt_id=attempt_id,
            candidate_commit="a" * 40, stage="image",
        )

        with pytest.raises(RuntimeError, match="failed image Evidence"):
            ledger.record_verification(admitted.run_id, failed_image)


def test_completed_attempt_recovers_dirty_durable_worktree_by_freezing_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        runner = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger)
        manifest = ledger.execution_snapshot(admitted.snapshot_id).manifest
        worktree, branch = runner._worktree(  # noqa: SLF001
            admitted.run_id, manifest["repository"], 60, lambda: None
        )
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=worktree, branch=branch)
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        (worktree / "completed-output.txt").write_text("durably produced\n", encoding="utf-8")

        report = runner.run_snapshot(ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id)

        assert report.status == "candidate"
        import subprocess
        recovered = subprocess.run(
            ("git", "show", f"{report.candidate_commit}:completed-output.txt"),
            cwd=worktree, check=True, text=True, capture_output=True,
        )
        assert recovered.stdout == "durably produced\n"


def test_running_image_checkpoint_recovers_without_starting_a_second_build(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        command = [sys.executable, "-c", "raise SystemExit(0)"]
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved", "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {name: {"argv": command, "approved": True} for name in ("gate", "image_start", "image_status", "image_result")}, "skills": {}},
            "harness": {"profiles": {}}, "images": {"profiles": {"candidate-image": {"environment": "non-production", "start": {"command": command}, "status": {"command": command}, "result": {"command": command}}}},
        }, sort_keys=False), encoding="utf-8")
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["policy"] = str(workflow)
        value["candidate"] = {"image_profile": "candidate-image"}
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(AdmissionRequest(contract))
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)
        assert "image" in snapshot.manifest["candidate"]
        builder = _FileCountingImageBuilder()
        runner = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, image_builder=builder)
        image_call = runner._image_call  # noqa: SLF001

        def interrupted_status(deadline, operation, *image_call_args, **image_call_kwargs):
            if image_call_args[0] == "result":
                raise KeyboardInterrupt("simulated daemon crash")
            return image_call(deadline, operation, *image_call_args, **image_call_kwargs)

        monkeypatch.setattr(runner, "_image_call", interrupted_status)

        with pytest.raises(KeyboardInterrupt):
            runner.run_snapshot(snapshot, run_id=admitted.run_id)
        monkeypatch.setattr(runner, "_image_call", image_call)
        report = runner.run_snapshot(snapshot, run_id=admitted.run_id)

        assert report.status == "candidate"
        assert (root / "state" / "artifacts" / admitted.run_id / "image" / "starts.txt").read_text(encoding="utf-8") == "1"


def test_verified_checkpoint_resumes_without_rerunning_the_agent_or_verification() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        runner = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger)
        worktree, branch = runner._worktree(  # noqa: SLF001
            admitted.run_id,
            {"path": str(repository), "base_commit": "main"},
            60,
            lambda: None,
        )
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=worktree, branch=branch)
        ledger.finish_attempt(attempt_id, AttemptOutcome.completed("done"))
        candidate_commit = __import__("subprocess").run(
            ("git", "rev-parse", "HEAD"), cwd=worktree, check=True, text=True, capture_output=True
        ).stdout.strip()
        ledger.checkpoint_candidate(admitted.run_id, attempt_id, candidate_commit)
        ledger.record_verification(admitted.run_id, _verification_evidence(attempt_id, candidate_commit))
        exploding = _ExplodingDriver()

        report = GoalRunner(root / "state", exploding, ledger=ledger, command_harness=_ExplodingVerificationHarness()).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"
        assert exploding.specs == []


def test_candidate_commit_contains_harness_changes_that_verification_saw() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        report = GoalRunner(root / "state", _WritingDriver(), ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )
        import subprocess

        candidate = subprocess.run(
            ("git", "show", f"{report.candidate_commit}:harness-output.txt"),
            cwd=report.worktree, check=True, text=True, capture_output=True,
        )

        assert report.status == "candidate"
        assert candidate.stdout == "generated by harness\n"


def test_candidate_git_write_is_bounded_and_cannot_outlive_its_runner() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        marker = root / "late-git-hook.txt"
        hook = repository / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, time\n"
            "time.sleep(2)\n"
            f"pathlib.Path({str(marker)!r}).write_text('late\\n')\n"
            "time.sleep(10)\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        __import__("subprocess").run(
            ("git", "config", "core.hooksPath", str(hook.parent)),
            cwd=repository,
            check=True,
        )
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["timeout_seconds"] = 1
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(contract))

        with pytest.raises(RuntimeError, match="candidate-git-commit exceeded"):
            GoalRunner(
                root / "state", _WritingDriver(), ledger=ledger
            ).run_snapshot(
                ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
            )
        time.sleep(2.5)

        assert not marker.exists()


def test_worktree_preparation_is_bounded_and_cannot_outlive_its_runner() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        marker = root / "late-worktree-hook.txt"
        hook = repository / ".git" / "hooks" / "post-checkout"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, time\n"
            "time.sleep(1.2)\n"
            f"pathlib.Path({str(marker)!r}).write_text('late\\n')\n"
            "time.sleep(2)\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        __import__("subprocess").run(
            ("git", "config", "core.hooksPath", str(hook.parent)),
            cwd=repository,
            check=True,
        )
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["timeout_seconds"] = 1
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(contract))

        with pytest.raises(RuntimeError, match="worktree-git-add exceeded"):
            GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger).run_snapshot(
                ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
            )
        time.sleep(1.5)

        assert not marker.exists()


def test_expired_claim_interrupts_the_old_attempt_and_keeps_the_run_discoverable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        started = datetime.now(timezone.utc)
        first = ledger.claim(admitted.run_id, owner_id="daemon-a", lease_seconds=10, now=started)
        assert first is not None
        ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test", lease=first)

        recovered = ledger.claim(
            admitted.run_id, owner_id="daemon-b", lease_seconds=10,
            now=started + timedelta(seconds=11),
        )

        assert recovered is not None
        assert recovered.generation == first.generation + 1
        assert ledger.queued_runs()[0].run_id == admitted.run_id
        assert ledger.projection(admitted.run_id).attempts[0].outcome == "interrupted"


def test_claim_rejects_an_incompatible_execution_snapshot_before_starting() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        with pytest.raises(RuntimeError, match="unsupported engine"):
            ledger.claim(
                admitted.run_id, owner_id="daemon", lease_seconds=30,
                supported_engine_versions={"other-engine"},
                supported_admission_schema_versions={5},
                supported_transition_policy_versions={"strict-v3"},
            )

        assert ledger.run(admitted.run_id).status == "queued"


def test_lease_cannot_mutate_an_attempt_from_a_different_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admission = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3")
        first = admission.admit(AdmissionRequest(contract))
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["goal"]["id"] = "other"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        second = admission.admit(AdmissionRequest(contract))
        lease = ledger.claim(first.run_id, owner_id="daemon", lease_seconds=30)
        assert lease is not None
        attempt_id = ledger.start_attempt(second.run_id, worktree=root / "worktree", branch="aiwb/other")

        with pytest.raises(RuntimeError, match="does not own"):
            ledger.record_activity(attempt_id, ActivityEvent.activity("status", "wrong run"), lease=lease)


def test_terminal_attempt_cannot_be_rewritten_by_a_late_outcome() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        attempt_id = ledger.start_attempt(admitted.run_id, worktree=root / "worktree", branch="aiwb/test")
        ledger.finish_attempt(attempt_id, AttemptOutcome.interrupted("interrupted"))

        with pytest.raises(RuntimeError, match="already terminal"):
            ledger.finish_attempt(attempt_id, AttemptOutcome.completed("late success"))

        assert ledger.projection(admitted.run_id).attempts[0].outcome == "interrupted"


def test_verification_that_modifies_the_candidate_worktree_cannot_accept_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, command_harness=_MutatingVerificationHarness()).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "failed"
        assert report.candidate_commit == ""


def test_first_verification_keeps_ignored_dependencies_created_by_the_attempt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))

        report = GoalRunner(
            root / "state",
            _IgnoredDependencyDriver(),
            ledger=ledger,
            command_harness=_DependencyCheckingVerificationHarness(),
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"


def test_candidate_checkpoint_recovery_keeps_ignored_attempt_dependencies() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)
        interrupted = GoalRunner(root / "state", _IgnoredDependencyDriver(), ledger=ledger)

        def crash_before_verification(*_args, **_kwargs):
            raise KeyboardInterrupt()

        interrupted._verify = crash_before_verification
        with pytest.raises(KeyboardInterrupt):
            interrupted.run_snapshot(snapshot, run_id=admitted.run_id)

        checkpoint = ledger.checkpoint(admitted.run_id)
        assert checkpoint.stage == "candidate"
        assert (Path(ledger.projection(admitted.run_id).worktree) / ".venv" / "dependency.txt").is_file()

        recovered = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(),
            ledger=ledger,
            command_harness=_DependencyCheckingVerificationHarness(),
        ).run_snapshot(snapshot, run_id=admitted.run_id)

        assert recovered.status == "candidate"


def test_retry_discards_verification_pollution_before_a_fresh_attempt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)
        failed = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, command_harness=_MutatingVerificationHarness()).run_snapshot(
            snapshot, run_id=admitted.run_id
        )

        ledger.retry(admitted.run_id)
        recovered = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger).run_snapshot(
            snapshot, run_id=admitted.run_id
        )

        assert failed.status == "failed"
        assert recovered.status == "candidate"
        import subprocess
        leaked = subprocess.run(
            ("git", "show", f"{recovered.candidate_commit}:verification-mutated.txt"),
            cwd=recovered.worktree, text=True, capture_output=True,
        )
        assert leaked.returncode != 0


def test_retry_discards_pollution_from_an_aborted_verification() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)

        failed = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(),
            ledger=ledger,
            command_harness=_MutatingExplodingVerificationHarness(),
        ).run_snapshot(snapshot, run_id=admitted.run_id)

        ledger.retry(admitted.run_id)
        recovered = GoalRunner(
            root / "state", FakeAgentHarnessDriver(), ledger=ledger
        ).run_snapshot(snapshot, run_id=admitted.run_id)

        assert failed.status == "failed"
        assert recovered.status == "candidate"
        import subprocess
        leaked = subprocess.run(
            ("git", "show", f"{recovered.candidate_commit}:verification-aborted.txt"),
            cwd=recovered.worktree, text=True, capture_output=True,
        )
        assert leaked.returncode != 0


def test_attempt_stops_when_its_parent_daemon_is_killed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))
        context = multiprocessing.get_context("spawn")
        parent = context.Process(
            target=_run_late_writing_attempt,
            args=(root / "state", root / "state" / "run-ledger.db", admitted.run_id),
        )
        parent.start()
        deadline = time.monotonic() + 10
        worktree = None
        while time.monotonic() < deadline:
            report = ledger.projection(admitted.run_id)
            if report.attempts and report.worktree:
                worktree = Path(report.worktree)
                break
            time.sleep(0.05)
        assert worktree is not None

        os.kill(parent.pid, signal.SIGKILL)
        parent.join(5)
        time.sleep(2.5)

        assert not (worktree / "late-driver-write.txt").exists()


def test_parent_death_escalates_past_descendants_that_ignore_sigterm() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))
        context = multiprocessing.get_context("spawn")
        parent = context.Process(
            target=_run_term_ignoring_attempt,
            args=(root / "state", root / "state" / "run-ledger.db", admitted.run_id),
        )

        parent.start()
        deadline = time.monotonic() + 10
        worktree = None
        ready = None
        while time.monotonic() < deadline:
            report = ledger.projection(admitted.run_id)
            if report.attempts and report.worktree:
                worktree = Path(report.worktree)
                ready = worktree / "term-ignoring-descendant-ready.txt"
                if ready.exists():
                    break
            time.sleep(0.05)
        assert worktree is not None
        assert ready is not None and ready.exists()

        os.kill(parent.pid, signal.SIGKILL)
        parent.join(5)
        time.sleep(2.5)

        assert not (worktree / "term-ignoring-descendant-escaped.txt").exists()


def test_parent_death_monitor_exits_when_no_worker_was_started() -> None:
    context = multiprocessing.get_context("spawn")
    child_liveness, parent_liveness = context.Pipe(duplex=False)
    worker_pid = context.Value("q", 0)
    monitor = context.Process(
        target=harness_native._monitor_parent_liveness,
        args=(child_liveness, worker_pid),
    )

    monitor.start()
    child_liveness.close()
    parent_liveness.close()
    monitor.join(2)
    if monitor.is_alive():
        monitor.kill()
        monitor.join(2)

    assert monitor.exitcode == 0


def test_delayed_worker_entry_observes_parent_death_before_external_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "escaped-worker.txt"
        context = multiprocessing.get_context("spawn")
        child_liveness, parent_liveness = context.Pipe(duplex=False)
        worker_pid = context.Value("q", 0)
        worker = context.Process(
            target=_delayed_supervised_process_entry,
            args=(child_liveness, worker_pid, marker),
        )

        worker.start()
        child_liveness.close()
        parent_liveness.close()
        worker.join(8)
        if worker.is_alive():
            worker.kill()
            worker.join(2)

        assert not marker.exists()


def test_lease_takeover_restores_candidate_before_restarting_verification() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(_contract(root, repository)))
        snapshot = ledger.execution_snapshot(admitted.snapshot_id)

        with pytest.raises(LeaseConflictError, match="lease was lost"):
            GoalRunner(
                root / "state",
                FakeAgentHarnessDriver(),
                ledger=ledger,
                command_harness=_MutatingSlowVerificationHarness(),
            ).run_snapshot(
                snapshot,
                run_id=admitted.run_id,
                lease_provider=_LeaseLostDuringVerification(ledger, admitted.run_id),
            )

        recovered = GoalRunner(
            root / "state", FakeAgentHarnessDriver(), ledger=ledger
        ).run_snapshot(snapshot, run_id=admitted.run_id)

        assert recovered.status == "candidate"
        assert not (Path(recovered.worktree) / "lease-lost-verification.txt").exists()


def test_verification_that_commits_after_checking_cannot_accept_a_different_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
            AdmissionRequest(_contract(root, repository))
        )

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, command_harness=_CommittingVerificationHarness()).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "failed"
        assert report.candidate_commit == ""


def test_credential_bearing_publish_remote_is_rejected_before_admission() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        import subprocess
        subprocess.run(("git", "remote", "add", "origin", "https://:token@example.test/repository.git"), cwd=repository, check=True)
        contract = _contract(root, repository)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved", "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {"gate": {"argv": [sys.executable, "-c", "raise SystemExit(0)"], "approved": True}}, "skills": {}},
            "harness": {"profiles": {}}, "images": {"profiles": {}},
            "publishing": {"candidate": {"approved": True, "remote": "origin", "branch_prefix": "aiwb/"}},
        }, sort_keys=False), encoding="utf-8")
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["policy"] = str(workflow)
        value["candidate"] = {"publish": True}
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="must not contain credentials"):
            Admission(SQLiteRunLedger(root / "state" / "run-ledger.db"), engine_version="test-engine", transition_policy_version="strict-v3").admit(AdmissionRequest(contract))


def test_daemon_terminalizes_a_run_with_an_unsupported_execution_snapshot() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        daemon = AgentDaemon(root / "state", FakeAgentHarnessDriver(), engine_version="daemon-engine", transition_policy_version="strict-v3")
        admitted = Admission(daemon._ledger, engine_version="snapshot-engine", transition_policy_version="strict-v3").admit(  # noqa: SLF001
            AdmissionRequest(_contract(root, repository))
        )

        daemon._execute(admitted.run_id)  # noqa: SLF001

        assert daemon._ledger.run(admitted.run_id).status == "failed"  # noqa: SLF001


def test_candidate_publication_failure_keeps_the_run_retryable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        import subprocess
        remote = root / "remote.git"
        subprocess.run(("git", "init", "--bare", str(remote)), check=True, capture_output=True)
        subprocess.run(("git", "remote", "add", "origin", str(remote)), cwd=repository, check=True)
        contract = _contract(root, repository)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        command = [sys.executable, "-c", "raise SystemExit(0)"]
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved", "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {"gate": {"argv": command, "approved": True}}, "skills": {}},
            "harness": {"profiles": {}}, "images": {"profiles": {}},
            "publishing": {"candidate": {"approved": True, "remote": "origin", "branch_prefix": "aiwb/"}},
        }, sort_keys=False), encoding="utf-8")
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["policy"] = str(workflow)
        value["candidate"] = {"publish": True}
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(AdmissionRequest(contract))

        report = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, publisher=_FailingPublisher()).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "failed"
        assert report.candidate_commit == ""


def test_preflight_displays_the_complete_frozen_agent_harness_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        contract = _contract(root, _repository(root))

        profile = preview_execution(contract).to_dict()["execution"]["agent_harness"]

        assert profile["permissions"] == ["workspace-write"]
        assert profile["capability_ceiling"] == ["git"]
        assert profile["extensions"] == ["skill:focused@1"]
        assert profile["native_configuration"] == {"mode": "test"}


def test_preflight_and_explicit_external_approval_bind_the_complete_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _draft_contract(root, repository)

        preview = preview_execution(contract)
        assert preview.approval_status == "draft"
        assert len(preview.execution_digest) == 64

        artifact = root / "execution-approval.json"
        approval = approve_execution(
            contract, approved_by="owner", artifact_path=artifact
        )
        assert approval.execution_digest == preview.execution_digest
        assert artifact.is_file()
        assert preview_execution(contract).approval_status == "approved"

        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v3",
        ).admit(AdmissionRequest(contract))
        assert admitted.run_id

        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["instructions"] = "Execute different instructions."
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        assert preview_execution(contract).approval_status == "stale"
        with pytest.raises(ValueError, match="does not match the complete execution"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v3",
            ).admit(AdmissionRequest(contract))


def test_execution_approval_artifact_must_stay_outside_the_target_repository() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _draft_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["approval"]["artifact_path"] = str(repository / "approval.json")
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="outside the target repository"):
            approve_execution(
                contract,
                approved_by="owner",
                artifact_path=repository / "approval.json",
            )


def test_goal_approve_cli_creates_the_external_execution_approval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        contract = _draft_contract(root, _repository(root))
        artifact = root / "execution-approval.json"

        assert cli_module.main(
            [
                "goal",
                "approve",
                "--contract",
                str(contract),
                "--approved-by",
                "owner",
                "--approval-artifact",
                str(artifact),
            ]
        ) == 0

        value = json.loads(capsys.readouterr().out)
        assert value["status"] == "approved"
        assert value["artifact_path"] == str(artifact.resolve())


def test_intake_reports_a_draft_contract_as_approval_required() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved",
            "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {}, "skills": {}},
            "harness": {"profiles": {}}, "images": {"profiles": {}},
        }, sort_keys=False), encoding="utf-8")
        contract = _contract(root, repository)
        Path(
            yaml.safe_load(contract.read_text(encoding="utf-8"))["approval"][
                "artifact_path"
            ]
        ).unlink()

        result = GoalIntake().inspect(repository=repository, contract_path=contract)

        assert result.readiness == "blocked"
        assert result.approval_required is True
        assert result.submission_required is False
        assert any(blocker.code == "approval" for blocker in result.blockers)


def test_intake_blocks_when_a_named_harness_extension_is_not_installed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        (repository / ".codex" / "skills" / "focused" / "SKILL.md").unlink()
        import subprocess
        subprocess.run(("git", "add", "-u"), cwd=repository, check=True)
        subprocess.run(("git", "commit", "-m", "remove skill"), cwd=repository, check=True)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir(exist_ok=True)
        workflow.write_text(yaml.safe_dump({
            "schema_version": 1, "status": "approved",
            "project": {"root": ".", "trusted": True},
            "capabilities": {"commands": {"gate": {"argv": [sys.executable, "-c", "raise SystemExit(0)"], "approved": True}}, "skills": {}},
            "harness": {"profiles": {}}, "images": {"profiles": {}},
        }, sort_keys=False), encoding="utf-8")

        result = GoalIntake().inspect(repository=repository, contract_path=contract)

        assert result.readiness == "blocked"
        assert any(blocker.code == "contract_validation" for blocker in result.blockers)


def test_preflight_and_admission_reject_a_mismatched_skill_extension_version() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["extensions"] = ["skill:focused@2"]
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="version does not match"):
            preview_execution(contract)
        with pytest.raises(ValueError, match="version does not match"):
            Admission(
                SQLiteRunLedger(root / "state" / "run-ledger.db"),
                engine_version="test-engine",
                transition_policy_version="strict-v3",
            ).admit(AdmissionRequest(contract))


def test_preflight_resolves_skill_from_the_selected_driver_install_root() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        codex_skill = repository / ".codex" / "skills" / "focused" / "SKILL.md"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        claude_skill.parent.mkdir(parents=True)
        codex_skill.rename(claude_skill)
        __import__("subprocess").run(("git", "add", "--all"), cwd=repository, check=True)
        __import__("subprocess").run(
            ("git", "commit", "-m", "install focused for claude"),
            cwd=repository,
            check=True,
        )
        contract = _draft_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["driver"] = "claude-code"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        envelope = preview_execution(contract).to_dict()

        assert envelope["execution"]["agent_harness"]["resolved_extensions"][0]["path"] == (
            ".claude/skills/focused/SKILL.md"
        )


def test_preflight_rejects_a_non_skill_extension_without_a_callable_entrypoint() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        descriptor = (
            repository
            / ".ai-workbench"
            / "extensions"
            / "mcp"
            / "focused-mcp.yaml"
        )
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            yaml.safe_dump(
                {
                    "kind": "mcp",
                    "name": "focused-mcp",
                    "version": 1,
                    "driver": "codex",
                    "configuration": {"entrypoint": "missing-mcp-server"},
                }
            ),
            encoding="utf-8",
        )
        __import__("subprocess").run(
            ("git", "add", str(descriptor)), cwd=repository, check=True
        )
        __import__("subprocess").run(
            ("git", "commit", "-m", "declare unavailable mcp"),
            cwd=repository,
            check=True,
        )
        contract = _draft_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["extensions"].append("mcp:focused-mcp@1")
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="callable entrypoint"):
            preview_execution(contract)


def test_preflight_rejects_a_non_skill_extension_registered_for_another_driver() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        executable = repository / ".ai-workbench" / "extensions" / "bin" / "focused-mcp"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        descriptor = (
            repository / ".ai-workbench" / "extensions" / "mcp" / "focused-mcp.yaml"
        )
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            yaml.safe_dump(
                {
                    "kind": "mcp",
                    "name": "focused-mcp",
                    "version": 1,
                    "driver": "claude-code",
                    "configuration": {
                        "entrypoint": ".ai-workbench/extensions/bin/focused-mcp"
                    },
                }
            ),
            encoding="utf-8",
        )
        __import__("subprocess").run(
            ("git", "add", ".ai-workbench/extensions"), cwd=repository, check=True
        )
        __import__("subprocess").run(
            ("git", "commit", "-m", "install extension for another driver"),
            cwd=repository,
            check=True,
        )
        contract = _draft_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["extensions"].append("mcp:focused-mcp@1")
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="not registered for Agent Harness Driver codex"):
            preview_execution(contract)


def test_preflight_resolves_named_harness_extensions_at_the_frozen_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        identities = []
        for kind in ("mcp", "plugin", "hook", "command"):
            name = f"focused-{kind}"
            identity = f"{kind}:{name}@1"
            identities.append(identity)
            entrypoint = f".ai-workbench/extensions/bin/{name}"
            executable = repository / entrypoint
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            descriptor = repository / ".ai-workbench" / "extensions" / kind / f"{name}.yaml"
            descriptor.parent.mkdir(parents=True, exist_ok=True)
            descriptor.write_text(
                yaml.safe_dump(
                    {
                        "kind": kind,
                        "name": name,
                        "version": 1,
                        "driver": "codex",
                        "configuration": {"entrypoint": entrypoint},
                    }
                ),
                encoding="utf-8",
            )
        import subprocess
        subprocess.run(("git", "add", ".ai-workbench/extensions"), cwd=repository, check=True)
        subprocess.run(("git", "commit", "-m", "install harness extensions"), cwd=repository, check=True)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["agent_harness"]["extensions"].extend(identities)
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)

        envelope = preview_execution(contract).to_dict()
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger, engine_version="test-engine", transition_policy_version="strict-v3"
        ).admit(AdmissionRequest(contract))
        report = GoalRunner(
            root / "state", _ResolvedExtensionDriver(), ledger=ledger
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert [
            item["identity"]
            for item in envelope["execution"]["agent_harness"][
                "resolved_extensions"
            ]
        ] == [
            "skill:focused@1", *identities
        ]
        assert envelope["execution"]["agent_harness"]["resolved_extensions"][1][
            "descriptor"
        ] == {
            "configuration": {
                "entrypoint": ".ai-workbench/extensions/bin/focused-mcp"
            },
            "kind": "mcp",
            "name": "focused-mcp",
            "version": 1,
            "driver": "codex",
        }
        assert [
            item["identity"]
            for item in ledger.execution_snapshot(admitted.snapshot_id).manifest[
                "agent_harness"
            ][
                "resolved_extensions"
            ]
        ] == ["skill:focused@1", *identities]
        assert (
            Path(report.worktree) / "resolved-extension.txt"
        ).read_text(encoding="utf-8") == ".ai-workbench/extensions/bin/focused-mcp\n"

        descriptor = (
            repository
            / ".ai-workbench"
            / "extensions"
            / "mcp"
            / "focused-mcp.yaml"
        )
        descriptor.write_text(
            descriptor.read_text(encoding="utf-8").replace(
                ".ai-workbench/extensions/bin/focused-mcp",
                ".ai-workbench/extensions/bin/changed-mcp",
            ),
            encoding="utf-8",
        )
        subprocess.run(("git", "add", str(descriptor)), cwd=repository, check=True)
        subprocess.run(("git", "commit", "-m", "change extension"), cwd=repository, check=True)

        with pytest.raises(ValueError, match="callable entrypoint"):
            preview_execution(contract)


def test_admission_rejects_literal_secret_before_storing_contract_source() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["metadata"] = {"api_token": "do-not-store-this"}
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")

        with pytest.raises(ValueError, match="literal secret"):
            Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3").admit(
                AdmissionRequest(contract)
            )

        assert ledger.queued_runs() == ()


def test_admission_rejects_literal_secret_reference_schemes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["required_secrets"] = ["literal:do-not-store"]
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError, match="required_secrets"):
            Admission(SQLiteRunLedger(root / "state" / "run-ledger.db"), engine_version="test-engine", transition_policy_version="strict-v3").admit(
                AdmissionRequest(contract)
            )


def test_activity_events_are_bounded_to_the_declared_trace_vocabulary() -> None:
    with pytest.raises(ValueError, match="kind"):
        ActivityEvent.activity("unknown-internal-role", "details")
    with pytest.raises(ValueError, match="session_id"):
        ActivityEvent("status", "details", session_id="s" * 129)


def test_goal_run_returns_after_the_new_candidate_terminal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def submit(self, contract):
            return SimpleNamespace(run_id="run-1", status="queued")

        def status(self, run_id):
            return SimpleNamespace(run_id=run_id, status="candidate")

        def report(self, run_id):
            return SimpleNamespace(to_dict=lambda: {"run_id": run_id, "status": "candidate"})

    monkeypatch.setattr(cli_module, "DaemonClient", lambda _: Client())
    options = SimpleNamespace(goal_command="run", contract=Path("contract.yaml"), state_dir=Path("state"), socket=None)

    assert cli_module._run_goal(options) == 0


def test_evidence_is_scoped_to_the_run_that_references_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admission = Admission(ledger, engine_version="test-engine", transition_policy_version="strict-v3")
        first = admission.admit(AdmissionRequest(contract))
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["goal"]["id"] = "other"
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        second = admission.admit(AdmissionRequest(contract))
        runner = GoalRunner(root / "state", FakeAgentHarnessDriver(), ledger=ledger, command_harness=_LargeOutputHarness())

        report = runner.run_snapshot(ledger.execution_snapshot(first.snapshot_id), run_id=first.run_id)
        reference = report.evidence[0].stdout_ref
        assert reference is not None

        with pytest.raises(KeyError, match="not referenced"):
            runner.evidence(second.run_id, reference.artifact_id)


def test_large_verification_output_does_not_deadlock_result_transport() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _repository(root)
        contract = _contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["verification"]["timeout_seconds"] = 3
        contract.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        _reapprove_contract(contract)
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v3",
        ).admit(AdmissionRequest(contract))

        report = GoalRunner(
            root / "state",
            FakeAgentHarnessDriver(),
            ledger=ledger,
            command_harness=_VeryLargeOutputHarness(),
        ).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id), run_id=admitted.run_id
        )

        assert report.status == "candidate"
        assert report.evidence[0].stdout_ref is not None


def test_process_result_storage_has_no_named_raw_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setattr(harness_native.tempfile, "tempdir", directory)
        result = harness_native._ProcessResultSpool.create()
        try:
            result.put(("value", "raw harness output"))

            assert list(Path(directory).iterdir()) == []
            assert result.get() == ("value", "raw harness output")
        finally:
            result.close()


def _repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    import subprocess

    for command in (
        ("git", "init", "-b", "main"),
        ("git", "config", "user.name", "AI Workbench Test"),
        ("git", "config", "user.email", "aiwb@example.test"),
    ):
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    (repository / ".gitignore").write_text(
        "verification-aborted.txt\n.venv/\n", encoding="utf-8"
    )
    skill = repository / ".codex" / "skills" / "focused" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: focused\ndescription: Focus this test attempt.\nversion: 1\n---\n\n# Focused\n",
        encoding="utf-8",
    )
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    subprocess.run(("git", "commit", "-m", "fixture"), cwd=repository, check=True)
    return repository


class _RecordingHarness:
    def __init__(self) -> None:
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        artifact = request.artifact_dir / "verification.log"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("verified\n", encoding="utf-8")
        return HarnessExecution(0, "verified\n", "", "http://unused", (str(artifact),), "local")


class _LargeOutputHarness:
    def execute(self, request):
        return HarnessExecution(0, "x" * 5000, "", "", (), "local")


class _VeryLargeOutputHarness:
    def execute(self, request):
        return HarnessExecution(0, "x" * 2_000_000, "", "", (), "local")


class _MutatingVerificationHarness:
    def execute(self, request):
        (request.cwd / "verification-mutated.txt").write_text("unexpected\n", encoding="utf-8")
        return HarnessExecution(0, "verified\n", "", "", (), "local")


class _DependencyCheckingVerificationHarness:
    def execute(self, request):
        dependency = request.cwd / ".venv" / "dependency.txt"
        return HarnessExecution(
            0 if dependency.read_text(encoding="utf-8") == "installed\n" else 1,
            "verified\n",
            "",
            "",
            (),
            "local",
        )


class _MutatingExplodingVerificationHarness:
    def execute(self, request):
        (request.cwd / "verification-aborted.txt").write_text(
            "unexpected\n", encoding="utf-8"
        )
        raise RuntimeError("verification failed after mutating the worktree")


class _MutatingSlowVerificationHarness:
    def execute(self, request):
        (request.cwd / "lease-lost-verification.txt").write_text(
            "unexpected\n", encoding="utf-8"
        )
        time.sleep(10)
        return HarnessExecution(0, "verified\n", "", "", (), "local")


class _CommittingVerificationHarness:
    def execute(self, request):
        import subprocess
        (request.cwd / "verification-committed.txt").write_text("unexpected\n", encoding="utf-8")
        subprocess.run(("git", "add", "verification-committed.txt"), cwd=request.cwd, check=True)
        subprocess.run(("git", "commit", "-m", "verification mutation"), cwd=request.cwd, check=True)
        return HarnessExecution(0, "verified\n", "", "", (), "local")


class _ExplodingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        raise RuntimeError("driver disconnected")


class _BlockingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        self.specs.append(attempt_spec)
        time.sleep(10)
        return AttemptOutcome.completed("late completion")


class _FloodingActivityDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        while True:
            event_sink(ActivityEvent.activity("activity", "bounded flood"))


class _MaximumActivityDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        for _ in range(256):
            event_sink(ActivityEvent.activity("activity", "within budget"))
        return AttemptOutcome.completed("bounded completion")


class _OverflowingActivityDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        for _ in range(257):
            event_sink(ActivityEvent.activity("activity", "over budget"))
        return AttemptOutcome.completed("must not be accepted")


class _LateWritingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        time.sleep(2)
        (attempt_spec.worktree / "late-driver-write.txt").write_text("late\n", encoding="utf-8")
        return AttemptOutcome.completed("late completion")


class _BackgroundWritingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        import subprocess
        subprocess.Popen(
            (
                sys.executable,
                "-c",
                "import pathlib,time; time.sleep(2); "
                f"pathlib.Path({str(attempt_spec.worktree / 'background-driver-write.txt')!r}).write_text('late\\n')",
            )
        )
        return AttemptOutcome.completed("driver returned before its descendant")


class _TermIgnoringDescendantDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        import subprocess

        ready = attempt_spec.worktree / "term-ignoring-descendant-ready.txt"
        escaped = attempt_spec.worktree / "term-ignoring-descendant-escaped.txt"
        subprocess.Popen(
            (
                sys.executable,
                "-c",
                "import pathlib,signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(ready)!r}).write_text('ready\\n'); "
                "time.sleep(2); "
                f"pathlib.Path({str(escaped)!r}).write_text('escaped\\n')",
            )
        )
        time.sleep(10)
        return AttemptOutcome.completed("descendant escaped supervision")


class _ActivityThenLateWritingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        self.validate(attempt_spec.profile)
        event_sink(ActivityEvent.activity("activity", "lease authority check"))
        time.sleep(0.5)
        (attempt_spec.worktree / "late-lease-write.txt").write_text("late\n", encoding="utf-8")
        return AttemptOutcome.completed("late completion")


class _LeaseLostAfterAttemptStart:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls > 1:
            raise LeaseConflictError("lease was lost")
        return None


class _LeaseLostDuringVerification:
    def __init__(self, ledger: SQLiteRunLedger, run_id: str) -> None:
        self.ledger = ledger
        self.run_id = run_id
        self.verification_calls = 0

    def __call__(self):
        if self.ledger.checkpoint(self.run_id).stage == "candidate":
            self.verification_calls += 1
            if self.verification_calls > 20:
                raise LeaseConflictError("lease was lost during verification")
        return None


class _ExplodingVerificationHarness:
    def execute(self, request):
        raise AssertionError("verification should resume from the durable checkpoint")


class _WritingDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        outcome = super().execute(attempt_spec, event_sink)
        (attempt_spec.worktree / "harness-output.txt").write_text(
            "generated by harness\n", encoding="utf-8"
        )
        return outcome


class _IgnoredDependencyDriver(FakeAgentHarnessDriver):
    def execute(self, attempt_spec, event_sink):
        outcome = super().execute(attempt_spec, event_sink)
        dependency = attempt_spec.worktree / ".venv" / "dependency.txt"
        dependency.parent.mkdir(parents=True, exist_ok=True)
        dependency.write_text("installed\n", encoding="utf-8")
        return outcome


class _ResolvedExtensionDriver:
    def validate(self, profile):
        if not profile.resolved_extensions:
            raise ValueError("extensions were not resolved")

    def execute(self, attempt_spec, event_sink):
        entrypoint = attempt_spec.profile.resolved_extensions[1]["descriptor"][
            "configuration"
        ]["entrypoint"]
        (attempt_spec.worktree / "resolved-extension.txt").write_text(
            f"{entrypoint}\n", encoding="utf-8"
        )
        return AttemptOutcome.completed("used frozen extension configuration")


def _run_late_writing_attempt(state_dir: Path, database: Path, run_id: str) -> None:
    ledger = SQLiteRunLedger(database)
    GoalRunner(state_dir, _LateWritingDriver(), ledger=ledger).run_snapshot(
        ledger.execution_snapshot(ledger.run(run_id).snapshot_id), run_id=run_id
    )


def _run_term_ignoring_attempt(state_dir: Path, database: Path, run_id: str) -> None:
    ledger = SQLiteRunLedger(database)
    GoalRunner(
        state_dir, _TermIgnoringDescendantDriver(), ledger=ledger
    ).run_snapshot(
        ledger.execution_snapshot(ledger.run(run_id).snapshot_id), run_id=run_id
    )


def _run_flooding_attempt(
    state_dir: Path, database: Path, run_id: str, report_path: Path
) -> None:
    ledger = SQLiteRunLedger(database)
    report = GoalRunner(state_dir, _FloodingActivityDriver(), ledger=ledger).run_snapshot(
        ledger.execution_snapshot(ledger.run(run_id).snapshot_id), run_id=run_id
    )
    report_path.write_text(report.status + "\n", encoding="utf-8")


def _delayed_supervised_process_entry(
    parent_liveness: object, worker_pid: object, marker: Path
) -> None:
    time.sleep(5.5)
    harness_native._supervised_process_entry(
        _write_escaped_worker_marker,
        (marker,),
        worker_pid,
        parent_liveness,
    )


def _write_escaped_worker_marker(marker: Path) -> None:
    marker.write_text("escaped\n", encoding="utf-8")


class _RecordingImageBuilder:
    def __init__(self) -> None:
        self.operations = []

    def start(self, request):
        self.operations.append("start")
        self.request = request
        return "operation-1"

    def status(self, request, operation_id):
        self.operations.append("status")
        return "succeeded"

    def result(self, request, operation_id):
        self.operations.append("result")
        artifact = request.artifact_dir / "image.log"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("image built\n", encoding="utf-8")
        return ImageBuildResult("sha256:" + "a" * 64, (str(artifact),))


class _FileCountingImageBuilder(_RecordingImageBuilder):
    def start(self, request):
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        marker = request.artifact_dir / "starts.txt"
        starts = int(marker.read_text(encoding="utf-8")) if marker.exists() else 0
        marker.write_text(str(starts + 1), encoding="utf-8")
        return "operation-1"


class _RecordingPublisher:
    def __init__(self) -> None:
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        return CandidatePublishResult(request.profile.remote, f"refs/heads/{request.branch}", request.commit)


class _FailingPublisher:
    def publish(self, request):
        raise RuntimeError("remote unavailable")


def _verification_evidence(attempt_id: str, candidate_commit: str) -> VerificationEvidence:
    return VerificationEvidence(
        command=("verify",), returncode=0, stdout="ok", stderr="",
        duration_seconds=0.0, attempt_id=attempt_id,
        candidate_commit=candidate_commit,
    )


def _contract(root: Path, repository: Path) -> Path:
    path = _draft_contract(root, repository)
    approve_execution(
        path,
        approved_by="owner",
        artifact_path=root / "execution-approval.json",
        approved_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    return path


def _draft_contract(root: Path, repository: Path) -> Path:
    path = root / "contract.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 5,
                "goal": {
                    "id": "greeting",
                    "title": "Add greeting",
                    "requirement": "Add the agreed greeting behavior.",
                    "acceptance": [{"id": "AC-1", "statement": "Tests pass."}],
                },
                "approval": {
                    "artifact_path": str(root / "execution-approval.json"),
                },
                "instructions": "Implement the agreed greeting behavior.",
                "agent_harness": {
                    "driver": "codex",
                    "model": "gpt-test",
                    "effort": "high",
                    "permissions": ["workspace-write"],
                    "capability_ceiling": ["git"],
                    "extensions": ["skill:focused@1"],
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
    return path


def _reapprove_contract(contract: Path) -> None:
    value = yaml.safe_load(contract.read_text(encoding="utf-8"))
    artifact = Path(value["approval"]["artifact_path"])
    artifact.unlink()
    approve_execution(
        contract,
        approved_by="owner",
        artifact_path=artifact,
        approved_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
