from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    ActivityEvent,
    Admission,
    AdmissionRequest,
    AgentHarnessProfile,
    AttemptOutcome,
    AttemptSpec,
    CodexDriver,
    GoalRunner,
    SQLiteRunLedger,
)
from aiwb.runner import approve_execution  # noqa: E402


_FAKE_CODEX_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys
import time

scenario = os.environ.get("AIWB_FAKE_CODEX_SCENARIO", "success")


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()


emit({"type": "thread.started", "thread_id": "thread-fake-1"})
if scenario == "invalid_output":
    sys.stdout.write("this is not json\\n")
    sys.stdout.flush()
    sys.exit(1)
emit({"type": "turn.started"})
if scenario == "quota":
    message = "You've hit your usage limit."
    emit({"type": "error", "message": message})
    emit({"type": "turn.failed", "error": {"message": message}})
    sys.exit(1)
if scenario == "budget":
    emit({"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 600}})
    time.sleep(30)
    sys.exit(0)
emit({"type": "item.completed", "item": {"id": "item_0", "type": "command_execution",
      "command": "echo greeting", "aggregated_output": "greeting\\n", "exit_code": 0}})
if scenario == "stream":
    time.sleep(0.6)
emit({"type": "item.completed", "item": {"id": "item_1", "type": "file_change",
      "changes": [{"path": "greeting.txt", "kind": "add"}]}})
emit({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message",
      "text": "Implemented the greeting."}})
emit({"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 30}})
sys.exit(0)
"""


def _fake_codex(root: Path) -> Path:
    path = root / "fake-codex"
    path.write_text(_FAKE_CODEX_SCRIPT, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _profile(**overrides: object) -> AgentHarnessProfile:
    values = {
        "driver": "codex",
        "model": "gpt-test",
        "effort": "high",
        "permissions": ("workspace-write",),
        "capability_ceiling": ("git",),
        "extensions": (),
        "allowed_paths": (".",),
        "tools": ("shell",),
        "input_artifact": "contract.yaml",
        "output_schema": "attempt-outcome/v1",
        "timeout_seconds": 60,
        "max_attempts": 1,
        "resource_limits": {"tokens": 1000},
        "native_configuration": {"mode": "autonomous"},
        "trace_coverage": ("activity",),
    }
    values.update(overrides)
    return AgentHarnessProfile(**values)


def _spec(root: Path, profile: AgentHarnessProfile) -> AttemptSpec:
    worktree = root / "worktree"
    worktree.mkdir(exist_ok=True)
    return AttemptSpec(
        run_id="run-1",
        attempt_id="attempt-1",
        worktree=worktree,
        instructions="Implement the agreed greeting behavior.",
        profile=profile,
    )


def _execute(driver: CodexDriver, root: Path, profile: AgentHarnessProfile):
    events = []
    outcome = driver.execute(_spec(root, profile), events.append)
    return outcome, events


def test_validate_rejects_unsupported_surfaces() -> None:
    with tempfile.TemporaryDirectory() as directory:
        driver = CodexDriver(str(_fake_codex(Path(directory))))
        driver.validate(_profile())
        unsupported = [
            {"driver": "claude-code"},
            {"permissions": ("network",)},
            {"permissions": ("workspace-write", "read-only")},
            {"effort": "extreme"},
            {"capability_ceiling": ("git", "kubernetes")},
            {"tools": ("shell", "browser")},
            {"allowed_paths": (".", "/tmp")},
            {"input_artifact": "other.yaml"},
            {"output_schema": "attempt-outcome/v0"},
            {"resource_limits": {"cpu": 2}},
            {"resource_limits": {"tokens": 0}},
            {"native_configuration": {"mode": "interactive"}},
            {"extensions": ("mcp:search@1",)},
            {"extensions": ("skill:focused@1",)},
            {"trace_coverage": ("chain-of-thought",)},
        ]
        for override in unsupported:
            with pytest.raises(ValueError):
                driver.validate(_profile(**override))
        missing = CodexDriver("aiwb-binary-that-does-not-exist")
        with pytest.raises(ValueError):
            missing.validate(_profile())


def test_completed_attempt_streams_events_before_codex_exits() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        driver = CodexDriver(str(_fake_codex(root)))
        events = []
        first_event_at = None
        started = time.monotonic()

        def sink(event: ActivityEvent) -> None:
            nonlocal first_event_at
            if first_event_at is None:
                first_event_at = time.monotonic()
            events.append(event)

        original = os.environ.get("AIWB_FAKE_CODEX_SCENARIO")
        os.environ["AIWB_FAKE_CODEX_SCENARIO"] = "stream"
        try:
            outcome = driver.execute(_spec(root, _profile()), sink)
        finally:
            if original is None:
                del os.environ["AIWB_FAKE_CODEX_SCENARIO"]
            else:
                os.environ["AIWB_FAKE_CODEX_SCENARIO"] = original

        returned_at = time.monotonic()
        assert outcome.status == "completed"
        assert outcome.session_id == "thread-fake-1"
        assert outcome.summary == "Implemented the greeting."
        assert first_event_at is not None
        assert returned_at - first_event_at >= 0.5
        kinds = [event.kind for event in events]
        assert "session" in kinds
        assert "lifecycle" in kinds
        assert "tool" in kinds
        assert "edit" in kinds
        assert "activity" in kinds
        assert "usage" in kinds
        assert kinds[-1] == "terminal"
        usage = next(event for event in events if event.kind == "usage")
        assert usage.usage_tokens == 150
        assert all(event.session_id == "thread-fake-1" for event in events[1:])


def test_quota_failure_is_classified_as_a_typed_outcome() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        driver = CodexDriver(str(_fake_codex(root)))
        original = os.environ.get("AIWB_FAKE_CODEX_SCENARIO")
        os.environ["AIWB_FAKE_CODEX_SCENARIO"] = "quota"
        try:
            outcome, events = _execute(driver, root, _profile())
        finally:
            if original is None:
                del os.environ["AIWB_FAKE_CODEX_SCENARIO"]
            else:
                os.environ["AIWB_FAKE_CODEX_SCENARIO"] = original
        assert outcome.status == "failed"
        assert outcome.summary.startswith("Codex Attempt failed: quota exhausted")
        assert outcome.session_id == "thread-fake-1"
        assert events[-1].kind == "terminal"


def test_invalid_output_is_classified_as_a_typed_outcome() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        driver = CodexDriver(str(_fake_codex(root)))
        original = os.environ.get("AIWB_FAKE_CODEX_SCENARIO")
        os.environ["AIWB_FAKE_CODEX_SCENARIO"] = "invalid_output"
        try:
            outcome, events = _execute(driver, root, _profile())
        finally:
            if original is None:
                del os.environ["AIWB_FAKE_CODEX_SCENARIO"]
            else:
                os.environ["AIWB_FAKE_CODEX_SCENARIO"] = original
        assert outcome.status == "failed"
        assert outcome.summary == "Codex Attempt failed: invalid output"


def test_token_budget_terminates_owned_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        driver = CodexDriver(str(_fake_codex(root)))
        original = os.environ.get("AIWB_FAKE_CODEX_SCENARIO")
        os.environ["AIWB_FAKE_CODEX_SCENARIO"] = "budget"
        started = time.monotonic()
        try:
            outcome, _events = _execute(driver, root, _profile())
        finally:
            if original is None:
                del os.environ["AIWB_FAKE_CODEX_SCENARIO"]
            else:
                os.environ["AIWB_FAKE_CODEX_SCENARIO"] = original
        assert time.monotonic() - started < 20
        assert outcome.status == "failed"
        assert outcome.summary == "Codex Attempt failed: token budget exhausted"


def test_codex_driver_attempt_flows_through_admission_and_goal_runner() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        for command in (
            ("git", "init", "-b", "main"),
            ("git", "config", "user.name", "AI Workbench Test"),
            ("git", "config", "user.email", "aiwb@example.test"),
        ):
            subprocess.run(command, cwd=repository, check=True, capture_output=True)
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        skill = repository / ".codex" / "skills" / "focused" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: focused\ndescription: Focus this test attempt.\nversion: 1\n---\n\n# Focused\n",
            encoding="utf-8",
        )
        subprocess.run(("git", "add", "."), cwd=repository, check=True)
        subprocess.run(("git", "commit", "-m", "fixture"), cwd=repository, check=True)
        contract = root / "contract.yaml"
        contract.write_text(
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
                        "max_attempts": 1,
                        "resource_limits": {"tokens": 1000},
                        "native_configuration": {"mode": "autonomous"},
                        "trace_coverage": [
                            "activity",
                            "extension",
                            "lifecycle",
                            "session",
                            "terminal",
                            "tool",
                            "usage",
                        ],
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
        driver = CodexDriver(str(_fake_codex(root)))

        report = GoalRunner(root / "state", driver, ledger=ledger).run_snapshot(
            ledger.execution_snapshot(admitted.snapshot_id),
            run_id=admitted.run_id,
        )

        assert report.status == "candidate"
        assert len(report.attempts) == 1
        assert report.attempts[0].outcome == "completed"
        assert report.attempts[0].session_id == "thread-fake-1"
        kinds = {event.kind for event in report.activity}
        assert {"session", "lifecycle", "tool", "edit", "activity", "usage", "terminal", "extension"} <= kinds
        assert len(report.evidence) == 1
