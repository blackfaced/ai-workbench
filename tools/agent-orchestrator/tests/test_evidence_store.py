from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    AgentResult,
    AgentDaemon,
    DaemonClient,
    EvidenceIntegrityError,
    EvidenceStore,
    GateError,
    GoalRunner,
    RunReport,
)
from aiwb.agent import AgentExecutionError, CodexCliAdapter  # noqa: E402
from aiwb.mcp_server import McpServer  # noqa: E402


class LargeOutputAgent:
    def __init__(self, fail_first_implementation: bool = False) -> None:
        self.fail_first_implementation = fail_first_implementation
        self.pin_implementation_mtime = fail_first_implementation
        self.calls = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls.append(request.role)
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting():\n"
                "    print('x' * 120000)\n"
                "    assert greeting() == 'hello'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            value = "incorrect" if self.fail_first_implementation else "hello"
            self.fail_first_implementation = False
            implementation = worktree / "greeting.py"
            implementation.write_text(
                "def greeting():\n"
                f"    return {value!r}\n",
                encoding="utf-8",
            )
            if self.pin_implementation_mtime:
                os.utime(implementation, (1_700_000_000, 1_700_000_000))
        return AgentResult(
            session_id=f"large-{request.role}",
            final_output="completed",
        )


class UnusedAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError(f"unexpected Agent call after restart: {request.role}")


class SensitiveFailureAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AgentExecutionError(
            provider=request.provider,
            role=request.role,
            reason="nonzero_exit",
            stdout="PRIVATE_AGENT_STDOUT_MARKER",
            stderr="PRIVATE_AGENT_STDERR_MARKER",
            returncode=42,
        )


class SensitiveTimeoutAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AgentExecutionError(
            provider=request.provider,
            role=request.role,
            reason="timeout",
            stdout="PRIVATE_TIMEOUT_STDOUT_MARKER",
            stderr="PRIVATE_TIMEOUT_STDERR_MARKER",
            timeout_seconds=request.timeout_seconds,
        )


class GenericSensitiveFailureAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise RuntimeError("PRIVATE_GENERIC_AGENT_ERROR_MARKER")


class SensitiveCandidateFailureAgent(LargeOutputAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        if request.role == "candidate_verifier":
            raise RuntimeError("PRIVATE_CANDIDATE_STDERR_MARKER")
        return super().run(request)


def test_content_addressed_store_bounds_text_and_detects_mutation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = EvidenceStore(Path(directory))
        full = "diagnostic-" * 20000

        summary, reference = store.retain_text(
            full,
            label="T-1/green/stdout",
        )

        assert len(summary.encode("utf-8")) <= 4096
        assert "truncated" in summary
        assert reference is not None
        assert reference.size_bytes == len(full.encode("utf-8"))
        assert reference.sha256 == reference.artifact_id
        payload = store.read(reference.artifact_id)
        assert payload.content == full
        assert payload.encoding == "utf-8"

        object_path = store.object_path(reference.artifact_id)
        object_path.write_text("mutated", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError, match="digest mismatch"):
            store.read(reference.artifact_id)


def test_large_runner_evidence_is_bounded_retrievable_and_restart_safe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"
        runner = GoalRunner(state_dir=state_dir, agent=LargeOutputAgent())

        report = runner.run(contract)

        assert report.status == "merge_ready"
        assert len(json.dumps(report.to_dict())) < 100_000
        assert all(len(item.stdout.encode("utf-8")) <= 4096 for item in report.evidence)
        references = [
            item.stdout_ref
            for item in report.evidence
            if item.stdout_ref is not None
        ]
        assert len(references) >= 3
        first = references[0]
        payload = runner.evidence(report.run_id, first.artifact_id)
        assert len(payload.content) >= 120000
        assert "xxxxxxxx" in payload.content
        with sqlite3.connect(state_dir / "state.db") as connection:
            inline_size = connection.execute(
                "SELECT length(evidence_json) FROM runs WHERE run_id = ?",
                (report.run_id,),
            ).fetchone()[0]
        assert inline_size < 50_000

        restarted = GoalRunner(state_dir=state_dir, agent=UnusedAgent())
        restored = restarted.report(report.run_id)
        assert first in {
            item.stdout_ref
            for item in restored.evidence
            if item.stdout_ref is not None
        }
        assert restarted.evidence(report.run_id, first.artifact_id).content == (
            payload.content
        )
        legacy = report.to_dict()
        for item in legacy["evidence"]:
            item.pop("stdout_ref", None)
            item.pop("stderr_ref", None)
            item.pop("artifact_refs", None)
        for todo in legacy["todos"]:
            for item in todo["evidence"]:
                item.pop("stdout_ref", None)
                item.pop("stderr_ref", None)
                item.pop("artifact_refs", None)
        legacy.pop("image_artifact_refs", None)
        assert RunReport.from_dict(legacy).evidence


def test_passing_retry_preserves_failed_evidence_and_consumption() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        agent = LargeOutputAgent(fail_first_implementation=True)
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        prepared = runner.prepare(contract)

        with pytest.raises(GateError, match="GREEN gate failed"):
            runner.run(contract)

        failed = runner.report(prepared.run_id)
        failed_green = [
            item
            for item in failed.evidence
            if item.stage == "green" and item.returncode != 0
        ]
        assert len(failed_green) == 1
        assert failed_green[0].stdout_ref is not None

        completed = runner.run(contract)

        green = [item for item in completed.evidence if item.stage == "green"]
        assert [item.returncode for item in green] == [1, 0]
        assert all(item.stdout_ref is not None for item in green)
        implementer = [
            attempt
            for attempt in completed.attempts
            if attempt.role == "implementer"
        ]
        assert len(implementer) == 2


def test_daemon_cli_and_mcp_fetch_full_evidence_only_when_requested() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=LargeOutputAgent(),
            socket_path=socket_path,
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(socket_path)
        _wait_until(client.ping)
        try:
            submitted = client.submit(contract)
            _wait_until(
                lambda: client.status(submitted.run_id).status == "merge_ready",
                timeout=30,
            )
            report = client.report(submitted.run_id)
            report_json = json.dumps(report.to_dict())
            assert len(report_json) < 100_000
            reference = next(
                item.stdout_ref
                for item in report.evidence
                if item.stdout_ref is not None
            )

            server = McpServer(socket_path)
            mcp_result = server._call_tool(
                "aiwb_goal_evidence",
                {
                    "run_id": submitted.run_id,
                    "artifact_id": reference.artifact_id,
                },
            )
            assert mcp_result["isError"] is False
            mcp_payload = json.loads(mcp_result["content"][0]["text"])
            assert len(mcp_payload["content"]) >= 120000

            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aiwb",
                    "goal",
                    "evidence",
                    submitted.run_id,
                    reference.artifact_id,
                    "--socket",
                    str(socket_path),
                ],
                cwd=str(TOOL_ROOT),
                env=environment,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            cli_payload = json.loads(completed.stdout)
            assert cli_payload == mcp_payload

            prune = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aiwb",
                    "evidence",
                    "prune",
                    "--older-than-days",
                    "30",
                    "--socket",
                    str(socket_path),
                ],
                cwd=str(TOOL_ROOT),
                env=environment,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert json.loads(prune.stdout)["deleted"] == 0
        finally:
            daemon.shutdown()
            thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    ("agent", "marker_prefix"),
    [
        (SensitiveFailureAgent(), "PRIVATE_AGENT_"),
        (SensitiveTimeoutAgent(), "PRIVATE_TIMEOUT_"),
    ],
    ids=("nonzero", "timeout"),
)
def test_agent_failure_outputs_are_only_available_as_explicit_evidence(
    agent: object,
    marker_prefix: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=agent,
            socket_path=socket_path,
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(socket_path)
        _wait_until(client.ping)
        try:
            submitted = client.submit(contract)
            _wait_until(
                lambda: client.status(submitted.run_id).status == "blocked",
            )
            status = client.status(submitted.run_id)
            report = client.report(submitted.run_id)
            attempt = report.attempts[0]

            assert attempt.stdout_ref is not None
            assert attempt.stderr_ref is not None
            assert marker_prefix not in status.error
            assert marker_prefix not in json.dumps(report.to_dict())
            assert len(status.error.encode("utf-8")) <= 512

            stdout = client.evidence(
                submitted.run_id,
                attempt.stdout_ref.artifact_id,
            )
            stderr = client.evidence(
                submitted.run_id,
                attempt.stderr_ref.artifact_id,
            )
            assert stdout.content == f"{marker_prefix}STDOUT_MARKER"
            assert stderr.content == f"{marker_prefix}STDERR_MARKER"

            with sqlite3.connect(state_dir / "run-ledger.db") as connection:
                run_error = connection.execute(
                    "SELECT error FROM runs WHERE run_id = ?",
                    (submitted.run_id,),
                ).fetchone()[0]
                transition_errors = connection.execute(
                    "SELECT error FROM run_transitions WHERE run_id = ?",
                    (submitted.run_id,),
                ).fetchall()
            assert marker_prefix not in run_error
            assert all(marker_prefix not in item[0] for item in transition_errors)
            assert len(run_error.encode("utf-8")) <= 512
        finally:
            daemon.shutdown()
            thread.join(timeout=5)
        assert not thread.is_alive()


def test_generic_agent_failure_is_redacted_across_ledger_projections() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=GenericSensitiveFailureAgent(),
            socket_path=socket_path,
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(socket_path)
        _wait_until(client.ping)
        try:
            submitted = client.submit(contract)
            _wait_until(
                lambda: client.status(submitted.run_id).status == "blocked",
            )
            status = client.status(submitted.run_id)
            report = client.report(submitted.run_id)
            attempt = report.attempts[0]

            assert attempt.stderr_ref is not None
            assert "PRIVATE_GENERIC_AGENT_ERROR_MARKER" not in status.error
            assert "PRIVATE_GENERIC_AGENT_ERROR_MARKER" not in json.dumps(
                report.to_dict()
            )
            payload = client.evidence(
                submitted.run_id,
                attempt.stderr_ref.artifact_id,
            )
            assert payload.content == "PRIVATE_GENERIC_AGENT_ERROR_MARKER"

            with sqlite3.connect(state_dir / "run-ledger.db") as connection:
                run_error = connection.execute(
                    "SELECT error FROM runs WHERE run_id = ?",
                    (submitted.run_id,),
                ).fetchone()[0]
                todo_error = connection.execute(
                    "SELECT last_error FROM todos WHERE run_id = ?",
                    (submitted.run_id,),
                ).fetchone()[0]
                transition_errors = connection.execute(
                    "SELECT error FROM run_transitions WHERE run_id = ?",
                    (submitted.run_id,),
                ).fetchall()
            assert "PRIVATE_GENERIC_AGENT_ERROR_MARKER" not in run_error
            assert "PRIVATE_GENERIC_AGENT_ERROR_MARKER" not in (todo_error or "")
            assert all(
                "PRIVATE_GENERIC_AGENT_ERROR_MARKER" not in item[0]
                for item in transition_errors
            )
        finally:
            daemon.shutdown()
            thread.join(timeout=5)
        assert not thread.is_alive()


def test_daemon_persists_attempts_and_harness_evidence_after_agent_parent_exit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        contract_data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        contract_data["test"]["timeout_seconds"] = 5
        contract.write_text(
            yaml.safe_dump(contract_data, sort_keys=False),
            encoding="utf-8",
        )
        executable = root / "fake-codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, subprocess, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "worktree = Path(args[args.index('--cd') + 1])\n"
            "prompt = args[-1]\n"
            "if 'Test Designer' in prompt:\n"
            "    tests = worktree / 'tests'\n"
            "    tests.mkdir(exist_ok=True)\n"
            "    (tests / 'test_greeting.py').write_text("
            "\"from greeting import greeting\\n\\ndef test_greeting():\\n"
            "    assert greeting() == 'hello'\\n\")\n"
            "    subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(10)'])\n"
            "elif 'Implementer' in prompt:\n"
            "    (worktree / 'greeting.py').write_text("
            "\"def greeting():\\n    return 'hello'\\n\")\n"
            "print(json.dumps({'type': 'thread.started', "
            "'thread_id': 'thread-123'}), flush=True)\n"
            "print(json.dumps({'type': 'item.completed', 'item': {"
            "'type': 'agent_message', 'text': 'completed'}}), flush=True)\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=CodexCliAdapter(str(executable)),
            socket_path=socket_path,
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        client = DaemonClient(socket_path)
        _wait_until(client.ping)
        try:
            submitted = client.submit(contract)
            _wait_until(
                lambda: client.status(submitted.run_id).status
                in {
                    "merge_ready",
                    "blocked",
                    "failed",
                    "failed_cleanup",
                    "paused",
                },
                timeout=30,
            )
            status = client.status(submitted.run_id)
            report = client.report(submitted.run_id)

            assert status.status == "merge_ready", status.error
            assert report.status == "merge_ready"
            assert report.todos[0].status == "integrated"
            assert [attempt.status for attempt in report.attempts] == [
                "succeeded",
                "succeeded",
                "succeeded",
                "succeeded",
            ]
            assert {attempt.role for attempt in report.attempts} == {
                "test_designer",
                "implementer",
                "verifier",
                "candidate_verifier",
            }
            assert report.evidence
            assert report.todos[0].evidence
        finally:
            daemon.shutdown()
            thread.join(timeout=5)
        assert not thread.is_alive()


def test_candidate_verifier_failure_output_is_retained_as_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        runner = GoalRunner(
            state_dir=root / "state",
            agent=SensitiveCandidateFailureAgent(),
        )
        prepared = runner.prepare(contract)

        with pytest.raises(RuntimeError):
            runner.run(contract)

        report = runner.report(prepared.run_id)
        attempt = next(
            item for item in report.attempts if item.role == "candidate_verifier"
        )
        assert attempt.stderr_ref is not None
        assert "PRIVATE_CANDIDATE_STDERR_MARKER" not in attempt.error
        payload = runner.evidence(
            prepared.run_id,
            attempt.stderr_ref.artifact_id,
        )
        assert payload.content == "PRIVATE_CANDIDATE_STDERR_MARKER"


def test_explicit_retention_prune_removes_only_old_objects() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory)
        store = EvidenceStore(state_dir)
        old = store.retain_bytes(
            b"old",
            label="old",
            media_type="text/plain",
        )
        current = store.retain_bytes(
            b"current",
            label="current",
            media_type="text/plain",
        )
        old_path = store.object_path(old.artifact_id)
        old_time = time.time() - 40 * 86400
        os.utime(old_path, (old_time, old_time))

        report = store.prune(older_than_days=30)

        assert report.scanned == 2
        assert report.deleted == 1
        assert report.retained == 1
        assert not old_path.exists()
        assert store.object_path(current.artifact_id).is_file()


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (ConnectionError, FileNotFoundError):
            pass
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def _create_repository(root: Path) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "pytest", "-q", "-s"]
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
                "harness": {"profiles": {}},
                "images": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_contract(root: Path, repository: Path) -> Path:
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "bounded-evidence-goal",
                    "title": "Bound large Evidence",
                    "requirement": "Retain complete diagnostics without large reports.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting returns hello."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc),
                },
                "agent": {"provider": "codex"},
                "resources": {},
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Implement greeting"},
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q", "-s"],
                    "allowed_paths": ["tests/test_greeting.py"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
