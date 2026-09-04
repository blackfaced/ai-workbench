from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    Admission,
    AdmissionRequest,
    AdmissionError,
    SQLiteRunLedger,
    prepare_proposal,
)
from aiwb import cli as cli_module  # noqa: E402
from aiwb.runner import approve_execution, preview_execution  # noqa: E402


_PROFILE = {
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
    "max_attempts": 1,
    "resource_limits": {"tokens": 1000},
    "native_configuration": {"mode": "autonomous"},
    "trace_coverage": ["activity"],
}

_TEST_COMMAND = [sys.executable, "-c", "raise SystemExit(0)"]


def _project(root: Path) -> Path:
    repository = root / "project"
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
    ai_dir = repository / ".ai-workbench"
    ai_dir.mkdir()
    (ai_dir / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": ".", "trusted": True},
                "capabilities": {
                    "commands": {
                        "test": {"argv": _TEST_COMMAND, "approved": True},
                        "lint": {
                            "argv": [sys.executable, "-c", "pass"],
                            "approved": True,
                        },
                    },
                    "skills": {},
                },
                "harness": {"profiles": {}},
                "images": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return repository


def _agent_harness(repository: Path, **profile_overrides: object) -> None:
    profile = dict(_PROFILE)
    profile.update(profile_overrides)
    (repository / ".ai-workbench" / "agent-harness.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "profile_digest": "0" * 64,
                "agent_harness": profile,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _prepare(root: Path, repository: Path, **overrides: object):
    arguments = {
        "goal_id": "overnight-1",
        "title": "Overnight task",
        "requirement": "Implement the agreed behavior.",
        "acceptance": ("AC-1: Verification passes.",),
        "instructions": "Implement the agreed behavior.",
        "command_name": "test",
        "approval_artifact": root / "approvals" / "overnight-1.json",
    }
    arguments.update(overrides)
    return prepare_proposal(repository, **arguments)


def test_proposal_is_hash_stable_and_validated_like_admission() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _project(root)
        _agent_harness(repository)
        proposal = _prepare(root, repository)
        assert proposal.approval_status == "draft"
        assert proposal.goal_id == "overnight-1"
        contract = Path(proposal.contract_path)
        assert contract.is_file()
        assert contract.parent == repository.resolve() / ".ai-workbench" / "proposals"
        envelope = preview_execution(contract)
        assert envelope.execution_digest == proposal.execution_digest
        again = _prepare(
            root, repository, output_path=root / "elsewhere.contract.yaml"
        )
        assert again.execution_digest == proposal.execution_digest


def test_proposal_fails_closed_on_missing_setup_profile_and_unapproved_command() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _project(root)
        with pytest.raises(ValueError, match="agent-harness.yaml"):
            _prepare(root, repository)
        _agent_harness(repository)
        with pytest.raises(ValueError, match="not a declared project capability"):
            _prepare(root, repository, command_name="unknown")
        with pytest.raises(ValueError, match="acceptance"):
            _prepare(root, repository, acceptance=())
        with pytest.raises(ValueError, match="acceptance"):
            _prepare(root, repository, acceptance=("no separator",))
        with pytest.raises(ValueError, match="instructions"):
            _prepare(root, repository, instructions="  ")
        with pytest.raises(ValueError, match="outside the target repository"):
            _prepare(
                root,
                repository,
                approval_artifact=repository / "inside.json",
            )
        _prepare(root, repository)
        with pytest.raises(ValueError, match="already exists"):
            _prepare(root, repository)


def test_changed_inputs_produce_a_new_digest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _project(root)
        _agent_harness(repository)
        base = _prepare(root, repository)
        variants = (
            {"instructions": "Implement the behavior differently."},
            {"command_name": "lint"},
        )
        for index, override in enumerate(variants):
            changed = _prepare(
                root,
                repository,
                output_path=root / f"variant-{index}.contract.yaml",
                approval_artifact=root / "approvals" / f"variant-{index}.json",
                **override,
            )
            assert changed.execution_digest != base.execution_digest
        _agent_harness(repository, model="gpt-other")
        changed = _prepare(
            root,
            repository,
            output_path=root / "variant-model.contract.yaml",
            approval_artifact=root / "approvals" / "variant-model.json",
        )
        assert changed.execution_digest != base.execution_digest


def test_duplicate_submission_of_one_approved_digest_creates_no_duplicate_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _project(root)
        _agent_harness(repository)
        proposal = _prepare(root, repository)
        approve_execution(
            Path(proposal.contract_path),
            approved_by="owner",
            artifact_path=Path(proposal.approval_artifact),
            approved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        ledger = SQLiteRunLedger(root / "state" / "run-ledger.db")
        admission = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v2",
        )
        key = proposal.execution_digest
        first = admission.admit(
            AdmissionRequest(Path(proposal.contract_path), idempotency_key=key)
        )
        second = admission.admit(
            AdmissionRequest(Path(proposal.contract_path), idempotency_key=key)
        )
        assert second.run_id == first.run_id
        assert len(ledger.projection(first.run_id).attempts) == 0
        assert [run.run_id for run in ledger.queued_runs()] == [first.run_id]

        changed = _prepare(
            root,
            repository,
            output_path=root / "changed.contract.yaml",
            approval_artifact=root / "approvals" / "changed.json",
            instructions="Implement something else.",
        )
        approve_execution(
            Path(changed.contract_path),
            approved_by="owner",
            artifact_path=Path(changed.approval_artifact),
            approved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        with pytest.raises(AdmissionError, match="idempotency key"):
            admission.admit(
                AdmissionRequest(Path(changed.contract_path), idempotency_key=key)
            )


def test_goal_propose_cli_displays_the_decision_package(capsys) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _project(root)
        _agent_harness(repository)
        exit_code = cli_module.main(
            [
                "goal", "propose",
                "--repo", str(repository),
                "--goal-id", "overnight-1",
                "--title", "Overnight task",
                "--requirement", "Implement the agreed behavior.",
                "--acceptance", "AC-1: Verification passes.",
                "--instructions", "Implement the agreed behavior.",
                "--command-name", "test",
                "--approval-artifact", str(root / "approvals" / "overnight-1.json"),
            ]
        )
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        proposal = output["proposal"]
        assert proposal["approval_status"] == "draft"
        assert len(proposal["execution_digest"]) == 64
        approve_action, submit_action = output["next_actions"]
        assert proposal["contract_path"] in approve_action
        assert proposal["approval_artifact"] in approve_action
        assert f"--idempotency-key {proposal['execution_digest']}" in submit_action
