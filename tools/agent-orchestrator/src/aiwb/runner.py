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

from .agent import AgentAdapter, AgentRequest, AgentResult, ProviderQuotaError
from .browser import McpBrowserDiagnosticAdapter
from .evidence import (
    EvidencePayload,
    EvidencePruneReport,
    EvidenceReference,
    EvidenceStore,
)
from .harness import HarnessAdapter, HarnessError, HarnessRequest, LocalProcessHarness
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
from .repair import MergeConflictRepairRequest, MergeConflictRepairer


class ContractError(ValueError):
    pass


class GateError(RuntimeError):
    pass


class RunPaused(RuntimeError):
    def __init__(self, stop: "StopReport") -> None:
        super().__init__(
            f"Run paused for {stop.reason}"
            + (f" at {stop.boundary}" if stop.boundary else "")
        )
        self.stop = stop


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
class _ResourcePolicy:
    agent_attempts: Optional[int] = None
    wall_clock_seconds: Optional[float] = None
    harness_seconds: Optional[float] = None
    provider_tokens: Optional[int] = None


@dataclass(frozen=True)
class _Contract:
    contract_hash: str
    approval_status: str
    goal_id: str
    goal_title: str
    requirement: str
    acceptance: Tuple[_Acceptance, ...]
    agent_provider: str
    agent_model: Optional[str]
    repository: Path
    base_ref: str
    todos: Tuple[_Todo, ...]
    resources: _ResourcePolicy
    required_secrets: Tuple[str, ...]
    image_profile_name: str
    image_profile: Optional[ImageProfile]
    candidate_publish: Optional[CandidatePublishProfile]
    role_skill_texts: Mapping[str, Tuple[Tuple[str, str], ...]]
    policy: Mapping[str, object]
    policy_blockers: Tuple[Mapping[str, str], ...]

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


@dataclass(frozen=True)
class CommandEvidence:
    stage: str
    command: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    recorded_at: str
    duration_seconds: float = 0.0
    harness_profile: str = ""
    environment: str = ""
    base_url: str = ""
    artifacts: Tuple[str, ...] = field(default_factory=tuple)
    stdout_ref: Optional[EvidenceReference] = None
    stderr_ref: Optional[EvidenceReference] = None
    artifact_refs: Tuple[EvidenceReference, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StopReport:
    reason: str
    detail: str
    recorded_at: str
    resumable: bool
    boundary: str = ""
    todo_id: str = ""
    role: str = ""
    stage: str = ""
    provider: str = ""
    model: str = ""
    known_usage: Optional[Mapping[str, int]] = None


@dataclass(frozen=True)
class AttemptReport:
    role: str
    todo_id: str
    provider: str
    model: str
    session_id: str
    status: str
    elapsed_seconds: float
    recorded_at: str
    error: str = ""
    usage: Optional[Mapping[str, int]] = None


@dataclass(frozen=True)
class TodoExecutionEnvelope:
    todo_id: str
    layer: int
    agent_attempts: int
    harness_executions: int


@dataclass(frozen=True)
class ExecutionEnvelope:
    goal_id: str
    approval_status: str
    provider: str
    model: Optional[str]
    layers: Tuple[Tuple[str, ...], ...]
    todos: Tuple[TodoExecutionEnvelope, ...]
    deterministic: Mapping[str, object]
    conditional_paths: Tuple[Mapping[str, object], ...]
    provider_usage: Mapping[str, object]
    monetary_cost: Mapping[str, object]
    resource_boundaries: Mapping[str, object]
    concurrency_explanation: str
    policy: Mapping[str, object] = field(default_factory=dict)
    readiness: str = "ready"
    blockers: Tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "approval_status": self.approval_status,
            "provider": self.provider,
            "model": self.model,
            "layers": [list(layer) for layer in self.layers],
            "todos": [asdict(todo) for todo in self.todos],
            "deterministic": dict(self.deterministic),
            "conditional_paths": [
                dict(item) for item in self.conditional_paths
            ],
            "provider_usage": dict(self.provider_usage),
            "monetary_cost": dict(self.monetary_cost),
            "resource_boundaries": dict(self.resource_boundaries),
            "concurrency_explanation": self.concurrency_explanation,
            "policy": dict(self.policy),
            "readiness": self.readiness,
            "blockers": [dict(blocker) for blocker in self.blockers],
        }


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
    attempts: Tuple[AttemptReport, ...] = field(default_factory=tuple)
    evidence: Tuple[CommandEvidence, ...] = field(default_factory=tuple)
    repair_commits: Tuple[str, ...] = field(default_factory=tuple)
    stop: Optional[StopReport] = None


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
    attempts: Tuple[AttemptReport, ...] = field(default_factory=tuple)
    evidence: Tuple[CommandEvidence, ...] = field(default_factory=tuple)
    todos: Tuple[TodoReport, ...] = field(default_factory=tuple)
    stop: Optional[StopReport] = None
    execution_envelope: Mapping[str, object] = field(default_factory=dict)
    candidate_commit: str = ""
    image_profile: str = ""
    image_operation_id: str = ""
    image_status: str = ""
    image_digest: str = ""
    image_artifacts: Tuple[str, ...] = field(default_factory=tuple)
    image_artifact_refs: Tuple[EvidenceReference, ...] = field(default_factory=tuple)
    published_remote: str = ""
    published_ref: str = ""
    published_commit: str = ""

    def to_dict(self) -> Dict[str, object]:
        value = asdict(self)
        value["attempts"] = [asdict(item) for item in self.attempts]
        value["evidence"] = [asdict(item) for item in self.evidence]
        todo_values = []
        for todo in self.todos:
            item = asdict(todo)
            item["attempts"] = [asdict(attempt) for attempt in todo.attempts]
            item["evidence"] = [asdict(evidence) for evidence in todo.evidence]
            item["repair_commits"] = list(todo.repair_commits)
            todo_values.append(item)
        value["todos"] = todo_values
        consumption = _consumption_dict(
            attempts=self.attempts,
            todos=self.todos,
            fallback_evidence=self.evidence,
        )
        value["consumption"] = consumption
        value["consumption_comparison"] = _consumption_comparison(
            self.execution_envelope,
            consumption,
        )
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunReport":
        evidence_data = value.get("evidence", [])
        if not isinstance(evidence_data, list):
            raise ValueError("report evidence must be a list")
        evidence = tuple(
            _command_evidence_from_dict(item)
            for item in evidence_data
            if isinstance(item, dict)
        )
        sessions_data = value.get("sessions", {})
        if not isinstance(sessions_data, dict):
            raise ValueError("report sessions must be a mapping")
        attempts_data = value.get("attempts", [])
        if not isinstance(attempts_data, list):
            raise ValueError("report attempts must be a list")
        todos_data = value.get("todos", [])
        if not isinstance(todos_data, list):
            raise ValueError("report todos must be a list")
        execution_envelope = value.get("execution_envelope", {})
        if not isinstance(execution_envelope, dict):
            raise ValueError("report execution_envelope must be a mapping")
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
            attempts=tuple(
                _attempt_report_from_dict(item)
                for item in attempts_data
                if isinstance(item, dict)
            ),
            evidence=evidence,
            todos=tuple(_todo_report_from_dict(item) for item in todos_data),
            stop=_stop_report_from_dict(value.get("stop")),
            execution_envelope=dict(execution_envelope),
            candidate_commit=str(value.get("candidate_commit", "")),
            image_profile=str(value.get("image_profile", "")),
            image_operation_id=str(value.get("image_operation_id", "")),
            image_status=str(value.get("image_status", "")),
            image_digest=str(value.get("image_digest", "")),
            image_artifacts=tuple(
                str(item) for item in value.get("image_artifacts", [])
            ),
            image_artifact_refs=tuple(
                _evidence_reference_from_dict(item)
                for item in value.get("image_artifact_refs", [])
                if isinstance(item, dict)
            ),
            published_remote=str(value.get("published_remote", "")),
            published_ref=str(value.get("published_ref", "")),
            published_commit=str(value.get("published_commit", "")),
        )


def preview_execution(
    contract_path: Path,
    workflow_path: Optional[Path] = None,
) -> ExecutionEnvelope:
    """Preview an authorized Contract without creating execution state."""
    contract = _load_contract(
        Path(contract_path).expanduser().resolve(),
        require_approval=False,
        workflow_path=workflow_path,
        preflight=True,
    )
    return _execution_envelope(contract)


def preview_todo_graph(
    *,
    goal_id: str,
    approval_status: str,
    provider: str,
    model: Optional[str],
    todo_dependencies: Mapping[str, Sequence[str]],
    resources: Optional[Mapping[str, object]] = None,
    browser_diagnostics_configured: bool = False,
    image_build_configured: bool = False,
    candidate_publish_configured: bool = False,
) -> ExecutionEnvelope:
    """Estimate one Todo graph without creating a Contract or Run."""
    normalized = {
        str(todo_id): tuple(str(item) for item in dependencies)
        for todo_id, dependencies in todo_dependencies.items()
    }
    if not normalized:
        raise ContractError("execution preview requires at least one Todo")
    known = set(normalized)
    if any(set(dependencies) - known for dependencies in normalized.values()):
        raise ContractError("execution preview has unknown Todo dependencies")
    return _execution_envelope_from_graph(
        goal_id=goal_id,
        approval_status=approval_status,
        provider=provider,
        model=model,
        todo_dependencies=normalized,
        resources=_parse_resources(resources or {}),
        browser_diagnostics_configured=browser_diagnostics_configured,
        image_build_configured=image_build_configured,
        candidate_publish_configured=candidate_publish_configured,
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
        self._evidence_store = EvidenceStore(self._state_dir)
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
        self._conflict_repairer = MergeConflictRepairer(agent)
        self._image_poll_interval_seconds = image_poll_interval_seconds

    def prepare(self, contract_path: Path) -> RunReport:
        _, _, record = self._prepare(Path(contract_path))
        return self._report(record)

    def report(self, run_id: str) -> RunReport:
        return self._report(self._store.get(run_id))

    def evidence(self, run_id: str, artifact_id: str) -> EvidencePayload:
        report = self.report(run_id)
        evidence_items = (
            *report.evidence,
            *(item for todo in report.todos for item in todo.evidence),
        )
        references = [
            *(
                reference
                for item in evidence_items
                for reference in (
                    item.stdout_ref,
                    item.stderr_ref,
                    *item.artifact_refs,
                )
                if reference is not None
            ),
            *report.image_artifact_refs,
        ]
        reference = next(
            (
                item
                for item in references
                if item.artifact_id == artifact_id
            ),
            None,
        )
        if reference is None:
            raise KeyError(
                f"Evidence artifact {artifact_id!r} does not belong to Run {run_id!r}"
            )
        return self._evidence_store.read(artifact_id, reference=reference)

    def prune_evidence(self, older_than_days: int) -> EvidencePruneReport:
        return self._evidence_store.prune(older_than_days)

    def resume(self, run_id: str) -> RunReport:
        self._store.resume(run_id)
        return self.report(run_id)

    def sweep_kubernetes(self) -> JanitorReport:
        return self._kubernetes_janitor.sweep()

    def run(self, contract_path: Path) -> RunReport:
        contract, workspace, record = self._prepare(Path(contract_path))
        try:
            return self._run_dag(contract, workspace, record)
        except RunPaused:
            raise
        except Exception as error:
            self._record_failure(contract, error)
            raise

    def _record_failure(
        self,
        contract: _Contract,
        error: Exception,
    ) -> None:
        record = self._store.get(contract.run_id)
        detail = str(error)
        lowered = detail.lower()
        stage = _failure_stage(detail, str(record["active_stage"]))
        if isinstance(error, HarnessError) and "cleanup" in lowered:
            reason = "cleanup_failure"
            status = "failed_cleanup"
        elif (
            isinstance(error, GateError)
            and (
                str(record["status"]) == "candidate_accepting"
                or "final candidate" in lowered
            )
        ):
            reason = "acceptance_failure"
            status = "failed_acceptance"
        elif isinstance(error, (GateError, HarnessError)):
            reason = "harness_failure"
            status = "failed_harness"
        else:
            self._store.record_interruption(contract.run_id, detail)
            return

        todo_id = ""
        for todo in self._store.get_todos(contract.run_id):
            if todo["active_stage"] == stage:
                todo_id = str(todo["todo_id"])
                break
        if stage.startswith("candidate_acceptance:"):
            todo_id = stage.split(":", 1)[1]
        elif stage == "candidate_verifier":
            todo_id = "candidate"

        self._store.fail(
            contract.run_id,
            status,
            StopReport(
                reason=reason,
                detail=detail,
                recorded_at=_now(),
                resumable=False,
                todo_id=todo_id,
                stage=stage,
                provider=contract.agent_provider,
                model=contract.agent_model or "",
            ),
        )

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
        if record["status"] == "candidate_accepted":
            return self._promote_candidate(contract, candidate)

        if record["status"] != "candidate_accepting":
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
                conflict_paths = candidate.merge(contract.todo_branch(todo))
                if conflict_paths:
                    self._repair_todo_merge_conflict(
                        contract,
                        todo,
                        candidate,
                        conflict_paths,
                    )
            evidence = self._run_gate(
                contract=contract,
                todo=todo,
                stage=f"integrate:{todo.todo_id}",
                cwd=candidate.worktree,
            )
            if evidence.returncode != 0:
                self._store.record_todo_evidence(
                    contract.run_id,
                    todo.todo_id,
                    evidence,
                )
                raise GateError(
                    f"Candidate integration failed for {todo.todo_id}:\n"
                    + (evidence.stderr or evidence.stdout)
                )
            self._store.integrate_todo(contract.run_id, todo.todo_id, evidence)

    def _repair_todo_merge_conflict(
        self,
        contract: _Contract,
        todo: _Todo,
        candidate: "_GitWorkspace",
        conflict_paths: Tuple[str, ...],
    ) -> None:
        self._store.set_todo_stage(contract.run_id, todo.todo_id, "conflict_repairer")
        self._admit_agent(contract, todo.todo_id, "conflict_repairer")
        started = time.monotonic()
        try:
            result = self._conflict_repairer.repair(
                MergeConflictRepairRequest(
                    worktree=candidate.worktree,
                    todo_id=todo.todo_id,
                    prompt=_conflict_repair_prompt(contract, todo, conflict_paths),
                    conflict_paths=conflict_paths,
                    provider=contract.agent_provider,
                    model=contract.agent_model,
                    timeout_seconds=todo.timeout_seconds,
                )
            )
        except ProviderQuotaError as error:
            self._pause_for_provider_quota(
                contract,
                todo.todo_id,
                "conflict_repairer",
                error,
            )
        except Exception as error:
            self._store.record_todo_attempt(
                contract.run_id,
                todo.todo_id,
                AttemptReport(
                    role="conflict_repairer",
                    todo_id=todo.todo_id,
                    provider=contract.agent_provider,
                    model=contract.agent_model or "",
                    session_id="",
                    status="failed",
                    elapsed_seconds=time.monotonic() - started,
                    recorded_at=_now(),
                    error=str(error),
                ),
            )
            self._store.record_todo_interruption(
                contract.run_id,
                todo.todo_id,
                str(error),
            )
            raise
        self._store.record_todo_attempt(
            contract.run_id,
            todo.todo_id,
            AttemptReport(
                role="conflict_repairer",
                todo_id=todo.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model or "",
                session_id=result.agent_result.session_id,
                status="succeeded",
                elapsed_seconds=time.monotonic() - started,
                recorded_at=_now(),
                usage=_reported_usage(result.agent_result),
            ),
        )
        self._store.record_todo_repair(
            contract.run_id,
            todo.todo_id,
            "conflict_repairer",
            result.agent_result,
            result.merge_commit,
        )

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

    def _run_todo_agent(
        self,
        contract: _Contract,
        todo: _Todo,
        role: str,
        prompt: str,
        worktree: Path,
    ) -> AgentResult:
        self._admit_agent(contract, todo.todo_id, role)
        started = time.monotonic()
        try:
            result = self._agent.run(
                AgentRequest(
                    role=role,
                    prompt=prompt,
                    worktree=str(worktree),
                    todo_id=todo.todo_id,
                    provider=contract.agent_provider,
                    model=contract.agent_model,
                    timeout_seconds=todo.timeout_seconds,
                )
            )
        except ProviderQuotaError as error:
            self._pause_for_provider_quota(
                contract,
                todo.todo_id,
                role,
                error,
            )
        except Exception as error:
            self._store.record_todo_attempt(
                contract.run_id,
                todo.todo_id,
                AttemptReport(
                    role=role,
                    todo_id=todo.todo_id,
                    provider=contract.agent_provider,
                    model=contract.agent_model or "",
                    session_id="",
                    status="failed",
                    elapsed_seconds=time.monotonic() - started,
                    recorded_at=_now(),
                    error=str(error),
                ),
            )
            raise
        self._store.record_todo_attempt(
            contract.run_id,
            todo.todo_id,
            AttemptReport(
                role=role,
                todo_id=todo.todo_id,
                provider=contract.agent_provider,
                model=contract.agent_model or "",
                session_id=result.session_id,
                status="succeeded",
                elapsed_seconds=time.monotonic() - started,
                recorded_at=_now(),
                usage=_reported_usage(result),
            ),
        )
        return result

    def _create_todo_red_checkpoint(
        self,
        contract: _Contract,
        todo: _Todo,
        workspace: "_GitWorkspace",
    ) -> None:
        record = self._store.get_todo(contract.run_id, todo.todo_id)
        workspace.restore_checkpoint(_required_string(record, "base_commit"))
        self._store.set_todo_stage(contract.run_id, todo.todo_id, "test_designer")
        result = self._run_todo_agent(
            contract,
            todo,
            "test_designer",
            _test_designer_prompt(contract, todo),
            workspace.worktree,
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
            self._store.record_todo_evidence(
                contract.run_id,
                todo.todo_id,
                evidence,
            )
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
            result = self._run_todo_agent(
                contract,
                todo,
                "implementer",
                _implementer_prompt(contract, todo),
                workspace.worktree,
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
            self._store.record_todo_evidence(
                contract.run_id,
                todo.todo_id,
                evidence,
            )
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
        result = self._run_todo_agent(
            contract,
            todo,
            "verifier",
            _verifier_prompt(contract, todo),
            workspace.worktree,
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
            self._store.record_todo_evidence(
                contract.run_id,
                todo.todo_id,
                evidence,
            )
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
        worktree = self._state_dir / "worktrees" / contract.run_id / "candidate"
        workspace = _GitWorkspace(
            repository=contract.repository,
            worktree=worktree,
            branch=contract.branch,
            base_ref=contract.base_ref,
        )
        workspace.ensure()
        record = self._store.get_or_create(contract, workspace.worktree)
        return contract, workspace, record

    def _finish_candidate(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> RunReport:
        self._accept_candidate(contract, workspace)
        return self._promote_candidate(contract, workspace)

    def _promote_candidate(
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

    def _accept_candidate(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> None:
        record = self._store.get(contract.run_id)
        candidate_commit = record["candidate_commit"] or workspace.head()
        self._store.start_candidate_acceptance(
            contract.run_id,
            candidate_commit,
        )
        workspace.restore_checkpoint(candidate_commit)
        record = self._store.get(contract.run_id)

        if not record["candidate_verifier_completed"]:
            try:
                result, elapsed_seconds = self._run_candidate_verifier(
                    contract,
                    workspace,
                )
            except Exception:
                workspace.restore_checkpoint(candidate_commit)
                raise
            if (
                workspace.head() != candidate_commit
                or workspace.changed_paths()
            ):
                workspace.restore_checkpoint(candidate_commit)
                error = "Final Candidate verifier mutated the immutable Candidate"
                self._store.record_run_attempt(
                    contract.run_id,
                    AttemptReport(
                        role="candidate_verifier",
                        todo_id="candidate",
                        provider=contract.agent_provider,
                        model=contract.agent_model or "",
                        session_id=result.session_id,
                        status="rejected",
                        elapsed_seconds=elapsed_seconds,
                        recorded_at=_now(),
                        error=error,
                        usage=_reported_usage(result),
                    ),
                )
                self._store.record_interruption(contract.run_id, error)
                raise GateError(error)
            self._store.record_run_attempt(
                contract.run_id,
                AttemptReport(
                    role="candidate_verifier",
                    todo_id="candidate",
                    provider=contract.agent_provider,
                    model=contract.agent_model or "",
                    session_id=result.session_id,
                    status="succeeded",
                    elapsed_seconds=elapsed_seconds,
                    recorded_at=_now(),
                    usage=_reported_usage(result),
                ),
            )
            self._store.complete_candidate_verifier(contract.run_id, result)

        completed_stages = {
            item["stage"]
            for item in json.loads(
                self._store.get(contract.run_id)["evidence_json"]
            )
            if item["returncode"] == 0
        }
        for todo in contract.todos:
            stage = f"candidate_acceptance:{todo.todo_id}"
            if stage in completed_stages:
                continue
            workspace.restore_checkpoint(candidate_commit)
            try:
                evidence = self._run_gate(
                    contract=contract,
                    todo=todo,
                    stage=stage,
                    cwd=workspace.worktree,
                )
            finally:
                workspace.restore_checkpoint(candidate_commit)
            self._store.record_run_evidence(contract.run_id, evidence)
            if evidence.returncode != 0:
                error = (
                    f"Final Candidate acceptance failed for {todo.todo_id}:\n"
                    + (evidence.stderr or evidence.stdout)
                )
                self._store.record_interruption(contract.run_id, error)
                raise GateError(error)

        self._store.complete_candidate_acceptance(contract.run_id)

    def _run_candidate_verifier(
        self,
        contract: _Contract,
        workspace: "_GitWorkspace",
    ) -> Tuple[AgentResult, float]:
        self._admit_agent(contract, "candidate", "candidate_verifier")
        started = time.monotonic()
        try:
            result = self._agent.run(
                AgentRequest(
                    role="candidate_verifier",
                    prompt=_candidate_verifier_prompt(contract),
                    worktree=str(workspace.worktree),
                    todo_id="candidate",
                    sandbox="read-only",
                    provider=contract.agent_provider,
                    model=contract.agent_model,
                    timeout_seconds=max(
                        todo.timeout_seconds for todo in contract.todos
                    ),
                )
            )
        except ProviderQuotaError as error:
            self._pause_for_provider_quota(
                contract,
                "candidate",
                "candidate_verifier",
                error,
            )
        except Exception as error:
            self._store.record_run_attempt(
                contract.run_id,
                AttemptReport(
                    role="candidate_verifier",
                    todo_id="candidate",
                    provider=contract.agent_provider,
                    model=contract.agent_model or "",
                    session_id="",
                    status="failed",
                    elapsed_seconds=time.monotonic() - started,
                    recorded_at=_now(),
                    error=str(error),
                ),
            )
            self._store.record_interruption(contract.run_id, str(error))
            raise
        return result, time.monotonic() - started

    def _pause_for_provider_quota(
        self,
        contract: _Contract,
        todo_id: str,
        role: str,
        error: ProviderQuotaError,
    ) -> None:
        stop = StopReport(
            reason="provider_quota",
            detail=error.detail,
            recorded_at=_now(),
            resumable=True,
            boundary="provider_quota",
            todo_id=todo_id,
            role=role,
            provider=contract.agent_provider,
            model=contract.agent_model or "",
            known_usage=error.usage,
        )
        self._store.pause(contract.run_id, stop)
        raise RunPaused(stop)

    def _admit_agent(
        self,
        contract: _Contract,
        todo_id: str,
        role: str,
    ) -> None:
        self._admit_deadline(
            contract,
            todo_id=todo_id,
            role=role,
        )
        record = self._store.get(contract.run_id)
        attempts, _, tokens = self._store.resource_totals(contract.run_id)
        attempt_limit = contract.resources.agent_attempts
        attempt_consumed = attempts - int(record["resource_attempt_baseline"])
        if attempt_limit is not None and attempt_consumed >= attempt_limit:
            self._pause_for_boundary(
                contract,
                boundary="agent_attempts",
                consumed=attempt_consumed,
                limit=attempt_limit,
                todo_id=todo_id,
                role=role,
            )
        token_limit = contract.resources.provider_tokens
        token_consumed = tokens - int(record["resource_token_baseline"])
        if token_limit is not None and token_consumed >= token_limit:
            self._pause_for_boundary(
                contract,
                boundary="provider_tokens",
                consumed=token_consumed,
                limit=token_limit,
                todo_id=todo_id,
                role=role,
            )

    def _admit_harness(
        self,
        contract: _Contract,
        todo_id: str,
        stage: str,
    ) -> None:
        self._admit_deadline(
            contract,
            todo_id=todo_id,
            stage=stage,
        )
        limit = contract.resources.harness_seconds
        if limit is None:
            return
        record = self._store.get(contract.run_id)
        _, harness_seconds, _ = self._store.resource_totals(contract.run_id)
        consumed = harness_seconds - float(record["resource_harness_baseline"])
        if consumed >= limit:
            self._pause_for_boundary(
                contract,
                boundary="harness_seconds",
                consumed=consumed,
                limit=limit,
                todo_id=todo_id,
                stage=stage,
            )

    def _admit_deadline(
        self,
        contract: _Contract,
        *,
        todo_id: str,
        role: str = "",
        stage: str = "",
    ) -> None:
        limit = contract.resources.wall_clock_seconds
        if limit is None:
            return
        record = self._store.get(contract.run_id)
        started = datetime.fromisoformat(record["resource_window_started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed < limit:
            return
        stop = StopReport(
            reason="deadline",
            detail=(
                f"Wall-clock boundary reached: {elapsed:.6f}/{limit} seconds"
            ),
            recorded_at=_now(),
            resumable=True,
            boundary="wall_clock_seconds",
            todo_id=todo_id,
            role=role,
            stage=stage,
            provider=contract.agent_provider,
            model=contract.agent_model or "",
        )
        self._store.pause(contract.run_id, stop)
        raise RunPaused(stop)

    def _pause_for_boundary(
        self,
        contract: _Contract,
        *,
        boundary: str,
        consumed: float,
        limit: float,
        todo_id: str,
        role: str = "",
        stage: str = "",
    ) -> None:
        stop = StopReport(
            reason="resource_boundary",
            detail=(
                f"{boundary} boundary reached: {consumed}/{limit}; "
                f"next action is {role or stage}"
            ),
            recorded_at=_now(),
            resumable=True,
            boundary=boundary,
            todo_id=todo_id,
            role=role,
            stage=stage,
            provider=contract.agent_provider,
            model=contract.agent_model or "",
        )
        self._store.pause(contract.run_id, stop)
        raise RunPaused(stop)

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
                try:
                    operation_id = self._image_builder.start(request)
                finally:
                    self._sync_image_artifacts(contract.run_id, request.artifact_dir)
                self._store.start_image(contract.run_id, operation_id)
            try:
                status = self._image_builder.status(request, operation_id)
            finally:
                self._sync_image_artifacts(contract.run_id, request.artifact_dir)
            self._store.set_image_status(contract.run_id, status)
            if status == "succeeded":
                try:
                    result = self._image_builder.result(request, operation_id)
                finally:
                    self._sync_image_artifacts(
                        contract.run_id,
                        request.artifact_dir,
                    )
                artifact_refs = self._retain_artifact_paths(
                    contract.run_id,
                    "image",
                    result.artifacts,
                )
                self._store.complete_image(
                    contract.run_id,
                    result.digest,
                    result.artifacts,
                    artifact_refs,
                )
                record = self._store.get(contract.run_id)
                return self._publish_candidate(contract, workspace, record)
            time.sleep(self._image_poll_interval_seconds)

    def _sync_image_artifacts(self, run_id: str, artifact_dir: Path) -> None:
        paths = tuple(
            str(path)
            for path in sorted(artifact_dir.rglob("*"))
            if path.is_file()
        )
        if not paths:
            return
        self._store.record_image_artifacts(
            run_id,
            paths,
            self._retain_artifact_paths(run_id, "image-operation", paths),
        )

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
        self._admit_harness(contract, todo.todo_id, stage)
        if todo.harness is None:
            evidence = _run_command(
                stage=stage,
                command=todo.test_command,
                cwd=cwd,
                timeout_seconds=todo.timeout_seconds,
            )
        else:
            artifact_dir = (
                self._state_dir
                / "evidence"
                / contract.run_id
                / todo.todo_id
                / stage.replace(":", "-")
            )
            adapter = self._harnesses[todo.harness.kind]
            started = time.monotonic()
            try:
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
            except HarnessError as error:
                retained = self._retain_command_evidence(
                    contract.run_id,
                    todo.todo_id,
                    CommandEvidence(
                        stage=stage,
                        command=todo.test_command,
                        returncode=-1,
                        stdout="",
                        stderr=str(error),
                        recorded_at=_now(),
                        duration_seconds=time.monotonic() - started,
                        harness_profile=todo.harness.name,
                        environment=todo.harness.environment,
                        artifacts=tuple(
                            str(path)
                            for path in sorted(artifact_dir.rglob("*"))
                            if path.is_file()
                        ),
                    ),
                )
                self._store.record_todo_evidence(
                    contract.run_id,
                    todo.todo_id,
                    retained,
                )
                raise
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
                    diagnostic_detail += " Artifacts: " + ", ".join(
                        diagnostic.artifacts
                    )
                stderr = "\n".join(
                    part for part in (stderr, diagnostic_detail) if part
                )
                artifacts = artifacts + diagnostic.artifacts
            evidence = CommandEvidence(
                stage=stage,
                command=todo.test_command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=stderr,
                recorded_at=_now(),
                duration_seconds=time.monotonic() - started,
                harness_profile=todo.harness.name,
                environment=result.environment,
                base_url=result.base_url,
                artifacts=artifacts,
            )
        return self._retain_command_evidence(
            contract.run_id,
            todo.todo_id,
            evidence,
        )

    def _retain_command_evidence(
        self,
        run_id: str,
        todo_id: str,
        evidence: CommandEvidence,
    ) -> CommandEvidence:
        label = f"{run_id}/{todo_id}/{evidence.stage}"
        stdout, stdout_ref = self._evidence_store.retain_text(
            evidence.stdout,
            label=f"{label}/stdout",
        )
        stderr, stderr_ref = self._evidence_store.retain_text(
            evidence.stderr,
            label=f"{label}/stderr",
        )
        return replace(
            evidence,
            stdout=stdout,
            stderr=stderr,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            artifact_refs=self._retain_artifact_paths(
                run_id,
                f"{todo_id}/{evidence.stage}",
                evidence.artifacts,
            ),
        )

    def _retain_artifact_paths(
        self,
        run_id: str,
        label: str,
        paths: Sequence[str],
    ) -> Tuple[EvidenceReference, ...]:
        references = []
        for index, value in enumerate(paths, start=1):
            path = Path(value)
            if not path.is_file():
                continue
            references.append(
                self._evidence_store.retain_file(
                    path,
                    label=f"{run_id}/{label}/artifact-{index}-{path.name}",
                )
            )
        return tuple(references)

    def _report(self, record: Mapping[str, Any]) -> RunReport:
        evidence = tuple(
            _command_evidence_from_dict(item)
            for item in json.loads(record["evidence_json"])
        )
        todos = tuple(
            _todo_report(item)
            for item in self._store.get_todos(record["run_id"])
        )
        attempts = tuple(
            sorted(
                (
                    *(
                        _attempt_report_from_dict(item)
                        for item in json.loads(record["attempts_json"])
                    ),
                    *(attempt for todo in todos for attempt in todo.attempts),
                ),
                key=lambda item: item.recorded_at,
            )
        )
        sessions = json.loads(record["sessions_json"])
        red_commit = record["red_commit"] or ""
        code_commit = record["code_commit"] or ""
        if len(todos) == 1:
            todo = todos[0]
            red_commit = red_commit or todo.red_commit
            code_commit = code_commit or todo.code_commit
            sessions = {**todo.sessions, **sessions}
            evidence = tuple(
                item
                for item in todo.evidence
                if not item.stage.startswith("integrate:")
            ) + evidence
        return RunReport(
            run_id=record["run_id"],
            goal_id=record["goal_id"],
            status=record["status"],
            branch=record["branch"],
            worktree=record["worktree"],
            contract_hash=record["contract_hash"],
            red_commit=red_commit,
            code_commit=code_commit,
            sessions=sessions,
            attempts=attempts,
            evidence=evidence,
            todos=todos,
            stop=_stop_report_from_dict(json.loads(record["stop_json"])),
            execution_envelope=json.loads(record["execution_envelope_json"]),
            candidate_commit=record["candidate_commit"],
            image_profile=record["image_profile"],
            image_operation_id=record["image_operation_id"],
            image_status=record["image_status"],
            image_digest=record["image_digest"],
            image_artifacts=tuple(json.loads(record["image_artifacts_json"])),
            image_artifact_refs=tuple(
                _evidence_reference_from_dict(item)
                for item in json.loads(record["image_artifact_refs_json"])
            ),
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
                    attempts_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL,
                    stop_json TEXT NOT NULL DEFAULT 'null',
                    resource_window_started_at TEXT NOT NULL DEFAULT '',
                    resource_attempt_baseline INTEGER NOT NULL DEFAULT 0,
                    resource_harness_baseline REAL NOT NULL DEFAULT 0,
                    resource_token_baseline INTEGER NOT NULL DEFAULT 0,
                    execution_envelope_json TEXT NOT NULL DEFAULT '{}',
                    candidate_commit TEXT NOT NULL DEFAULT '',
                    candidate_verifier_completed INTEGER NOT NULL DEFAULT 0,
                    image_profile TEXT NOT NULL DEFAULT '',
                    image_operation_id TEXT NOT NULL DEFAULT '',
                    image_status TEXT NOT NULL DEFAULT '',
                    image_digest TEXT NOT NULL DEFAULT '',
                    image_artifacts_json TEXT NOT NULL DEFAULT '[]',
                    image_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
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
                    attempts_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL,
                    repair_commits_json TEXT NOT NULL DEFAULT '[]',
                    resume_status TEXT NOT NULL DEFAULT '',
                    stop_json TEXT NOT NULL DEFAULT 'null',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, todo_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            self._ensure_todo_columns(connection)

    def get_or_create(self, contract: _Contract, worktree: Path) -> Mapping[str, Any]:
        existing = self._find_by_hash(contract.contract_hash)
        if existing:
            if contract.image_profile_name and not existing["image_profile"]:
                self._update(
                    contract.run_id,
                    image_profile=contract.image_profile_name,
                )
            if not json.loads(existing["execution_envelope_json"]):
                self._update(
                    contract.run_id,
                    execution_envelope_json=json.dumps(
                        _execution_envelope(contract).to_dict(),
                        sort_keys=True,
                    ),
                )
            if not existing["resource_window_started_at"]:
                self._update(
                    contract.run_id,
                    resource_window_started_at=existing["created_at"],
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
                    resource_window_started_at, execution_envelope_json,
                    image_profile, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 'approved', '', ?, ?, ?, '{}', '[]', ?, ?, ?, ?, ?
                )
                """,
                (
                    contract.run_id,
                    contract.contract_hash,
                    contract.goal_id,
                    str(contract.repository),
                    str(worktree),
                    contract.branch,
                    now,
                    json.dumps(
                        _execution_envelope(contract).to_dict(),
                        sort_keys=True,
                    ),
                    contract.image_profile_name,
                    now,
                    now,
                ),
            )
        self._ensure_todos(contract)
        return self.get(contract.run_id)

    def _ensure_todos(self, contract: _Contract) -> None:
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

    def pause(
        self,
        run_id: str,
        stop: StopReport,
    ) -> None:
        status = {
            "resource_boundary": "paused_resource",
            "deadline": "paused_deadline",
            "provider_quota": "paused_provider_quota",
        }[stop.reason]
        if stop.todo_id and stop.todo_id != "candidate":
            todo = self.get_todo(run_id, stop.todo_id)
            resume_status = (
                todo["resume_status"]
                if todo["status"] == "paused"
                else todo["status"]
            )
            self._update_todo(
                run_id,
                stop.todo_id,
                status="paused",
                resume_status=resume_status,
                stop_json=json.dumps(asdict(stop), sort_keys=True),
                last_error=stop.detail,
            )
        self._update(
            run_id,
            status=status,
            active_stage=stop.stage or stop.role,
            stop_json=json.dumps(asdict(stop), sort_keys=True),
            last_error=stop.detail,
        )

    def resume(self, run_id: str) -> None:
        record = self.get(run_id)
        if not str(record["status"]).startswith("paused_"):
            raise ValueError(f"Run {run_id!r} is not paused")
        attempts, harness_seconds, tokens = self.resource_totals(run_id)
        for todo in self.get_todos(run_id):
            if todo["status"] != "paused":
                continue
            self._update_todo(
                run_id,
                todo["todo_id"],
                status=todo["resume_status"],
                resume_status="",
                stop_json="null",
                last_error=None,
            )
        self._update(
            run_id,
            status="running",
            active_stage="",
            stop_json="null",
            last_error=None,
            resource_window_started_at=_now(),
            resource_attempt_baseline=attempts,
            resource_harness_baseline=harness_seconds,
            resource_token_baseline=tokens,
        )

    def fail(
        self,
        run_id: str,
        status: str,
        stop: StopReport,
    ) -> None:
        if stop.todo_id and stop.todo_id != "candidate":
            try:
                self._update_todo(
                    run_id,
                    stop.todo_id,
                    stop_json=json.dumps(asdict(stop), sort_keys=True),
                    last_error=stop.detail,
                )
            except KeyError:
                pass
        self._update(
            run_id,
            status=status,
            active_stage=stop.stage,
            stop_json=json.dumps(asdict(stop), sort_keys=True),
            last_error=stop.detail,
        )

    def resource_totals(self, run_id: str) -> Tuple[int, float, int]:
        run = self.get(run_id)
        todo_records = self.get_todos(run_id)
        attempts = [
            *json.loads(run["attempts_json"]),
            *(
                item
                for todo in todo_records
                for item in json.loads(todo["attempts_json"])
            ),
        ]
        evidence = [
            *json.loads(run["evidence_json"]),
            *(
                item
                for todo in todo_records
                for item in json.loads(todo["evidence_json"])
            ),
        ]
        token_total = 0
        for attempt in attempts:
            usage = attempt.get("usage")
            if isinstance(usage, dict):
                value = usage.get("total_tokens")
                if isinstance(value, int):
                    token_total += value
        return (
            len(attempts),
            sum(float(item.get("duration_seconds", 0)) for item in evidence),
            token_total,
        )

    def start_candidate_acceptance(
        self,
        run_id: str,
        candidate_commit: str,
    ) -> None:
        record = self.get(run_id)
        persisted_commit = record["candidate_commit"]
        if persisted_commit and persisted_commit != candidate_commit:
            raise GateError(
                "Assembled Candidate commit changed during final acceptance"
            )
        self._update(
            run_id,
            status="candidate_accepting",
            active_stage=(
                "candidate_harness"
                if record["candidate_verifier_completed"]
                else "candidate_verifier"
            ),
            candidate_commit=persisted_commit or candidate_commit,
            last_error=None,
        )

    def record_run_attempt(
        self,
        run_id: str,
        attempt: AttemptReport,
    ) -> None:
        record = self.get(run_id)
        attempts = json.loads(record["attempts_json"])
        attempts.append(asdict(attempt))
        self._update(
            run_id,
            attempts_json=json.dumps(attempts, sort_keys=True),
        )

    def complete_candidate_verifier(
        self,
        run_id: str,
        result: AgentResult,
    ) -> None:
        record = self.get(run_id)
        sessions = json.loads(record["sessions_json"])
        sessions["candidate_verifier"] = result.session_id
        self._update(
            run_id,
            active_stage="candidate_harness",
            sessions_json=json.dumps(sessions, sort_keys=True),
            candidate_verifier_completed=1,
            last_error=None,
        )

    def record_run_evidence(
        self,
        run_id: str,
        evidence: CommandEvidence,
    ) -> None:
        record = self.get(run_id)
        evidence_items = json.loads(record["evidence_json"])
        evidence_items.append(asdict(evidence))
        self._update(
            run_id,
            evidence_json=json.dumps(evidence_items),
        )

    def complete_candidate_acceptance(self, run_id: str) -> None:
        self._update(
            run_id,
            status="candidate_accepted",
            active_stage="",
            last_error=None,
        )

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
        artifact_refs: Sequence[EvidenceReference],
    ) -> None:
        self.record_image_artifacts(run_id, artifacts, artifact_refs)
        self._update(
            run_id,
            status="merge_ready",
            image_status="succeeded",
            image_digest=digest,
            last_error=None,
        )

    def record_image_artifacts(
        self,
        run_id: str,
        artifacts: Sequence[str],
        artifact_refs: Sequence[EvidenceReference],
    ) -> None:
        record = self.get(run_id)
        known_paths = list(json.loads(record["image_artifacts_json"]))
        known_refs = [
            _evidence_reference_from_dict(item)
            for item in json.loads(record["image_artifact_refs_json"])
        ]
        merged_paths = list(dict.fromkeys((*known_paths, *artifacts)))
        refs_by_id = {
            reference.artifact_id: reference
            for reference in (*known_refs, *artifact_refs)
        }
        self._update(
            run_id,
            image_artifacts_json=json.dumps(merged_paths),
            image_artifact_refs_json=json.dumps(
                [asdict(reference) for reference in refs_by_id.values()],
                sort_keys=True,
            ),
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

    def record_todo_attempt(
        self,
        run_id: str,
        todo_id: str,
        attempt: AttemptReport,
    ) -> None:
        record = self.get_todo(run_id, todo_id)
        attempts = json.loads(record["attempts_json"])
        attempts.append(asdict(attempt))
        self._update_todo(
            run_id,
            todo_id,
            attempts_json=json.dumps(attempts, sort_keys=True),
        )

    def record_todo_evidence(
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
            evidence_json=json.dumps(evidence_items, sort_keys=True),
        )

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

    def record_todo_repair(
        self,
        run_id: str,
        todo_id: str,
        role: str,
        agent_result: AgentResult,
        merge_commit: str,
    ) -> None:
        record = self.get_todo(run_id, todo_id)
        sessions = json.loads(record["sessions_json"])
        sessions[role] = agent_result.session_id
        repair_commits = json.loads(record["repair_commits_json"])
        repair_commits.append(merge_commit)
        self._update_todo(
            run_id,
            todo_id,
            active_stage="",
            sessions_json=json.dumps(sessions, sort_keys=True),
            repair_commits_json=json.dumps(repair_commits),
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
            "attempts_json": "TEXT NOT NULL DEFAULT '[]'",
            "stop_json": "TEXT NOT NULL DEFAULT 'null'",
            "resource_window_started_at": "TEXT NOT NULL DEFAULT ''",
            "resource_attempt_baseline": "INTEGER NOT NULL DEFAULT 0",
            "resource_harness_baseline": "REAL NOT NULL DEFAULT 0",
            "resource_token_baseline": "INTEGER NOT NULL DEFAULT 0",
            "execution_envelope_json": "TEXT NOT NULL DEFAULT '{}'",
            "candidate_commit": "TEXT NOT NULL DEFAULT ''",
            "candidate_verifier_completed": "INTEGER NOT NULL DEFAULT 0",
            "image_profile": "TEXT NOT NULL DEFAULT ''",
            "image_operation_id": "TEXT NOT NULL DEFAULT ''",
            "image_status": "TEXT NOT NULL DEFAULT ''",
            "image_digest": "TEXT NOT NULL DEFAULT ''",
            "image_artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
            "image_artifact_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "published_remote": "TEXT NOT NULL DEFAULT ''",
            "published_ref": "TEXT NOT NULL DEFAULT ''",
            "published_commit": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_todo_columns(connection: sqlite3.Connection) -> None:
        existing = {
            row[1] for row in connection.execute("PRAGMA table_info(todos)").fetchall()
        }
        columns = {
            "attempts_json": "TEXT NOT NULL DEFAULT '[]'",
            "repair_commits_json": "TEXT NOT NULL DEFAULT '[]'",
            "resume_status": "TEXT NOT NULL DEFAULT ''",
            "stop_json": "TEXT NOT NULL DEFAULT 'null'",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE todos ADD COLUMN {name} {definition}")


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

    def merge(self, branch: str) -> Tuple[str, ...]:
        if self._merge_in_progress():
            if self._in_worktree("rev-parse", "MERGE_HEAD").stdout.strip() != (
                self._in_worktree("rev-parse", branch).stdout.strip()
            ):
                raise RuntimeError("Candidate has an unrelated merge in progress")
            return self._unmerged_paths()
        result = self._in_worktree(
            "merge",
            "--no-ff",
            "--no-edit",
            branch,
            check=False,
        )
        if result.returncode == 0:
            return ()
        conflict_paths = self._unmerged_paths()
        if conflict_paths:
            return conflict_paths
        raise RuntimeError(
            "Candidate merge failed without file conflicts:\n"
            + (result.stderr or result.stdout)
        )

    def _merge_in_progress(self) -> bool:
        return (
            self._in_worktree(
                "rev-parse",
                "-q",
                "--verify",
                "MERGE_HEAD",
                check=False,
            ).returncode
            == 0
        )

    def _unmerged_paths(self) -> Tuple[str, ...]:
        output = self._in_worktree(
            "diff",
            "--name-only",
            "--diff-filter=U",
            "-z",
        ).stdout
        return tuple(path for path in output.split("\0") if path)

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


def _load_contract(
    path: Path,
    *,
    require_approval: bool = True,
    workflow_path: Optional[Path] = None,
    preflight: bool = False,
    raw: Optional[bytes] = None,
) -> _Contract:
    if raw is None:
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
    approval_status = approval.get("status")
    if approval_status not in {"draft", "approved"}:
        raise ContractError("Contract approval.status must be draft or approved")
    if require_approval and approval_status != "approved":
        raise ContractError("Contract must be approved before execution")
    if approval_status == "approved":
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

    if "todos" not in data:
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
    (
        todos,
        image_profile,
        candidate_publish,
        role_skill_texts,
        policy_metadata,
    ) = _authorize_contract(
        project,
        repository,
        todos,
        image_profile_name,
        workflow_path=workflow_path,
        preflight=preflight,
    )
    resources = _parse_resources(data.get("resources", {}))
    required_secrets = _parse_required_secrets(data.get("required_secrets", []))

    return _Contract(
        contract_hash=_contract_hash(raw, role_skill_texts),
        approval_status=str(approval_status),
        goal_id=goal_id,
        goal_title=_text(goal, "title"),
        requirement=_text(goal, "requirement"),
        acceptance=acceptance,
        agent_provider=agent_provider,
        agent_model=agent_model,
        repository=repository,
        base_ref=_text(project, "base_ref"),
        todos=todos,
        resources=resources,
        required_secrets=required_secrets,
        image_profile_name=image_profile_name,
        image_profile=image_profile,
        candidate_publish=candidate_publish,
        role_skill_texts=role_skill_texts,
        policy={
            key: value
            for key, value in policy_metadata.items()
            if key != "blockers"
        },
        policy_blockers=tuple(policy_metadata.get("blockers", ())),
    )


def _parse_required_secrets(value: object) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError("required_secrets must be a list of references")
    references: List[str] = []
    reference_pattern = re.compile(
        r"^(?:env:[A-Za-z_][A-Za-z0-9_]*|"
        r"keychain:[A-Za-z0-9_][A-Za-z0-9._/@:-]*)$"
    )
    for item in value:
        if not isinstance(item, str) or not reference_pattern.fullmatch(item):
            raise ContractError(
                "required_secrets entries must use supported references such as "
                "env:OPENAI_API_KEY or keychain:aiwb/openai"
            )
        if item in references:
            raise ContractError(f"required_secrets contains duplicate reference {item!r}")
        references.append(item)
    return tuple(references)


def _parse_resources(value: object) -> _ResourcePolicy:
    resources = _as_mapping(value, "resources")

    def optional_positive_number(name: str) -> Optional[float]:
        item = resources.get(name)
        if item is None:
            return None
        if isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0:
            raise ContractError(f"resources.{name} must be a positive number")
        return float(item)

    def optional_positive_integer(name: str) -> Optional[int]:
        item = resources.get(name)
        if item is None:
            return None
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ContractError(f"resources.{name} must be a positive integer")
        return item

    return _ResourcePolicy(
        agent_attempts=optional_positive_integer("agent_attempts"),
        wall_clock_seconds=optional_positive_number("wall_clock_seconds"),
        harness_seconds=optional_positive_number("harness_seconds"),
        provider_tokens=optional_positive_integer("provider_tokens"),
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
    *,
    workflow_path: Optional[Path] = None,
    preflight: bool = False,
) -> Tuple[
    Tuple[_Todo, ...],
    Optional[ImageProfile],
    Optional[CandidatePublishProfile],
    Mapping[str, Tuple[Tuple[str, str], ...]],
    Mapping[str, object],
]:
    explicit = workflow_path is not None
    if explicit:
        resolved_workflow_path = Path(workflow_path).expanduser().resolve()
    else:
        workflow_value = project.get("workflow", ".ai-workbench/workflow.yaml")
        if not isinstance(workflow_value, str) or not workflow_value:
            raise ContractError("project.workflow must be a non-empty path")
        resolved_workflow_path = Path(workflow_value).expanduser()
        if not resolved_workflow_path.is_absolute():
            resolved_workflow_path = repository / resolved_workflow_path
        resolved_workflow_path = resolved_workflow_path.resolve()
        try:
            resolved_workflow_path.relative_to(repository)
        except ValueError as error:
            raise ContractError(
                "project.workflow must stay inside project.repo"
            ) from error
    try:
        policy = ProjectPolicy.load(resolved_workflow_path)
        blockers = []
        authorized_todos = []
        root_mismatch = policy.repository != repository
        if preflight and root_mismatch:
            blockers.append(
                {
                    "code": "policy_root_mismatch",
                    "message": (
                        "The selected policy root does not match the Contract "
                        "repository."
                    ),
                    "action": (
                        f"Review {resolved_workflow_path} and set project.root to "
                        f"{repository}."
                    ),
                }
            )
            authorized_todos.extend(todos)
        else:
            for todo in todos:
                try:
                    harness = policy.authorize(
                        repository,
                        todo.test_command,
                        todo.harness_name,
                    )
                except ProjectConfigError as error:
                    if (
                        preflight
                        and str(error)
                        == "Contract test command is not an approved project capability"
                    ):
                        blockers.append(
                            {
                                "code": "approved_command_missing",
                                "message": (
                                    f"Contract Todo {todo.todo_id} test command is not "
                                    "exactly approved by the selected policy."
                                ),
                                "action": (
                                    "Review and add the exact command to "
                                    f"{resolved_workflow_path} capabilities.commands "
                                    "with approved: true."
                                ),
                            }
                        )
                        harness = None
                    else:
                        raise
                authorized_todos.append(replace(todo, harness=harness))
        return (
            tuple(authorized_todos),
            policy.authorize_image(image_profile_name),
            policy.authorize_publish(repository),
            policy.role_skill_texts,
            {
                "path": str(resolved_workflow_path),
                "source": "explicit" if explicit else "repository",
                "candidate_commands": [
                    dict(command) for command in policy.candidate_commands
                ],
                "approved_commands": [
                    list(command) for command in policy.approved_commands
                ],
                "blockers": blockers,
            },
        )
    except ProjectConfigError as error:
        blocker = _preflight_policy_error(
            error,
            resolved_workflow_path,
        ) if preflight else None
        if blocker is not None:
            return _blocked_preflight_authorization(
                todos=todos,
                path=resolved_workflow_path,
                explicit=explicit,
                blocker=blocker,
            )
        raise ContractError(str(error)) from error


def _preflight_policy_error(
    error: ProjectConfigError,
    path: Path,
) -> Optional[Mapping[str, str]]:
    message = str(error)
    if (
        message == "project policy requires an approved command"
        or (
            message.startswith("project command ")
            and message.endswith(" must be approved")
        )
    ):
        return {
            "code": "approved_command_missing",
            "message": message,
            "action": (
                "Review and add the exact Contract test command to "
                f"{path} capabilities.commands with approved: true."
            ),
        }
    if message in {
        "project policy status must be approved",
        "project must be explicitly trusted",
    }:
        return {
            "code": "policy_not_approved",
            "message": message,
            "action": (
                f"Review {path}, explicitly approve its trusted project and "
                "capabilities, then rerun preflight."
            ),
        }
    if message.startswith(
        (
            "production Harness profile is forbidden:",
            "production image profile is forbidden:",
        )
    ):
        return {
            "code": "production_target",
            "message": message,
            "action": (
                f"Review {path} and use only local or non-production "
                "Harness and image profiles."
            ),
        }
    return None


def _blocked_preflight_authorization(
    *,
    todos: Sequence[_Todo],
    path: Path,
    explicit: bool,
    blocker: Mapping[str, str],
) -> Tuple[
    Tuple[_Todo, ...],
    Optional[ImageProfile],
    Optional[CandidatePublishProfile],
    Mapping[str, Tuple[Tuple[str, str], ...]],
    Mapping[str, object],
]:
    return (
        tuple(todos),
        None,
        None,
        {},
        {
            **_policy_display_metadata(
                _read_policy_mapping(path),
                path,
                explicit,
            ),
            "blockers": [dict(blocker)],
        },
    )


def _read_policy_mapping(path: Path) -> Mapping[str, object]:
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot read project policy: {error}") from error
    if not isinstance(value, dict):
        raise ContractError("project policy must be a YAML mapping")
    return value


def _policy_display_metadata(
    data: Mapping[str, object],
    path: Path,
    explicit: bool,
) -> Mapping[str, object]:
    suggestions = data.get("suggestions")
    suggestions = suggestions if isinstance(suggestions, dict) else {}
    candidate_values = suggestions.get("commands")
    candidate_values = (
        candidate_values if isinstance(candidate_values, dict) else {}
    )
    candidates = []
    for name, definition in candidate_values.items():
        if isinstance(name, str) and isinstance(definition, dict):
            argv = definition.get("argv")
            reason = definition.get("reason", "")
            if isinstance(argv, list) and isinstance(reason, str):
                candidates.append(
                    {"name": name, "argv": list(argv), "reason": reason}
                )
    capabilities = data.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    command_values = capabilities.get("commands")
    command_values = command_values if isinstance(command_values, dict) else {}
    approved = [
        list(definition["argv"])
        for definition in command_values.values()
        if isinstance(definition, dict)
        and definition.get("approved") is True
        and isinstance(definition.get("argv"), list)
    ]
    return {
        "path": str(path),
        "source": "explicit" if explicit else "repository",
        "candidate_commands": candidates,
        "approved_commands": approved,
    }


def _contract_hash(
    raw_contract: bytes,
    role_skill_texts: Mapping[str, Tuple[Tuple[str, str], ...]],
) -> str:
    guidance = json.dumps(role_skill_texts, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw_contract + b"\0" + guidance).hexdigest()


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


def _execution_envelope(contract: _Contract) -> ExecutionEnvelope:
    envelope = _execution_envelope_from_graph(
        goal_id=contract.goal_id,
        approval_status=contract.approval_status,
        provider=contract.agent_provider,
        model=contract.agent_model,
        todo_dependencies={
            todo.todo_id: todo.depends_on for todo in contract.todos
        },
        resources=contract.resources,
        browser_diagnostics_configured=any(
            todo.harness is not None
            and todo.harness.browser_diagnostic is not None
            for todo in contract.todos
        ),
        image_build_configured=contract.image_profile is not None,
        candidate_publish_configured=contract.candidate_publish is not None,
    )
    return replace(
        envelope,
        policy=contract.policy,
        readiness="blocked" if contract.policy_blockers else "ready",
        blockers=contract.policy_blockers,
    )


def _execution_envelope_from_graph(
    *,
    goal_id: str,
    approval_status: str,
    provider: str,
    model: Optional[str],
    todo_dependencies: Mapping[str, Sequence[str]],
    resources: _ResourcePolicy,
    browser_diagnostics_configured: bool,
    image_build_configured: bool,
    candidate_publish_configured: bool,
) -> ExecutionEnvelope:
    completed: set[str] = set()
    layers: List[Tuple[str, ...]] = []
    todo_layers: Dict[str, int] = {}
    while len(completed) < len(todo_dependencies):
        ready = tuple(
            sorted(
                todo_id
                for todo_id, dependencies in todo_dependencies.items()
                if todo_id not in completed
                and set(dependencies) <= completed
            )
        )
        if not ready:
            raise ContractError("Todo dependencies must form an acyclic graph")
        layer_index = len(layers)
        layers.append(ready)
        for todo_id in ready:
            todo_layers[todo_id] = layer_index
        completed.update(ready)

    todo_count = len(todo_dependencies)
    conditional_paths: Tuple[Mapping[str, object], ...] = (
        {
            "name": "conflict_repair",
            "unit": "agent_attempt",
            "trigger": "an integrated Todo produces a merge conflict",
            "configured": True,
        },
        {
            "name": "browser_diagnosis",
            "unit": "diagnostic_invocation",
            "trigger": "a formal browser Harness pass fails",
            "configured": browser_diagnostics_configured,
        },
        {
            "name": "retry",
            "unit": "agent_attempt_or_harness_execution",
            "trigger": "an execution step fails and policy permits retry",
            "configured": False,
        },
        {
            "name": "image_build",
            "unit": "external_operation",
            "trigger": "final Candidate acceptance succeeds",
            "configured": image_build_configured,
        },
        {
            "name": "candidate_publish",
            "unit": "external_mutation",
            "trigger": "final Candidate acceptance and image promotion succeed",
            "configured": candidate_publish_configured,
        },
    )
    return ExecutionEnvelope(
        goal_id=goal_id,
        approval_status=approval_status,
        provider=provider,
        model=model,
        layers=tuple(layers),
        todos=tuple(
            TodoExecutionEnvelope(
                todo_id=todo_id,
                layer=todo_layers[todo_id],
                agent_attempts=3,
                harness_executions=4,
            )
            for todo_id in todo_dependencies
        ),
        deterministic={
            "agent_attempts": todo_count * 3 + 1,
            "agent_attempts_by_role": {
                "test_designer": todo_count,
                "implementer": todo_count,
                "verifier": todo_count,
                "candidate_verifier": 1,
            },
            "harness_executions": todo_count * 5,
            "harness_executions_by_stage": {
                "red": todo_count,
                "green": todo_count,
                "verify": todo_count,
                "integrate": todo_count,
                "candidate_acceptance": todo_count,
            },
            "final_candidate_acceptance": {
                "agent_attempts": 1,
                "harness_executions": todo_count,
            },
        },
        conditional_paths=conditional_paths,
        provider_usage={
            "status": "unknown",
            "unit": "provider_reported_tokens",
        },
        monetary_cost={"status": "unknown", "currency": None},
        resource_boundaries={
            name: value
            for name, value in {
                "agent_attempts": resources.agent_attempts,
                "wall_clock_seconds": resources.wall_clock_seconds,
                "harness_seconds": resources.harness_seconds,
                "provider_tokens": resources.provider_tokens,
            }.items()
            if value is not None
        },
        concurrency_explanation=(
            "Independent Todo layers may reduce elapsed wall-clock time; "
            "concurrency does not reduce total consumption."
        ),
    )


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
        + _role_guidance(contract, "test_designer")
        + "\nAdd exactly the executable test needed for this acceptance boundary. "
        f"Modify only these path patterns: {', '.join(selected.allowed_test_paths)}. "
        "Do not implement production behavior and do not commit. Run the approved "
        "test command and leave the worktree in the expected RED state."
    )


def _role_guidance(contract: _Contract, role: str) -> str:
    entries = contract.role_skill_texts.get(role, ())
    if not entries:
        return ""
    rendered = "\n\n".join(
        f"--- {path} ---\n{content.rstrip()}" for path, content in entries
    )
    return (
        "\nProject-approved role guidance follows. It is advisory: the Contract and "
        "the role safety constraints take precedence on conflict.\n"
        + rendered
        + "\n"
    )


def _implementer_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    return (
        "You are the fresh Implementer for one approved Todo.\n"
        + _contract_prompt(contract, selected)
        + _role_guidance(contract, "implementer")
        + "\nMake the existing approved RED test pass with the smallest production "
        "change. Do not modify any protected test path, do not expand scope, and do "
        "not commit. Run the approved test command before finishing."
    )


def _conflict_repair_prompt(
    contract: _Contract,
    todo: _Todo,
    conflict_paths: Tuple[str, ...],
) -> str:
    return (
        "You are the fresh Conflict Repairer for one approved Candidate integration.\n"
        + _contract_prompt(contract, todo)
        + _role_guidance(contract, "conflict_repairer")
        + "\nResolve only these existing Git conflict paths: "
        + ", ".join(conflict_paths)
        + ". Preserve the accepted behavior from both branches. Do not edit any "
        "other path, do not stage or commit, and do not change the target branch. "
        "Run the approved test command before finishing."
    )


def _verifier_prompt(contract: _Contract, todo: Optional[_Todo] = None) -> str:
    selected = todo or contract.todos[0]
    return (
        "You are a fresh independent Verifier for one Candidate.\n"
        + _contract_prompt(contract, selected)
        + _role_guidance(contract, "verifier")
        + "\nInspect the Candidate and run the approved test command. Do not modify, "
        "format, fix, or commit any file. Report the observed result and evidence."
    )


def _candidate_verifier_prompt(contract: _Contract) -> str:
    acceptance = "\n".join(
        f"- {item.test_id}: {item.statement}"
        for item in contract.acceptance
    )
    boundary = "\n".join(
        f"- {todo.todo_id} ({todo.harness_name or 'direct-command'}): "
        f"{json.dumps(todo.test_command)}"
        for todo in contract.todos
    )
    return (
        "You are the fresh final Verifier for the fully assembled Candidate.\n"
        f"Goal: {contract.goal_title}\n"
        f"Requirement: {contract.requirement}\n"
        f"Acceptance:\n{acceptance}\n"
        f"Complete approved Harness boundary:\n{boundary}\n"
        + _role_guidance(contract, "verifier")
        + "\nInspect the immutable assembled Candidate and the complete acceptance "
        "boundary. Do not modify, format, fix, stage, or commit any file. The "
        "orchestrator runs every approved Harness command after this independent "
        "review; report any cross-Todo risk or inconsistency you observe."
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
    started = time.monotonic()
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
        duration_seconds=time.monotonic() - started,
        harness_profile="direct-command",
        environment="local",
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
        _command_evidence_from_dict(item)
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
        attempts=tuple(
            _attempt_report_from_dict(item)
            for item in json.loads(record["attempts_json"])
        ),
        evidence=evidence,
        repair_commits=tuple(json.loads(record["repair_commits_json"])),
        stop=_stop_report_from_dict(json.loads(record["stop_json"])),
    )


def _todo_report_from_dict(value: object) -> TodoReport:
    if not isinstance(value, dict):
        raise ValueError("Todo report must be a mapping")
    evidence_data = value.get("evidence", [])
    sessions_data = value.get("sessions", {})
    attempts_data = value.get("attempts", [])
    repair_commits_data = value.get("repair_commits", [])
    if (
        not isinstance(evidence_data, list)
        or not isinstance(sessions_data, dict)
        or not isinstance(attempts_data, list)
        or not isinstance(repair_commits_data, list)
    ):
        raise ValueError(
            "Todo report attempts, evidence, sessions, and repairs have invalid types"
        )
    return TodoReport(
        todo_id=str(value["todo_id"]),
        status=str(value["status"]),
        branch=str(value["branch"]),
        worktree=str(value["worktree"]),
        base_commit=str(value.get("base_commit", "")),
        red_commit=str(value.get("red_commit", "")),
        code_commit=str(value.get("code_commit", "")),
        sessions={str(key): str(item) for key, item in sessions_data.items()},
        attempts=tuple(
            _attempt_report_from_dict(item)
            for item in attempts_data
            if isinstance(item, dict)
        ),
        evidence=tuple(
            _command_evidence_from_dict(item)
            for item in evidence_data
            if isinstance(item, dict)
        ),
        repair_commits=tuple(str(commit) for commit in repair_commits_data),
        stop=_stop_report_from_dict(value.get("stop")),
    )


def _command_evidence_from_dict(
    value: Mapping[str, object],
) -> CommandEvidence:
    return CommandEvidence(
        stage=str(value["stage"]),
        command=tuple(str(part) for part in value["command"]),
        returncode=int(value["returncode"]),
        stdout=str(value.get("stdout", "")),
        stderr=str(value.get("stderr", "")),
        recorded_at=str(value["recorded_at"]),
        duration_seconds=float(value.get("duration_seconds", 0)),
        harness_profile=str(value.get("harness_profile", "")),
        environment=str(value.get("environment", "")),
        base_url=str(value.get("base_url", "")),
        artifacts=tuple(str(path) for path in value.get("artifacts", [])),
        stdout_ref=_optional_evidence_reference(value.get("stdout_ref")),
        stderr_ref=_optional_evidence_reference(value.get("stderr_ref")),
        artifact_refs=tuple(
            _evidence_reference_from_dict(item)
            for item in value.get("artifact_refs", [])
            if isinstance(item, dict)
        ),
    )


def _optional_evidence_reference(value: object) -> Optional[EvidenceReference]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Evidence reference must be a mapping")
    return _evidence_reference_from_dict(value)


def _evidence_reference_from_dict(
    value: Mapping[str, object],
) -> EvidenceReference:
    return EvidenceReference(
        artifact_id=str(value["artifact_id"]),
        sha256=str(value["sha256"]),
        size_bytes=int(value["size_bytes"]),
        media_type=str(value.get("media_type", "application/octet-stream")),
        label=str(value.get("label", "")),
    )


def _stop_report_from_dict(value: object) -> Optional[StopReport]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Run stop must be a mapping")
    known_usage = value.get("known_usage")
    if known_usage is not None and not isinstance(known_usage, dict):
        raise ValueError("Run stop known_usage must be a mapping")
    return StopReport(
        reason=str(value["reason"]),
        detail=str(value.get("detail", "")),
        recorded_at=str(value["recorded_at"]),
        resumable=bool(value.get("resumable", False)),
        boundary=str(value.get("boundary", "")),
        todo_id=str(value.get("todo_id", "")),
        role=str(value.get("role", "")),
        stage=str(value.get("stage", "")),
        provider=str(value.get("provider", "")),
        model=str(value.get("model", "")),
        known_usage=(
            {str(key): int(item) for key, item in known_usage.items()}
            if isinstance(known_usage, dict)
            else None
        ),
    )


def _attempt_report_from_dict(value: Mapping[str, object]) -> AttemptReport:
    usage = value.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("Attempt usage must be a mapping")
    return AttemptReport(
        role=str(value["role"]),
        todo_id=str(value.get("todo_id", "")),
        provider=str(value["provider"]),
        model=str(value.get("model", "")),
        session_id=str(value.get("session_id", "")),
        status=str(value["status"]),
        elapsed_seconds=float(value.get("elapsed_seconds", 0)),
        recorded_at=str(value["recorded_at"]),
        error=str(value.get("error", "")),
        usage=(
            {str(key): int(item) for key, item in usage.items()}
            if isinstance(usage, dict)
            else None
        ),
    )


def _reported_usage(result: AgentResult) -> Optional[Mapping[str, int]]:
    usage = getattr(result, "usage", {})
    return dict(usage) if usage else None


def _failure_stage(detail: str, fallback: str) -> str:
    candidate_match = re.search(
        r"Final Candidate acceptance failed for ([^:\n]+)",
        detail,
    )
    if candidate_match:
        return f"candidate_acceptance:{candidate_match.group(1)}"
    lowered = detail.lower()
    if "final candidate verifier" in lowered:
        return "candidate_verifier"
    if "green gate" in lowered:
        return "green"
    if "red gate" in lowered:
        return "red"
    if "verification gate" in lowered:
        return "verify"
    if "candidate integration failed" in lowered:
        return "integrate"
    if "cleanup" in lowered:
        return "cleanup"
    return fallback


def _consumption_dict(
    *,
    attempts: Sequence[AttemptReport],
    todos: Sequence[TodoReport],
    fallback_evidence: Sequence[CommandEvidence],
) -> Dict[str, object]:
    agent_groups: Dict[Tuple[str, str, str, str], List[AttemptReport]] = {}
    for attempt in attempts:
        key = (
            attempt.todo_id,
            attempt.role,
            attempt.provider,
            attempt.model,
        )
        agent_groups.setdefault(key, []).append(attempt)

    agents: List[Dict[str, object]] = []
    for (todo_id, role, provider, model), group in sorted(agent_groups.items()):
        usage_totals: Dict[str, int] = {}
        for item in group:
            if item.usage is None:
                continue
            for key, value in item.usage.items():
                usage_totals[key] = usage_totals.get(key, 0) + value
        agents.append(
            {
                "todo_id": todo_id,
                "role": role,
                "provider": provider,
                "model": model or None,
                "attempt_count": len(group),
                "succeeded_count": sum(
                    item.status == "succeeded" for item in group
                ),
                "failed_count": sum(item.status == "failed" for item in group),
                "rejected_count": sum(
                    item.status == "rejected" for item in group
                ),
                "elapsed_seconds": sum(item.elapsed_seconds for item in group),
                "usage": (
                    usage_totals
                    if all(item.usage is not None for item in group)
                    else None
                ),
                "usage_reported_attempts": sum(
                    item.usage is not None for item in group
                ),
                "usage_unknown_attempts": sum(
                    item.usage is None for item in group
                ),
            }
        )

    harness_groups: Dict[
        Tuple[str, str, str],
        List[CommandEvidence],
    ] = {}
    if todos:
        evidence_with_todo = [
            (todo.todo_id, item)
            for todo in todos
            for item in todo.evidence
        ]
        evidence_with_todo.extend(
            (
                item.stage.removeprefix("candidate_acceptance:"),
                item,
            )
            for item in fallback_evidence
            if item.stage.startswith("candidate_acceptance:")
        )
    else:
        evidence_with_todo = [("", item) for item in fallback_evidence]
    for todo_id, item in evidence_with_todo:
        key = (
            todo_id,
            item.harness_profile or "unknown",
            item.environment or "unknown",
        )
        harness_groups.setdefault(key, []).append(item)

    harnesses = [
        {
            "todo_id": todo_id,
            "profile": profile,
            "environment": environment,
            "execution_count": len(group),
            "duration_seconds": sum(item.duration_seconds for item in group),
        }
        for (todo_id, profile, environment), group in sorted(
            harness_groups.items()
        )
    ]
    return {"agents": agents, "harnesses": harnesses}


def _consumption_comparison(
    execution_envelope: Mapping[str, object],
    consumption: Mapping[str, object],
) -> Dict[str, object]:
    deterministic = execution_envelope.get("deterministic", {})
    if not isinstance(deterministic, dict):
        deterministic = {}
    planned_agents = deterministic.get("agent_attempts")
    planned_harnesses = deterministic.get("harness_executions")
    agents = consumption.get("agents", [])
    harnesses = consumption.get("harnesses", [])
    actual_agents = sum(
        int(item.get("attempt_count", 0))
        for item in agents
        if isinstance(item, dict)
    ) if isinstance(agents, list) else 0
    actual_harnesses = sum(
        int(item.get("execution_count", 0))
        for item in harnesses
        if isinstance(item, dict)
    ) if isinstance(harnesses, list) else 0
    planned = {
        "agent_attempts": (
            int(planned_agents)
            if isinstance(planned_agents, int)
            else None
        ),
        "harness_executions": (
            int(planned_harnesses)
            if isinstance(planned_harnesses, int)
            else None
        ),
    }
    actual = {
        "agent_attempts": actual_agents,
        "harness_executions": actual_harnesses,
    }
    return {
        "planned": planned,
        "actual": actual,
        "variance": {
            key: actual[key] - value if value is not None else None
            for key, value in planned.items()
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
