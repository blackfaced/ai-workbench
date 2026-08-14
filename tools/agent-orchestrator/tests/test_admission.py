from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    Admission,
    AdmissionError,
    AdmissionRequest,
    ExecutionManifest,
    ExecutionSnapshot,
    RunLedger,
    SQLiteRunLedger,
    preview_execution,
)


def test_approved_contract_is_admitted_as_an_immutable_queued_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        base_commit = _git(repository, "rev-parse", "main").stdout.strip()
        ledger = SQLiteRunLedger(root / "state.db")

        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v1",
        ).admit(AdmissionRequest(contract_path=contract))

        snapshot = ledger.execution_snapshot(admitted.snapshot_id)
        run = ledger.run(admitted.run_id)
        assert snapshot.source == contract.read_bytes()
        assert snapshot.manifest["repository"] == {
            "path": str(repository.resolve()),
            "base_ref": "main",
            "base_commit": base_commit,
        }
        assert snapshot.manifest["goal"]["id"] == "admission-goal"
        assert snapshot.manifest["agent"] == {
            "provider": "codex",
            "model": "gpt-test",
        }
        assert snapshot.manifest["versions"] == {
            "admission_schema": 1,
            "engine": "test-engine",
            "transition_policy": "strict-v1",
        }
        assert admitted.status == "queued"
        assert run.run_id == admitted.run_id
        assert run.snapshot_id == admitted.snapshot_id
        assert run.goal_id == "admission-goal"
        assert run.status == "queued"


def test_preflight_remains_read_only_for_the_run_ledger() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["approval"] = {"status": "draft"}
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        envelope = preview_execution(contract)

        assert envelope.approval_status == "draft"
        assert ledger.execution_snapshots() == ()
        assert ledger.queued_runs() == ()


def test_unapproved_contract_is_rejected_without_a_queued_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["approval"] = {"status": "draft"}
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="approved before execution"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.queued_runs() == ()


def test_admission_uses_one_contract_read_for_source_and_manifest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        approved_source = contract.read_bytes()
        replacement = yaml.safe_load(approved_source)
        replacement["goal"]["id"] = "replacement-goal"
        ledger = SQLiteRunLedger(root / "state.db")

        def read_then_replace(path: Path) -> bytes:
            source = path.read_bytes()
            path.write_text(
                yaml.safe_dump(replacement, sort_keys=False),
                encoding="utf-8",
            )
            return source

        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v1",
            contract_reader=read_then_replace,
        ).admit(AdmissionRequest(contract_path=contract))

        snapshot = ledger.execution_snapshot(admitted.snapshot_id)
        assert snapshot.source == approved_source
        assert snapshot.manifest["goal"]["id"] == "admission-goal"
        assert admitted.goal_id == "admission-goal"


def test_secret_environment_values_are_rejected_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        secret = "literal-secret-that-must-not-be-stored"
        monkeypatch.setenv("AIWB_TEST_API_TOKEN", secret)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["metadata"] = {"diagnostic": secret}
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="secret material"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.queued_runs() == ()


def test_required_secret_references_are_frozen_without_resolving_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["required_secrets"] = ["env:AIWB_TEST_API_TOKEN"]
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")
        admission = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v1",
        )

        monkeypatch.setenv("AIWB_TEST_API_TOKEN", "first-secret-value")
        first = admission.admit(AdmissionRequest(contract_path=contract))
        monkeypatch.setenv("AIWB_TEST_API_TOKEN", "second-secret-value")
        second = admission.admit(AdmissionRequest(contract_path=contract))

        snapshot = ledger.execution_snapshot(first.snapshot_id)
        assert first.snapshot_id == second.snapshot_id
        assert snapshot.manifest["required_secrets"] == (
            "env:AIWB_TEST_API_TOKEN",
        )
        serialized = snapshot.source + repr(snapshot.manifest).encode("utf-8")
        assert b"first-secret-value" not in serialized
        assert b"second-secret-value" not in serialized


def test_required_secrets_reject_inline_values() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["required_secrets"] = [
            {"reference": "env:AIWB_TEST_API_TOKEN", "value": "do-not-store"}
        ]
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="required_secrets"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.execution_snapshots() == ()


def test_literal_secret_fields_are_rejected_without_environment_help() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["metadata"] = {"api_token": "offline-secret-value"}
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="literal secret"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.execution_snapshots() == ()


def test_unknown_contract_fields_cannot_smuggle_opaque_values() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["metadata"] = {"note": "opaque-private-value"}
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="unsupported Contract field"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.execution_snapshots() == ()


def test_legacy_and_multi_todo_contract_forms_are_mutually_exclusive() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["todos"] = [
            {
                "id": "T-1",
                "title": "Implement Admission",
                "depends_on": [],
                "test_ids": ["AC-1"],
                "test": value["test"],
            }
        ]
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="mutually exclusive"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.execution_snapshots() == ()


def test_required_secrets_reject_unsupported_reference_schemes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["required_secrets"] = ["literal:offline-secret-value"]
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="supported references"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.execution_snapshots() == ()


def test_idempotency_key_rejects_a_different_execution_snapshot() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        ledger = SQLiteRunLedger(root / "state.db")
        admission = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v1",
        )
        request = AdmissionRequest(
            contract_path=contract,
            idempotency_key="submission-1",
        )
        first = admission.admit(request)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["goal"]["requirement"] = "A materially different requirement."
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )

        with pytest.raises(AdmissionError, match="idempotency key.*different"):
            admission.admit(request)

        assert ledger.queued_runs() == (ledger.run(first.run_id),)


@pytest.mark.parametrize(
    "boundary",
    ("after_snapshot", "after_run", "after_enqueue", "after_idempotency"),
)
def test_admission_failure_rolls_back_every_durable_effect(boundary: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)

        def fail_at_boundary(current: str) -> None:
            if current == boundary:
                raise RuntimeError(f"crash at {current}")

        ledger = SQLiteRunLedger(
            root / "state.db",
            _fault_injector=fail_at_boundary,
        )

        with pytest.raises(RuntimeError, match=f"crash at {boundary}"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(
                AdmissionRequest(
                    contract_path=contract,
                    idempotency_key="faulted-submission",
                )
            )

        assert ledger.queued_runs() == ()
        assert ledger.execution_snapshots() == ()


class RunLedgerBackendContract:
    """Behavior suite every future RunLedger backend must inherit."""

    def create_ledger(self, database: Path) -> RunLedger:
        raise NotImplementedError

    def create_faulting_ledger(
        self,
        database: Path,
        boundary: str,
    ) -> RunLedger:
        raise NotImplementedError

    def test_exact_source_and_queued_run_are_observable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = _create_repository(root)
            contract = _write_contract(root, repository)
            expected_source = contract.read_bytes()
            ledger = self.create_ledger(root / "state.db")

            admitted = Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

            assert ledger.execution_snapshot(admitted.snapshot_id).source == (
                expected_source
            )
            assert ledger.run(admitted.run_id) in ledger.queued_runs()

    def test_invalid_snapshot_identity_has_no_durable_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = self.create_ledger(root / "state.db")
            snapshot = ExecutionSnapshot(
                snapshot_id="0" * 64,
                source=b"approved source",
                manifest=_minimal_manifest_values(),
                created_at="2026-08-03T00:00:00+00:00",
            )

            with pytest.raises(AdmissionError, match="snapshot identity"):
                ledger.admit(snapshot, goal_id="goal")

            assert ledger.execution_snapshots() == ()
            assert ledger.queued_runs() == ()

    @pytest.mark.parametrize(
        "boundary",
        ("after_snapshot", "after_run", "after_enqueue", "after_idempotency"),
    )
    def test_atomic_admission_rollback(self, boundary: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = _create_repository(root)
            contract = _write_contract(root, repository)
            ledger = self.create_faulting_ledger(root / "state.db", boundary)

            with pytest.raises(RuntimeError, match=f"crash at {boundary}"):
                Admission(
                    ledger,
                    engine_version="test-engine",
                    transition_policy_version="strict-v1",
                ).admit(
                    AdmissionRequest(
                        contract_path=contract,
                        idempotency_key="faulted-submission",
                    )
                )

            assert ledger.execution_snapshots() == ()
            assert ledger.queued_runs() == ()

    def test_snapshot_reuse_preserves_distinct_runs_and_idempotent_retries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = _create_repository(root)
            contract = _write_contract(root, repository)
            ledger = self.create_ledger(root / "state.db")
            admission = Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            )

            first = admission.admit(AdmissionRequest(contract_path=contract))
            second = admission.admit(AdmissionRequest(contract_path=contract))
            keyed = admission.admit(
                AdmissionRequest(
                    contract_path=contract,
                    idempotency_key="submission-1",
                )
            )
            retry = admission.admit(
                AdmissionRequest(
                    contract_path=contract,
                    idempotency_key="submission-1",
                )
            )

            assert first.snapshot_id == second.snapshot_id == keyed.snapshot_id
            assert len({first.run_id, second.run_id, keyed.run_id}) == 3
            assert retry == keyed
            assert len(ledger.execution_snapshots()) == 1
            assert {run.run_id for run in ledger.queued_runs()} == {
                first.run_id,
                second.run_id,
                keyed.run_id,
            }


class TestSQLiteRunLedgerBackendContract(RunLedgerBackendContract):
    def create_ledger(self, database: Path) -> RunLedger:
        return SQLiteRunLedger(database)

    def create_faulting_ledger(
        self,
        database: Path,
        boundary: str,
    ) -> RunLedger:
        def fail_at_boundary(current: str) -> None:
            if current == boundary:
                raise RuntimeError(f"crash at {current}")

        return SQLiteRunLedger(database, _fault_injector=fail_at_boundary)


def test_dirty_repository_is_rejected_without_durable_residue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        (repository / "README.md").write_text("dirty\n", encoding="utf-8")
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="clean repository"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.queued_runs() == ()
        assert ledger.execution_snapshots() == ()


def test_unresolved_base_ref_is_rejected_without_durable_residue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["project"]["base_ref"] = "missing-branch"
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="Git Admission check failed"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.queued_runs() == ()
        assert ledger.execution_snapshots() == ()


def test_unauthorized_policy_is_rejected_without_durable_residue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["test"]["command"] = [sys.executable, "-c", "pass"]
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        ledger = SQLiteRunLedger(root / "state.db")

        with pytest.raises(AdmissionError, match="not an approved"):
            Admission(
                ledger,
                engine_version="test-engine",
                transition_policy_version="strict-v1",
            ).admit(AdmissionRequest(contract_path=contract))

        assert ledger.queued_runs() == ()
        assert ledger.execution_snapshots() == ()


def test_execution_snapshot_freezes_every_resolved_execution_input() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        policy_values = _configure_full_policy(root, repository)
        contract = _write_contract(root, repository)
        value = yaml.safe_load(contract.read_text(encoding="utf-8"))
        value["test"]["harness"] = "local-e2e"
        value["candidate"] = {"image_profile": "pr-image"}
        value["resources"] = {
            "agent_attempts": 7,
            "wall_clock_seconds": 3600,
            "harness_seconds": 300,
            "provider_tokens": 12345,
        }
        contract.write_text(
            yaml.safe_dump(value, sort_keys=False),
            encoding="utf-8",
        )
        expected_source = contract.read_bytes()
        pinned_commit = _git(repository, "rev-parse", "main").stdout.strip()
        ledger = SQLiteRunLedger(root / "state.db")

        admitted = Admission(
            ledger,
            engine_version="test-engine",
            transition_policy_version="strict-v1",
        ).admit(AdmissionRequest(contract_path=contract))
        original = ledger.execution_snapshot(admitted.snapshot_id)

        assert original.source == expected_source
        assert original.manifest["repository"]["base_commit"] == pinned_commit
        assert original.manifest["resources"] == {
            "agent_attempts": 7,
            "wall_clock_seconds": 3600.0,
            "harness_seconds": 300.0,
            "provider_tokens": 12345,
        }
        assert original.manifest["role_guidance"] == {
            "implementer": (
                (
                    ".agents/skills/focused/SKILL.md",
                    "# Focused\n\nKeep the implementation bounded.\n",
                ),
            )
        }
        assert original.manifest["todos"][0]["harness"]["name"] == "local-e2e"
        assert original.manifest["todos"][0]["harness"]["start_command"] == (
            tuple(policy_values["serve"])
        )
        assert original.manifest["image_profile"]["name"] == "pr-image"
        assert original.manifest["publish_policy"] == {
            "remote": "origin",
            "branch_prefix": "aiwb/",
            "remote_url": str(root / "remote.git"),
        }

        (repository / ".agents" / "skills" / "focused" / "SKILL.md").write_text(
            "# Changed guidance\n",
            encoding="utf-8",
        )
        (repository / ".ai-workbench" / "workflow.yaml").write_text(
            "schema_version: 999\n",
            encoding="utf-8",
        )
        (repository / "AFTER_ADMISSION.md").write_text("changed\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Move main after Admission")
        contract.write_text("schema_version: 999\n", encoding="utf-8")

        assert ledger.execution_snapshot(admitted.snapshot_id) == original


def test_run_ledger_rejects_an_invalid_execution_snapshot_identity() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = SQLiteRunLedger(root / "state.db")
        snapshot = ExecutionSnapshot(
            snapshot_id="0" * 64,
            source=b"approved source",
            manifest=_minimal_manifest_values(),
            created_at="2026-08-03T00:00:00+00:00",
        )

        with pytest.raises(AdmissionError, match="snapshot identity"):
            ledger.admit(snapshot, goal_id="goal")

        assert ledger.execution_snapshots() == ()
        assert ledger.queued_runs() == ()


def test_execution_snapshot_manifest_is_deeply_immutable() -> None:
    manifest = ExecutionManifest(_minimal_manifest_values())
    snapshot = ExecutionSnapshot(
        snapshot_id="not-yet-persisted",
        source=b"approved source",
        manifest=manifest,
        created_at="2026-08-03T00:00:00+00:00",
    )

    goal = snapshot.manifest["goal"]
    assert isinstance(goal, dict) is False
    with pytest.raises(TypeError):
        goal["id"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    "values, message",
    (
        ({"schema_version": 999, "versions": {}}, "schema_version"),
        (
            {
                "schema_version": 1,
                "versions": {
                    "admission_schema": 999,
                    "engine": "test-engine",
                    "transition_policy": "strict-v1",
                },
            },
            "admission_schema",
        ),
    ),
)
def test_execution_manifest_rejects_incompatible_schema(
    values: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(AdmissionError, match=message):
        ExecutionManifest(values)


def test_execution_manifest_rejects_an_incomplete_shape() -> None:
    values = _minimal_manifest_values()
    goal = values["goal"]
    assert isinstance(goal, dict)
    del goal["title"]

    with pytest.raises(AdmissionError, match="goal.title"):
        ExecutionManifest(values)


@pytest.mark.parametrize(
    "mutate, message",
    (
        (
            lambda values: values["resources"].update(
                {"agent_attempts": "many"}
            ),
            "resources.agent_attempts",
        ),
        (
            lambda values: values.update(
                {"required_secrets": ("literal:secret-value",)}
            ),
            "required_secrets",
        ),
        (
            lambda values: values["todos"][0].update(
                {"harness": {"name": "broken"}}
            ),
            "harness.kind",
        ),
    ),
)
def test_execution_manifest_rejects_malformed_execution_authority(
    mutate: object,
    message: str,
) -> None:
    values = _minimal_manifest_values()
    mutate(values)  # type: ignore[operator]

    with pytest.raises(AdmissionError, match=message):
        ExecutionManifest(values)


def _create_repository(root: Path) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    command = [sys.executable, "-m", "pytest", "-q"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {
                        "unit": {"argv": command, "approved": True},
                    },
                    "skills": {},
                },
                "harness": {
                    "profiles": {"local": {"environment": "local"}},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _minimal_manifest_values() -> dict[str, object]:
    return {
        "schema_version": 1,
        "versions": {
            "admission_schema": 1,
            "engine": "test-engine",
            "transition_policy": "strict-v1",
        },
        "approval_status": "approved",
        "goal": {
            "id": "goal",
            "title": "Goal",
            "requirement": "Requirement",
            "acceptance": ({"test_id": "AC-1", "statement": "It works"},),
        },
        "agent": {"provider": "codex", "model": None},
        "repository": {
            "path": "/project",
            "base_ref": "main",
            "base_commit": "a" * 40,
        },
        "todos": (
            {
                "todo_id": "T-1",
                "title": "Todo",
                "depends_on": (),
                "test_ids": ("AC-1",),
                "test_command": ("python", "-m", "pytest"),
                "allowed_test_paths": ("tests/test_goal.py",),
                "timeout_seconds": 60,
                "harness_name": "",
                "harness": None,
            },
        ),
        "resources": {},
        "role_guidance": {},
        "image_profile": None,
        "publish_policy": None,
        "policy": {
            "path": "/project/.ai-workbench/workflow.yaml",
            "source": "repository",
            "candidate_commands": (),
            "approved_commands": (("python", "-m", "pytest"),),
        },
        "required_secrets": (),
    }


def _write_contract(root: Path, repository: Path) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "admission-goal",
                    "title": "Freeze execution inputs",
                    "requirement": "Admit one immutable execution snapshot.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Admission is atomic."},
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 8, 3, tzinfo=timezone.utc),
                },
                "agent": {"provider": "codex", "model": "gpt-test"},
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {
                    "id": "T-1",
                    "title": "Implement Admission",
                },
                "test": {
                    "command": command,
                    "allowed_paths": ["tests/test_admission.py"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _configure_full_policy(root: Path, repository: Path) -> dict[str, list[str]]:
    remote = root / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _git(repository, "remote", "add", "origin", str(remote))
    skill = repository / ".agents" / "skills" / "focused" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "# Focused\n\nKeep the implementation bounded.\n",
        encoding="utf-8",
    )
    unit = [sys.executable, "-m", "pytest", "-q"]
    serve = [sys.executable, "-c", "print('ready')"]
    image_start = [sys.executable, "image.py", "start"]
    image_status = [sys.executable, "image.py", "status"]
    image_result = [sys.executable, "image.py", "result"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {
                        "unit": {"argv": unit, "approved": True},
                        "serve": {"argv": serve, "approved": True},
                        "image_start": {
                            "argv": image_start,
                            "approved": True,
                        },
                        "image_status": {
                            "argv": image_status,
                            "approved": True,
                        },
                        "image_result": {
                            "argv": image_result,
                            "approved": True,
                        },
                    },
                    "skills": {
                        "implementer": [
                            ".agents/skills/focused/SKILL.md",
                        ]
                    },
                },
                "harness": {
                    "profiles": {
                        "local-e2e": {
                            "kind": "local_process",
                            "environment": "local",
                            "start": {"command": serve},
                            "ready": {
                                "url": "http://127.0.0.1:{port}/health",
                                "timeout_seconds": 5,
                            },
                        }
                    }
                },
                "images": {
                    "profiles": {
                        "pr-image": {
                            "environment": "local",
                            "start": {"command": image_start},
                            "status": {"command": image_status},
                            "result": {"command": image_result},
                        }
                    }
                },
                "publishing": {
                    "candidate": {
                        "approved": True,
                        "remote": "origin",
                        "branch_prefix": "aiwb/",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Configure complete policy")
    return {
        "serve": serve,
        "image_start": image_start,
        "image_status": image_status,
        "image_result": image_result,
    }


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
