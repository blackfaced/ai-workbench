from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from .agent import AgentAdapter, AgentRequest, AgentResult
from .browser import McpBrowserDiagnosticAdapter
from .harness import HarnessAdapter, HarnessRequest, LocalProcessHarness
from .image import CommandImageBuilder, ImageBuildRequest
from .kubernetes import JanitorReport, KubernetesHarness, KubernetesJanitor
from .project import (
    CandidatePublishProfile,
    HarnessProfile,
    ImageProfile,
    ProjectConfigError,
    ProjectPolicy,
)
from .publish import CandidatePublishError, CandidatePublishRequest, CandidatePublisher


class ContractError(ValueError):
    pass


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Acceptance:
    test_id: str
    statement: str


@dataclass(frozen=True)
class _Todo:
    todo_id: str
    title: str
    depends_on: Tuple[str, ...]
    test_ids: Tuple[str, ...]
    test_command: Tuple[str, ...]
    allowed_test_paths: Tuple[str, ...]
    timeout_seconds: int
    harness_name: str
    harness: Optional[HarnessProfile]


@dataclass(frozen=True)
class _Contract:
    contract_hash: str
    goal_id: str
    goal_title: str
    requirement: str
    acceptance: Tuple[_Acceptance, ...]
    agent_provider: str
    agent_model: Optional[str]
    repository: Path
    base_ref: str
    todos: Tuple[_Todo, ...]
    legacy_single_todo: bool
    image_profile_name: str
    image_profile: Optional[ImageProfile]
    candidate_publish: Optional[CandidatePublishProfile]

    @property
    def run_id(self) -> str:
        return f"{self.goal_id}-{self.contract_hash[:12]}"

    @property
    def branch(self) -> str:
        prefix = (
            self.candidate_publish.branch_prefix
            if self.candidate_publish is not None
            else "aiwb/"
        )
        return f"{prefix}{self.goal_id}/integration-{self.contract_hash[:8]}"

    def todo_branch(self, todo: _Todo) -> str:
        return f"aiwb/{self.goal_id}/{todo.todo_id}-{self.contract_hash[:8]}"

    @property
    def todo_id(self) -> str:
        return self.todos[0].todo_id

    @property
    def todo_title(self) -> str:
        return self.todos[0].title

    @property
    def test_command(self) -> Tuple[str, ...]:
        return self.todos[0].test_command

    @property
    def allowed_test_paths(self) -> Tuple[str, ...]:
        return self.todos[0].allowed_test_paths

    @property
    def timeout_seconds(self) -> int:
        return self.todos[0].timeout_seconds


@dataclass(frozen=True)
class CommandEvidence:
    stage: str
    command: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    recorded_at: str
    harness_profile: str = ""
    environment: str = ""
    base_url: str = ""
    artifacts: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TodoReport:
    todo_id: str
    status: str
    branch: str
    worktree: str
    base_commit: str
    red_commit: str
    code_commit: str
    sessions: Mapping[str, str] = field(default_factory=dict)
    evidence: Tuple[CommandEvidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RunReport:
    run_id: str
    goal_id: str
    status: str
    branch: str
    worktree: str
    contract_hash: str
    red_commit: str
    code_commit: str
    sessions: Mapping[str, str] = field(default_factory=dict)
    evidence: Tuple[CommandEvidence, ...] = field(default_factory=tuple)
    todos: Tuple[TodoReport, ...] = field(default_factory=tuple)
    image_profile: str = ""
    image_operation_id: str = ""
    image_status: str = ""
    image_digest: str = ""
    image_artifacts: Tuple[str, ...] = field(default_factory=tuple)
    published_remote: str = ""
    published_ref: str = ""
    published_commit: str = ""

    def to_dict(self) -> Dict[str, object]:
        value = asdict(self)
        value["evidence"] = [asdict(item) for item in self.evidence]
        todo_values = []
        for todo in self.todos:
            item = asdict(todo)
            item["evidence"] = [asdict(evidence) for evidence in todo.evidence]
            todo_values.append(item)
        value["todos"] = todo_values
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunReport":
        evidence_data = value.get("evidence", [])
        if not isinstance(evidence_data, list):
            raise ValueError("report evidence must be a list")
        evidence = tuple(
            CommandEvidence(
                stage=str(item["stage"]),
                command=tuple(str(part) for part in item["command"]),
                returncode=int(item["returncode"]),
                stdout=str(item["stdout"]),
                stderr=str(item["stderr"]),
                recorded_at=str(item["recorded_at"]),
                harness_profile=str(item.get("harness_profile", "")),
                environment=str(item.get("environment", "")),
                base_url=str(item.get("base_url", "")),
                artifacts=tuple(str(path) for path in item.get("artifacts", [])),
            )
            for item in evidence_data
            if isinstance(item, dict)
        )
        sessions_data = value.get("sessions", {})
        if not isinstance(sessions_data, dict):
            raise ValueError("report sessions must be a mapping")
        todos_data = value.get("todos", [])
        if not isinstance(todos_data, list):
            raise ValueError("report todos must be a list")
        return cls(
            run_id=str(value["run_id"]),
            goal_id=str(value["goal_id"]),
            status=str(value["status"]),
            branch=str(value["branch"]),
            worktree=str(value["worktree"]),
            contract_hash=str(value["contract_hash"]),
            red_commit=str(value.get("red_commit", "")),
            code_commit=str(value.get("code_commit", "")),
            sessions={str(key): str(item) for key, item in sessions_data.items()},
            evidence=evidence,
            todos=tuple(_todo_report_from_dict(item) for item in todos_data),
            image_profile=str(value.get("image_profile", "")),
            image_operation_id=str(value.get("image_operation_id", "")),
            image_status=str(value.get("image_status", "")),
            image_digest=str(value.get("image_digest", "")),
            image_artifacts=tuple(
                str(item) for item in value.get("image_artifacts", [])
            ),
            published_remote=str(value.get("published_remote", "")),
            published_ref=str(value.get("published_ref", "")),
            published_commit=str(value.get("published_commit", "")),
        )


class GoalRunner:
    """Execute and recover an approved Contract into one Candidate branch."""

    def __init__(
        self,
        state_dir: Path,
        agent: AgentAdapter,
        max_workers: int = 1,
        image_poll_interval_seconds: float = 5.0,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if image_poll_interval_seconds <= 0:
            raise ValueError("image_poll_interval_seconds must be positive")
        self._state_dir = Path(state_dir).expanduser().resolve()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._store = _RunStore(self._state_dir / "state.db")
        self._agent = agent
        self._max_workers = max_workers
        self._git_lock = threading.Lock()
        browser_diagnostics = McpBrowserDiagnosticAdapter()
        self._harnesses: Mapping[str, HarnessAdapter] = {
            "local_process": LocalProcessHarness(browser_diagnostics),
            "kubernetes": KubernetesHarness(self._state_dir, browser_diagnostics),
        }
        self._kubernetes_janitor = KubernetesJanitor(self._state_dir)
        self._image_builder = CommandImageBuilder()
        self._candidate_publisher = CandidatePublisher()
        self._image_poll_interval_seconds = image_poll_interval_seconds

    def prepare(self, contract_path: Path) -> RunReport:
        _, _, record = self._prepare(Path(contract_path))
        return self._report(record)

    def report(self, run_id: str) -> RunReport:
        return self._report(self._store.get(run_id))

    def sweep_kubernetes(self) -> JanitorReport:
        return self._kubernetes_janitor.sweep()

    def run(self, contract_path: Path) -> RunReport:
        contract, workspace, record = self._prepare(Path(contract_path))

        if not contract.legacy_single_todo:
            return self._run_dag(contract, workspace, record)

        if record["status"] == "merge_ready":
            return self._publish_candidate(contract, workspace, record)
        if record["status"] in {"candidate_verified", "waiting_image"}:
            return self._await_image(contract, workspace)

        if record["status"] == "approved":
            self._create_red_checkpoint(contract, workspace)
            record = self._store.get(contract.run_id)

        if record["status"] == "red_verified":
            self._create_code_checkpoint(contract, workspace, record)
            record = self._store.get(contract.run_id)

        if record["status"] == "code_ready":
            self._verify_candidate(contract, workspace, record)
            record = self._store.get(contract.run_id)

        if record["status"] == "candidate_verified":
            return self._await_image(contract, workspace)
        if record["status"] == "merge_ready":
            return self._publish_candidate(contract, workspace, record)
        return self._report(record)

    def _run_dag(
        self,
        contract: _Contract,
        candidate: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> RunReport:
        if record["status"] == "merge_ready":
            return self._publish_candidate(contract, candidate, record)
        if record["status"] in {"candidate_verified", "waiting_image"}:
            return self._await_image(contract, candidate)

        self._store.set_run_status(contract.run_id, "running")
        while True:
            todo_records = self._store.get_todos(contract.run_id)
            if all(item["status"] == "integrated" for item in todo_records):
                return self._finish_candidate(contract, candidate)

            ready = self._ready_todos(contract, todo_records)
            if not ready:
                raise GateError("Todo DAG has no runnable node")

            workspaces = self._prepare_todo_layer(contract, candidate, ready)
            self._execute_todo_layer(contract, ready, workspaces)
            self._integrate_todo_layer(contract, candidate, ready)

    @staticmethod
    def _ready_todos(
        contract: _Contract,
        records: Sequence[Mapping[str, Any]],
    ) -> List[_Todo]:
        integrated = {
            item["todo_id"] for item in records if item["status"] == "integrated"
        }
        return [
            todo
            for todo in contract.todos
            if GoalRunner._todo_ready(todo, records, integrated)
        ]

    def _prepare_todo_layer(
        self,
        contract: _Contract,
        candidate: "_GitWorkspace",
        todos: Sequence[_Todo],
    ) -> Dict[str, "_GitWorkspace"]:
        candidate_head = candidate.head()
        return {
            todo.todo_id: self._prepare_todo_workspace(
                contract,
                todo,
                candidate_head,
            )
            for todo in todos
        }

    def _execute_todo_layer(
        self,
        contract: _Contract,
        todos: Sequence[_Todo],
        workspaces: Mapping[str, "_GitWorkspace"],
    ) -> None:
        with ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(todos))
        ) as executor:
            futures = [
                executor.submit(
                    self._run_todo,
                    contract,
                    todo,
                    workspaces[todo.todo_id],
                )
                for todo in todos
            ]
            for future in futures:
                future.result()

    def _integrate_todo_layer(
        self,
        contract: _Contract,
        candidate: "_GitWorkspace",
        todos: Sequence[_Todo],
    ) -> None:
        for todo in sorted(todos, key=lambda item: item.todo_id):
            todo_record = self._store.get_todo(contract.run_id, todo.todo_id)
            code_commit = _required_string(todo_record, "code_commit")
            if not candidate.contains(code_commit):
                candidate.merge(contract.todo_branch(todo))
            evidence = self._run_gate(
                contract=contract,
                todo=todo,
                stage=f"integrate:{todo.todo_id}",
                cwd=candidate.worktree,
            )
            if evidence.returncode != 0:
                raise GateError(
                    f"Candidate integration failed for {todo.todo_id}:\n"
                    + (evidence.stderr or evidence.stdout)
                )
            self._store.integrate_todo(contract.run_id, todo.todo_id, evidence)

    @staticmethod
    def _todo_ready(
        todo: _Todo,
        records: Sequence[Mapping[str, Any]],
        integrated: set[str],
    ) -> bool:
        status = next(
            item["status"] for item in records if item["todo_id"] == todo.todo_id
        )
        return status != "integrated" and set(todo.depends_on) <= integrated

    def _prepare_todo_workspace(
        self,
        contract: _Contract,
        todo: _Todo,
        candidate_head: str,
    ) -> "_GitWorkspace":
        record = self._store.get_todo(contract.run_id, todo.todo_id)
        base_commit = record["base_commit"] or candidate_head
        worktree = (
            self._state_dir
            / "worktrees"
            / contract.run_id
            / "todos"
            / todo.todo_id
        )
        workspace = _GitWorkspace(
            repository=contract.repository,
            worktree=worktree,
            branch=contract.todo_branch(todo),
            base_ref=base_commit,
        )
        workspace.ensure()
        self._store.prepare_todo(
            contract.run_id,
            todo.todo_id,
            branch=workspace.branch,
            worktree=workspace.worktree,
            base_commit=base_commit,
        )
        return workspace

    def _run_todo(
        self,
        contract: _Contract,
        todo: _Todo,
        workspace: "_GitWorkspace",
    ) -> None:
        record = self._store.get_todo(contract.run_id, todo.todo_id)
        if record["status"] == "pending":
            self._create_todo_red_checkpoint(contract, todo, workspace)
            record = self._store.get_todo(contract.run_id, todo.todo_id)
        if record["status"] == "red_verified":
            self._create_todo_code_checkpoint(contract, todo, workspace, record)
            record = self._store.get_todo(contract.run_id, todo.todo_id)
        if record["status"] == "code_ready":
            self._verify_todo(contract, todo, workspace, record)

    def _create_todo_red_checkpoint(
        self,
        contract: _Contract,
        todo: _Todo,
        workspace: "_GitWorkspace",
    ) -> None:
        record = self._store.get_todo(contract.run_id, todo.todo_id)
        workspace.restore_checkpoint(_required_string(record, "base_commit"))
        self._store.set_todo_stage(contract.run_id, todo.todo_id, "test_designer")
        result = self._agent.run(
            AgentRequest(
                role="test_designer",
                prompt=_test_designer_prompt(contract, todo),
                worktree=str(workspace.worktree),
                todo_id=todo.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model,
                timeout_seconds=todo.timeout_seconds,
            )
        )
        changed_paths = workspace.changed_paths()
        if not changed_paths:
            raise GateError(f"Test Designer produced no test changes for {todo.todo_id}")
        outside = [
            path for path in changed_paths if not _matches_any(path, todo.allowed_test_paths)
        ]
        if outside:
            raise GateError(
                f"Test Designer changed paths outside {todo.todo_id} test paths: "
                + ", ".join(outside)
            )
        evidence = self._run_gate(
            contract,
            todo,
            "red",
            workspace.worktree,
        )
        if evidence.returncode == 0:
            raise GateError(f"RED gate failed for {todo.todo_id}")
        with self._git_lock:
            red_commit = workspace.commit(
                f"test({todo.todo_id}): add RED acceptance test"
            )
        self._store.todo_checkpoint(
            contract.run_id,
            todo.todo_id,
            "red_verified",
            result,
            "test_designer",
            evidence,
            red_commit=red_commit,
        )

    def _create_todo_code_checkpoint(
        self,
        contract: _Contract,
        todo: _Todo,
        workspace: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> None:
        workspace.restore_checkpoint(_required_string(record, "red_commit"))
        self._store.set_todo_stage(contract.run_id, todo.todo_id, "implementer")
        try:
            result = self._agent.run(
                AgentRequest(
                    role="implementer",
                    prompt=_implementer_prompt(contract, todo),
                    worktree=str(workspace.worktree),
                    todo_id=todo.todo_id,
                    provider=contract.agent_provider,
                    model=contract.agent_model,
                    timeout_seconds=todo.timeout_seconds,
                )
            )
        except Exception as error:
            self._store.record_todo_interruption(
                contract.run_id, todo.todo_id, str(error)
            )
            raise
        changed_paths = workspace.changed_paths()
        if not changed_paths:
            raise GateError(f"Implementer produced no code changes for {todo.todo_id}")
        protected = [
            path for path in changed_paths if _matches_any(path, todo.allowed_test_paths)
        ]
        if protected:
            raise GateError(
                f"Implementer changed protected RED tests for {todo.todo_id}: "
                + ", ".join(protected)
            )
        evidence = self._run_gate(
            contract,
            todo,
            "green",
            workspace.worktree,
        )
        if evidence.returncode != 0:
            raise GateError(
                f"GREEN gate failed for {todo.todo_id}:\n"
                + (evidence.stderr or evidence.stdout)
            )
        with self._git_lock:
            code_commit = workspace.commit(
                f"feat({todo.todo_id}): satisfy acceptance test"
            )
        self._store.todo_checkpoint(
            contract.run_id,
            todo.todo_id,
            "code_ready",
            result,
            "implementer",
            evidence,
            code_commit=code_commit,
        )

    def _verify_todo(
        self,
        contract: _Contract,
        todo: _Todo,
        workspace: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> None:
        code_commit = _required_string(record, "code_commit")
        workspace.restore_checkpoint(code_commit)
        self._store.set_todo_stage(contract.run_id, todo.todo_id, "verifier")
        result = self._agent.run(
            AgentRequest(
                role="verifier",
                prompt=_verifier_prompt(contract, todo),
                worktree=str(workspace.worktree),
                todo_id=todo.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model,
                timeout_seconds=todo.timeout_seconds,
            )
        )
        if workspace.changed_paths():
            workspace.restore_checkpoint(code_commit)
            raise GateError(f"Verifier mutated Todo Candidate {todo.todo_id}")
        evidence = self._run_gate(
            contract,
            todo,
            "verify",
            workspace.worktree,
        )
        if evidence.returncode != 0:
            raise GateError(
                f"verification gate failed for {todo.todo_id}:\n"
                + (evidence.stderr or evidence.stdout)
            )
        self._store.todo_checkpoint(
            contract.run_id,
            todo.todo_id,
            "verified",
            result,
            "verifier",
            evidence,
        )

    def _prepare(
        self,
        contract_path: Path,
    ) -> Tuple[_Contract, "_GitWorkspace", Mapping[str, Any]]:
        contract = _load_contract(contract_path)
        worktree = self._state_dir / "worktrees" / contract.run_id
        if not contract.legacy_single_todo:
            worktree = worktree / "candidate"
        workspace = _GitWorkspace(
            repository=contract.repository,
            worktree=worktree,
            branch=contract.branch,
            base_ref=contract.base_ref,
        )
        workspace.ensure()
        record = self._store.get_or_create(contract, workspace.worktree)
        return contract, workspace, record

    def _create_red_checkpoint(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> None:
        workspace.restore_checkpoint(workspace.head())
        self._store.set_active_stage(contract.run_id, "test_designer")
        result = self._agent.run(
            AgentRequest(
                role="test_designer",
                prompt=_test_designer_prompt(contract),
                worktree=str(workspace.worktree),
                todo_id=contract.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model,
                timeout_seconds=contract.timeout_seconds,
            )
        )
        changed_paths = workspace.changed_paths()
        if not changed_paths:
            raise GateError("Test Designer produced no test changes")
        outside_test_paths = [
            path
            for path in changed_paths
            if not _matches_any(path, contract.allowed_test_paths)
        ]
        if outside_test_paths:
            raise GateError(
                "Test Designer changed paths outside the approved test paths: "
                + ", ".join(outside_test_paths)
            )

        evidence = self._run_gate(
            contract,
            contract.todos[0],
            "red",
            workspace.worktree,
        )
        if evidence.returncode == 0:
            raise GateError("RED gate failed: the new test passed before implementation")

        red_commit = workspace.commit(f"test({contract.todo_id}): add RED acceptance test")
        self._store.checkpoint(
            contract.run_id,
            status="red_verified",
            red_commit=red_commit,
            agent_result=result,
            role="test_designer",
            evidence=evidence,
        )

    def _create_code_checkpoint(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> None:
        red_commit = _required_string(record, "red_commit")
        workspace.restore_checkpoint(red_commit)
        self._store.set_active_stage(contract.run_id, "implementer")
        try:
            result = self._agent.run(
                AgentRequest(
                    role="implementer",
                prompt=_implementer_prompt(contract),
                worktree=str(workspace.worktree),
                todo_id=contract.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model,
                timeout_seconds=contract.timeout_seconds,
                )
            )
        except Exception as error:
            self._store.record_interruption(contract.run_id, str(error))
            raise

        changed_paths = workspace.changed_paths()
        if not changed_paths:
            raise GateError("Implementer produced no code changes")
        protected_changes = [
            path
            for path in changed_paths
            if _matches_any(path, contract.allowed_test_paths)
        ]
        if protected_changes:
            raise GateError(
                "Implementer changed protected RED tests: "
                + ", ".join(protected_changes)
            )

        evidence = self._run_gate(
            contract,
            contract.todos[0],
            "green",
            workspace.worktree,
        )
        if evidence.returncode != 0:
            raise GateError(
                "GREEN gate failed after implementation:\n"
                + (evidence.stderr or evidence.stdout)
            )

        code_commit = workspace.commit(f"feat({contract.todo_id}): satisfy acceptance test")
        self._store.checkpoint(
            contract.run_id,
            status="code_ready",
            code_commit=code_commit,
            agent_result=result,
            role="implementer",
            evidence=evidence,
        )

    def _verify_candidate(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> None:
        code_commit = _required_string(record, "code_commit")
        workspace.restore_checkpoint(code_commit)
        self._store.set_active_stage(contract.run_id, "verifier")
        result = self._agent.run(
            AgentRequest(
                role="verifier",
                prompt=_verifier_prompt(contract),
                worktree=str(workspace.worktree),
                todo_id=contract.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model,
                timeout_seconds=contract.timeout_seconds,
            )
        )
        changed_paths = workspace.changed_paths()
        if changed_paths:
            workspace.restore_checkpoint(code_commit)
            raise GateError(
                "Verifier mutated the Candidate: " + ", ".join(changed_paths)
            )

        evidence = self._run_gate(
            contract,
            contract.todos[0],
            "verify",
            workspace.worktree,
        )
        if evidence.returncode != 0:
            raise GateError(
                "verification gate failed:\n" + (evidence.stderr or evidence.stdout)
            )
        if workspace.changed_paths():
            workspace.restore_checkpoint(code_commit)
            raise GateError("Verification command mutated the Candidate")

        self._store.checkpoint(
            contract.run_id,
            status=(
                "candidate_verified"
                if contract.image_profile is not None
                else "merge_ready"
            ),
            agent_result=result,
            role="verifier",
            evidence=evidence,
        )

    def _finish_candidate(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> RunReport:
        if contract.image_profile is None:
            self._store.set_run_status(contract.run_id, "merge_ready")
            record = self._store.get(contract.run_id)
            return self._publish_candidate(contract, workspace, record)
        self._store.set_run_status(contract.run_id, "candidate_verified")
        return self._await_image(contract, workspace)

    def _await_image(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> RunReport:
        profile = contract.image_profile
        if profile is None:
            raise RuntimeError("Run is waiting for an image without an image profile")
        request = ImageBuildRequest(
            profile=profile,
            cwd=workspace.worktree,
            run_id=contract.run_id,
            artifact_dir=self._state_dir / "image-builds" / contract.run_id,
        )
        while True:
            record = self._store.get(contract.run_id)
            operation_id = record["image_operation_id"]
            if not operation_id:
                operation_id = self._image_builder.start(request)
                self._store.start_image(contract.run_id, operation_id)
            status = self._image_builder.status(request, operation_id)
            self._store.set_image_status(contract.run_id, status)
            if status == "succeeded":
                result = self._image_builder.result(request, operation_id)
                self._store.complete_image(
                    contract.run_id,
                    result.digest,
                    result.artifacts,
                )
                record = self._store.get(contract.run_id)
                return self._publish_candidate(contract, workspace, record)
            time.sleep(self._image_poll_interval_seconds)

    def _publish_candidate(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
        record: Mapping[str, Any],
    ) -> RunReport:
        profile = contract.candidate_publish
        if profile is None or record["published_commit"]:
            return self._report(record)
        try:
            result = self._candidate_publisher.publish(
                CandidatePublishRequest(
                    repository=contract.repository,
                    branch=contract.branch,
                    commit=workspace.head(),
                    profile=profile,
                )
            )
        except CandidatePublishError as error:
            self._store.record_interruption(contract.run_id, str(error))
            raise
        self._store.complete_publish(
            contract.run_id,
            remote=result.remote,
            ref=result.ref,
            commit=result.commit,
        )
        return self._report(self._store.get(contract.run_id))

    def _run_gate(
        self,
        contract: _Contract,
        todo: _Todo,
        stage: str,
        cwd: Path,
    ) -> CommandEvidence:
        if todo.harness is None:
            return _run_command(
                stage=stage,
                command=todo.test_command,
                cwd=cwd,
                timeout_seconds=todo.timeout_seconds,
            )
        artifact_dir = (
            self._state_dir
            / "evidence"
            / contract.run_id
            / todo.todo_id
            / stage.replace(":", "-")
        )
        adapter = self._harnesses[todo.harness.kind]
        result = adapter.execute(HarnessRequest(
            profile=todo.harness,
            command=todo.test_command,
            cwd=cwd,
            timeout_seconds=todo.timeout_seconds,
            run_id=contract.run_id,
            artifact_dir=artifact_dir,
            execution_id=f"{todo.todo_id}:{stage}",
            stage=stage,
        ))
        stderr = result.stderr
        artifacts = result.artifacts
        if result.browser_diagnostic is not None:
            diagnostic = result.browser_diagnostic
            diagnostic_detail = (
                f"Browser diagnostic ({diagnostic.adapter}): {diagnostic.summary}"
            )
            if diagnostic.error:
                diagnostic_detail += f" Error: {diagnostic.error}"
            if diagnostic.artifacts:
                diagnostic_detail += " Artifacts: " + ", ".join(diagnostic.artifacts)
            stderr = "\n".join(part for part in (stderr, diagnostic_detail) if part)
            artifacts = artifacts + diagnostic.artifacts
        return CommandEvidence(
            stage=stage,
            command=todo.test_command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=stderr,
            recorded_at=_now(),
            harness_profile=todo.harness.name,
            environment=result.environment,
            base_url=result.base_url,
            artifacts=artifacts,
        )

    def _report(self, record: Mapping[str, Any]) -> RunReport:
        evidence = tuple(
            CommandEvidence(
                stage=item["stage"],
                command=tuple(item["command"]),
                returncode=item["returncode"],
                stdout=item["stdout"],
                stderr=item["stderr"],
                recorded_at=item["recorded_at"],
                harness_profile=item.get("harness_profile", ""),
                environment=item.get("environment", ""),
                base_url=item.get("base_url", ""),
                artifacts=tuple(item.get("artifacts", [])),
            )
            for item in json.loads(record["evidence_json"])
        )
        return RunReport(
            run_id=record["run_id"],
            goal_id=record["goal_id"],
            status=record["status"],
            branch=record["branch"],
            worktree=record["worktree"],
            contract_hash=record["contract_hash"],
            red_commit=record["red_commit"] or "",
            code_commit=record["code_commit"] or "",
            sessions=json.loads(record["sessions_json"]),
            evidence=evidence,
            todos=tuple(
                _todo_report(item)
                for item in self._store.get_todos(record["run_id"])
            ),
            image_profile=record["image_profile"],
            image_operation_id=record["image_operation_id"],
            image_status=record["image_status"],
            image_digest=record["image_digest"],
            image_artifacts=tuple(json.loads(record["image_artifacts_json"])),
            published_remote=record["published_remote"],
            published_ref=record["published_ref"],
            published_commit=record["published_commit"],
        )


class _RunStore:
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self._database = database
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    contract_hash TEXT NOT NULL UNIQUE,
                    goal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_stage TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    worktree TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    red_commit TEXT,
                    code_commit TEXT,
                    sessions_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    image_profile TEXT NOT NULL DEFAULT '',
                    image_operation_id TEXT NOT NULL DEFAULT '',
                    image_status TEXT NOT NULL DEFAULT '',
                    image_digest TEXT NOT NULL DEFAULT '',
                    image_artifacts_json TEXT NOT NULL DEFAULT '[]',
                    published_remote TEXT NOT NULL DEFAULT '',
                    published_ref TEXT NOT NULL DEFAULT '',
                    published_commit TEXT NOT NULL DEFAULT '',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_run_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    run_id TEXT NOT NULL,
                    todo_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_stage TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    worktree TEXT NOT NULL,
                    base_commit TEXT,
                    red_commit TEXT,
                    code_commit TEXT,
                    sessions_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, todo_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )

    def get_or_create(self, contract: _Contract, worktree: Path) -> Mapping[str, Any]:
        existing = self._find_by_hash(contract.contract_hash)
        if existing:
            if contract.image_profile_name and not existing["image_profile"]:
                self._update(
                    contract.run_id,
                    image_profile=contract.image_profile_name,
                )
            self._ensure_todos(contract)
            return self.get(contract.run_id)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, contract_hash, goal_id, status, active_stage,
                    repository, worktree, branch, sessions_json, evidence_json,
                    image_profile, created_at, updated_at
                ) VALUES (?, ?, ?, 'approved', '', ?, ?, ?, '{}', '[]', ?, ?, ?)
                """,
                (
                    contract.run_id,
                    contract.contract_hash,
                    contract.goal_id,
                    str(contract.repository),
                    str(worktree),
                    contract.branch,
                    contract.image_profile_name,
                    now,
                    now,
                ),
            )
        self._ensure_todos(contract)
        return self.get(contract.run_id)

    def _ensure_todos(self, contract: _Contract) -> None:
        if contract.legacy_single_todo:
            return
        now = _now()
        with self._connect() as connection:
            for todo in contract.todos:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO todos (
                        run_id, todo_id, title, status, active_stage,
                        branch, worktree, sessions_json, evidence_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', '', ?, '', '{}', '[]', ?, ?)
                    """,
                    (
                        contract.run_id,
                        todo.todo_id,
                        todo.title,
                        contract.todo_branch(todo),
                        now,
                        now,
                    ),
                )

    def get(self, run_id: str) -> Mapping[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return dict(row)

    def set_active_stage(self, run_id: str, stage: str) -> None:
        self._update(run_id, active_stage=stage, last_error=None)

    def set_run_status(self, run_id: str, status: str) -> None:
        self._update(run_id, status=status)

    def start_image(self, run_id: str, operation_id: str) -> None:
        self._update(
            run_id,
            status="waiting_image",
            image_operation_id=operation_id,
            image_status="queued",
            last_error=None,
        )

    def set_image_status(self, run_id: str, status: str) -> None:
        self._update(
            run_id,
            status="waiting_image",
            image_status=status,
            last_error=None,
        )

    def complete_image(
        self,
        run_id: str,
        digest: str,
        artifacts: Sequence[str],
    ) -> None:
        self._update(
            run_id,
            status="merge_ready",
            image_status="succeeded",
            image_digest=digest,
            image_artifacts_json=json.dumps(list(artifacts)),
            last_error=None,
        )

    def complete_publish(
        self,
        run_id: str,
        remote: str,
        ref: str,
        commit: str,
    ) -> None:
        self._update(
            run_id,
            published_remote=remote,
            published_ref=ref,
            published_commit=commit,
            last_error=None,
        )

    def record_interruption(self, run_id: str, error: str) -> None:
        self._update(run_id, last_error=error)

    def get_todos(self, run_id: str) -> List[Mapping[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM todos WHERE run_id = ? ORDER BY todo_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_todo(self, run_id: str, todo_id: str) -> Mapping[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM todos WHERE run_id = ? AND todo_id = ?",
                (run_id, todo_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Todo: {run_id}/{todo_id}")
        return dict(row)

    def prepare_todo(
        self,
        run_id: str,
        todo_id: str,
        branch: str,
        worktree: Path,
        base_commit: str,
    ) -> None:
        record = self.get_todo(run_id, todo_id)
        values: Dict[str, object] = {
            "branch": branch,
            "worktree": str(worktree),
        }
        if not record["base_commit"]:
            values["base_commit"] = base_commit
        self._update_todo(run_id, todo_id, **values)

    def set_todo_stage(self, run_id: str, todo_id: str, stage: str) -> None:
        self._update_todo(
            run_id,
            todo_id,
            active_stage=stage,
            last_error=None,
        )

    def record_todo_interruption(
        self,
        run_id: str,
        todo_id: str,
        error: str,
    ) -> None:
        self._update_todo(run_id, todo_id, last_error=error)

    def todo_checkpoint(
        self,
        run_id: str,
        todo_id: str,
        status: str,
        agent_result: AgentResult,
        role: str,
        evidence: CommandEvidence,
        red_commit: Optional[str] = None,
        code_commit: Optional[str] = None,
    ) -> None:
        record = self.get_todo(run_id, todo_id)
        sessions = json.loads(record["sessions_json"])
        sessions[role] = agent_result.session_id
        evidence_items = json.loads(record["evidence_json"])
        evidence_items.append(asdict(evidence))
        values: Dict[str, object] = {
            "status": status,
            "active_stage": "",
            "sessions_json": json.dumps(sessions, sort_keys=True),
            "evidence_json": json.dumps(evidence_items),
            "last_error": None,
        }
        if red_commit is not None:
            values["red_commit"] = red_commit
        if code_commit is not None:
            values["code_commit"] = code_commit
        self._update_todo(run_id, todo_id, **values)

    def integrate_todo(
        self,
        run_id: str,
        todo_id: str,
        evidence: CommandEvidence,
    ) -> None:
        record = self.get_todo(run_id, todo_id)
        evidence_items = json.loads(record["evidence_json"])
        evidence_items.append(asdict(evidence))
        self._update_todo(
            run_id,
            todo_id,
            status="integrated",
            active_stage="",
            evidence_json=json.dumps(evidence_items),
            last_error=None,
        )

    def checkpoint(
        self,
        run_id: str,
        status: str,
        agent_result: AgentResult,
        role: str,
        evidence: CommandEvidence,
        red_commit: Optional[str] = None,
        code_commit: Optional[str] = None,
    ) -> None:
        record = self.get(run_id)
        sessions = json.loads(record["sessions_json"])
        sessions[role] = agent_result.session_id
        evidence_items = json.loads(record["evidence_json"])
        evidence_items.append(asdict(evidence))
        values: Dict[str, object] = {
            "status": status,
            "active_stage": "",
            "sessions_json": json.dumps(sessions, sort_keys=True),
            "evidence_json": json.dumps(evidence_items),
            "last_error": None,
        }
        if red_commit is not None:
            values["red_commit"] = red_commit
        if code_commit is not None:
            values["code_commit"] = code_commit
        self._update(run_id, **values)

    def _find_by_hash(self, contract_hash: str) -> Optional[Mapping[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE contract_hash = ?",
                (contract_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _update(self, run_id: str, **values: object) -> None:
        values["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = list(values.values()) + [run_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                parameters,
            )

    def _update_todo(self, run_id: str, todo_id: str, **values: object) -> None:
        values["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = list(values.values()) + [run_id, todo_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE todos SET {assignments} WHERE run_id = ? AND todo_id = ?",
                parameters,
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _ensure_run_columns(connection: sqlite3.Connection) -> None:
        existing = {
            row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        columns = {
            "image_profile": "TEXT NOT NULL DEFAULT ''",
            "image_operation_id": "TEXT NOT NULL DEFAULT ''",
            "image_status": "TEXT NOT NULL DEFAULT ''",
            "image_digest": "TEXT NOT NULL DEFAULT ''",
            "image_artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
            "published_remote": "TEXT NOT NULL DEFAULT ''",
            "published_ref": "TEXT NOT NULL DEFAULT ''",
            "published_commit": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")


class _GitWorkspace:
    def __init__(
        self,
        repository: Path,
        worktree: Path,
        branch: str,
        base_ref: str,
    ) -> None:
        self.repository = repository
        self.worktree = worktree
        self.branch = branch
        self.base_ref = base_ref

    def ensure(self) -> None:
        if (self.worktree / ".git").exists():
            return
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = self._in_repository(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{self.branch}",
            check=False,
        ).returncode == 0
        if branch_exists:
            self._in_repository("worktree", "add", str(self.worktree), self.branch)
        else:
            self._in_repository(
                "worktree",
                "add",
                "-b",
                self.branch,
                str(self.worktree),
                self.base_ref,
            )

    def head(self) -> str:
        return self._in_worktree("rev-parse", "HEAD").stdout.strip()

    def restore_checkpoint(self, commit: str) -> None:
        self._in_worktree("reset", "--hard", commit)
        self._in_worktree("clean", "-fd")

    def changed_paths(self) -> List[str]:
        paths = set()
        for arguments in (
            ("diff", "--name-only", "-z"),
            ("diff", "--cached", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            output = self._in_worktree(*arguments).stdout
            paths.update(path for path in output.split("\0") if path)
        return sorted(paths)

    def commit(self, message: str) -> str:
        self._in_worktree("add", "-A")
        self._in_worktree("commit", "-m", message)
        return self.head()

    def contains(self, commit: str) -> bool:
        return self._in_worktree(
            "merge-base",
            "--is-ancestor",
            commit,
            "HEAD",
            check=False,
        ).returncode == 0

    def merge(self, branch: str) -> None:
        self._in_worktree("merge", "--no-ff", "--no-edit", branch)

    def _in_repository(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return _git(self.repository, *arguments, check=check)

    def _in_worktree(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return _git(self.worktree, *arguments, check=check)


def _load_contract(path: Path) -> _Contract:
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise ContractError(f"invalid Contract YAML: {error}") from error
    if not isinstance(data, dict):
        raise ContractError("Contract must be a YAML mapping")
    if data.get("schema_version") != 1:
        raise ContractError("Contract schema_version must be 1")

    approval = _mapping(data, "approval")
    if approval.get("status") != "approved":
        raise ContractError("Contract must be approved before execution")
    _text(approval, "approved_by")
    _approval_time(approval)

    goal = _mapping(data, "goal")
    goal_id = _identifier(goal, "id")
    acceptance_data = goal.get("acceptance")
    if not isinstance(acceptance_data, list) or not acceptance_data:
        raise ContractError("goal.acceptance must contain at least one item")
    acceptance = tuple(
        _Acceptance(
            test_id=_identifier(_as_mapping(item, "acceptance item"), "id"),
            statement=_text(_as_mapping(item, "acceptance item"), "statement"),
        )
        for item in acceptance_data
    )

    agent_value = data.get("agent", {})
    agent = _as_mapping(agent_value, "agent")
    agent_provider = agent.get("provider", "codex")
    if agent_provider not in {"codex", "claude-code"}:
        raise ContractError("agent.provider must be codex or claude-code")
    agent_model = agent.get("model")
    if agent_model is not None and (
        not isinstance(agent_model, str) or not agent_model.strip()
    ):
        raise ContractError("agent.model must be a non-empty model name")

    project = _mapping(data, "project")
    repository = _load_repository(path, project)

    legacy_single_todo = "todos" not in data
    if legacy_single_todo:
        todo_data = dict(_mapping(data, "todo"))
        todo_data["test"] = _mapping(data, "test")
        todo_data["depends_on"] = []
        todo_data["test_ids"] = [item.test_id for item in acceptance]
        todos = (_parse_todo(todo_data),)
    else:
        todos_data = data.get("todos")
        if not isinstance(todos_data, list) or not todos_data:
            raise ContractError("todos must contain at least one Todo")
        todos = tuple(
            _parse_todo(_as_mapping(item, "Todo")) for item in todos_data
        )
        _validate_todo_dag(todos, acceptance)

    candidate_value = data.get("candidate", {})
    candidate = _as_mapping(candidate_value, "candidate")
    image_profile_name = candidate.get("image_profile", "")
    if not isinstance(image_profile_name, str):
        raise ContractError("candidate.image_profile must be a profile name")
    todos, image_profile, candidate_publish = _authorize_contract(
        project,
        repository,
        todos,
        image_profile_name,
    )

    return _Contract(
        contract_hash=hashlib.sha256(raw).hexdigest(),
        goal_id=goal_id,
        goal_title=_text(goal, "title"),
        requirement=_text(goal, "requirement"),
        acceptance=acceptance,
        agent_provider=agent_provider,
        agent_model=agent_model,
        repository=repository,
        base_ref=_text(project, "base_ref"),
        todos=todos,
        legacy_single_todo=legacy_single_todo,
        image_profile_name=image_profile_name,
        image_profile=image_profile,
        candidate_publish=candidate_publish,
    )


def _load_repository(contract_path: Path, project: Mapping[str, object]) -> Path:
    repository = Path(_text(project, "repo")).expanduser()
    if not repository.is_absolute():
        repository = (contract_path.parent / repository).resolve()
    else:
        repository = repository.resolve()
    if not repository.is_dir():
        raise ContractError(f"project.repo is not a directory: {repository}")
    git_check = _git(repository, "rev-parse", "--is-inside-work-tree", check=False)
    if git_check.returncode != 0:
        raise ContractError(f"project.repo is not a Git repository: {repository}")
    return repository


def _authorize_contract(
    project: Mapping[str, object],
    repository: Path,
    todos: Sequence[_Todo],
    image_profile_name: str,
) -> Tuple[
    Tuple[_Todo, ...],
    Optional[ImageProfile],
    Optional[CandidatePublishProfile],
]:
    workflow_value = project.get("workflow", ".ai-workbench/workflow.yaml")
    if not isinstance(workflow_value, str) or not workflow_value:
        raise ContractError("project.workflow must be a non-empty path")
    workflow_path = Path(workflow_value).expanduser()
    if not workflow_path.is_absolute():
        workflow_path = repository / workflow_path
    workflow_path = workflow_path.resolve()
    try:
        workflow_path.relative_to(repository)
    except ValueError as error:
        raise ContractError("project.workflow must stay inside project.repo") from error
    try:
        policy = ProjectPolicy.load(workflow_path)
        authorized_todos = tuple(
            replace(
                todo,
                harness=policy.authorize(
                    repository,
                    todo.test_command,
                    todo.harness_name,
                ),
            )
            for todo in todos
        )
        return (
            authorized_todos,
            policy.authorize_image(image_profile_name),
            policy.authorize_publish(repository),
        )
    except ProjectConfigError as error:
        raise ContractError(str(error)) from error


def _parse_todo(data: Mapping[str, object]) -> _Todo:
    test = _mapping(data, "test")
    timeout_seconds = test.get("timeout_seconds", 600)
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise ContractError("test.timeout_seconds must be a positive integer")
    harness_name = test.get("harness", "")
    if not isinstance(harness_name, str):
        raise ContractError("test.harness must be a profile name")
    return _Todo(
        todo_id=_identifier(data, "id"),
        title=_text(data, "title"),
        depends_on=_string_list(data.get("depends_on"), "depends_on", allow_empty=True),
        test_ids=_string_list(data.get("test_ids"), "test_ids"),
        test_command=_string_list(test.get("command"), "test.command"),
        allowed_test_paths=_string_list(
            test.get("allowed_paths"),
            "test.allowed_paths",
        ),
        timeout_seconds=timeout_seconds,
        harness_name=harness_name,
        harness=None,
    )


def _validate_todo_dag(
    todos: Sequence[_Todo],
    acceptance: Sequence[_Acceptance],
) -> None:
    todo_ids = [todo.todo_id for todo in todos]
    if len(todo_ids) != len(set(todo_ids)):
        raise ContractError("Todo ids must be unique")
    known_acceptance = {item.test_id for item in acceptance}
    known_todos = set(todo_ids)
    for todo in todos:
        unknown_dependencies = set(todo.depends_on) - known_todos
        if unknown_dependencies:
            raise ContractError(
                f"Todo {todo.todo_id} has unknown dependencies: "
                + ", ".join(sorted(unknown_dependencies))
            )
        unknown_tests = set(todo.test_ids) - known_acceptance
        if unknown_tests:
            raise ContractError(
                f"Todo {todo.todo_id} has unknown test_ids: "
                + ", ".join(sorted(unknown_tests))
            )
    completed: set[str] = set()
    while len(completed) < len(todos):
        ready = [
            todo
            for todo in todos
            if todo.todo_id not in completed and set(todo.depends_on) <= completed
        ]
        if not ready:
            raise ContractError("Todo dependencies must form an acyclic graph")
        completed.update(todo.todo_id for todo in ready)


def _string_list(
    value: object,
    name: str,
    allow_empty: bool = False,
) -> Tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "a string list" if allow_empty else "a non-empty string list"
        raise ContractError(f"{name} must be {qualifier}")
    return tuple(value)


def _test_designer_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    return (
        "You are the fresh Test Designer for one approved Todo.\n"
        + _contract_prompt(contract, selected)
        + "\nAdd exactly the executable test needed for this acceptance boundary. "
        f"Modify only these path patterns: {', '.join(selected.allowed_test_paths)}. "
        "Do not implement production behavior and do not commit. Run the approved "
        "test command and leave the worktree in the expected RED state."
    )


def _implementer_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    return (
        "You are the fresh Implementer for one approved Todo.\n"
        + _contract_prompt(contract, selected)
        + "\nMake the existing approved RED test pass with the smallest production "
        "change. Do not modify any protected test path, do not expand scope, and do "
        "not commit. Run the approved test command before finishing."
    )


def _verifier_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    return (
        "You are a fresh independent Verifier for one Candidate.\n"
        + _contract_prompt(contract, selected)
        + "\nInspect the Candidate and run the approved test command. Do not modify, "
        "format, fix, or commit any file. Report the observed result and evidence."
    )


def _contract_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    acceptance = "\n".join(
        f"- {item.test_id}: {item.statement}"
        for item in contract.acceptance
        if item.test_id in selected.test_ids
    )
    command = json.dumps(selected.test_command)
    return (
        f"Goal: {contract.goal_title}\n"
        f"Requirement: {contract.requirement}\n"
        f"Todo: {selected.todo_id} - {selected.title}\n"
        f"Acceptance:\n{acceptance}\n"
        f"Approved test command: {command}"
    )


def _run_command(
    stage: str,
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandEvidence:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )
    return CommandEvidence(
        stage=stage,
        command=tuple(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        recorded_at=_now(),
    )


def _git(
    cwd: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _mapping(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _as_mapping(data.get(key), key)


def _as_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be a mapping")
    return value


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be a non-empty string")
    return value.strip()


def _identifier(data: Mapping[str, object], key: str) -> str:
    value = _text(data, key)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ContractError(
            f"{key} must contain only letters, numbers, dots, underscores, and dashes"
        )
    return value


def _approval_time(data: Mapping[str, object]) -> str:
    value = data.get("approved_at")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ContractError("approved_at must be an ISO timestamp")


def _required_string(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"run is missing checkpoint field: {key}")
    return value


def _todo_report(record: Mapping[str, Any]) -> TodoReport:
    evidence = tuple(
        CommandEvidence(
            stage=item["stage"],
            command=tuple(item["command"]),
            returncode=item["returncode"],
            stdout=item["stdout"],
            stderr=item["stderr"],
            recorded_at=item["recorded_at"],
            harness_profile=item.get("harness_profile", ""),
            environment=item.get("environment", ""),
            base_url=item.get("base_url", ""),
            artifacts=tuple(item.get("artifacts", [])),
        )
        for item in json.loads(record["evidence_json"])
    )
    return TodoReport(
        todo_id=record["todo_id"],
        status=record["status"],
        branch=record["branch"],
        worktree=record["worktree"],
        base_commit=record["base_commit"] or "",
        red_commit=record["red_commit"] or "",
        code_commit=record["code_commit"] or "",
        sessions=json.loads(record["sessions_json"]),
        evidence=evidence,
    )


def _todo_report_from_dict(value: object) -> TodoReport:
    if not isinstance(value, dict):
        raise ValueError("Todo report must be a mapping")
    evidence_data = value.get("evidence", [])
    sessions_data = value.get("sessions", {})
    if not isinstance(evidence_data, list) or not isinstance(sessions_data, dict):
        raise ValueError("Todo report evidence and sessions have invalid types")
    return TodoReport(
        todo_id=str(value["todo_id"]),
        status=str(value["status"]),
        branch=str(value["branch"]),
        worktree=str(value["worktree"]),
        base_commit=str(value.get("base_commit", "")),
        red_commit=str(value.get("red_commit", "")),
        code_commit=str(value.get("code_commit", "")),
        sessions={str(key): str(item) for key, item in sessions_data.items()},
        evidence=tuple(
            CommandEvidence(
                stage=str(item["stage"]),
                command=tuple(str(part) for part in item["command"]),
                returncode=int(item["returncode"]),
                stdout=str(item["stdout"]),
                stderr=str(item["stderr"]),
                recorded_at=str(item["recorded_at"]),
                harness_profile=str(item.get("harness_profile", "")),
                environment=str(item.get("environment", "")),
                base_url=str(item.get("base_url", "")),
                artifacts=tuple(str(path) for path in item.get("artifacts", [])),
            )
            for item in evidence_data
            if isinstance(item, dict)
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
