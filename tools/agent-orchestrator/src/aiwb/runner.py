"""Compatibility-free entry points for harness-native Run execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from ._harness_apply import _write_json_atomically
from .harness_native import (
    AdmissionError,
    ContractError,
    GoalRunner,
    RunReport,
    _approval_artifact_path,
    _execution_digest,
    _json_value,
    _load_execution_approval,
    _resolve_execution_input,
)


@dataclass(frozen=True)
class ExecutionEnvelope:
    goal_id: str
    approval_status: str
    approval_artifact: str
    execution_digest: str
    execution: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "approval_status": self.approval_status,
            "approval_artifact": self.approval_artifact,
            "execution_digest": self.execution_digest,
            "execution": _json_value(self.execution),
        }


@dataclass(frozen=True)
class ExecutionApproval:
    status: str
    approved_by: str
    approved_at: str
    artifact_path: str
    execution_digest: str
    execution: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "artifact_path": self.artifact_path,
            "execution_digest": self.execution_digest,
            "execution": _json_value(self.execution),
        }


def preview_execution(
    contract_path: Path,
    *,
    workflow_path: Optional[Path] = None,
) -> ExecutionEnvelope:
    """Resolve the complete execution without creating durable Run state."""
    try:
        _source, data, execution = _resolve_execution_input(
            contract_path, workflow_path
        )
        artifact_path = _approval_artifact_path(data, contract_path)
        try:
            _load_execution_approval(data, contract_path, execution)
            status = "approved"
        except AdmissionError:
            status = "stale" if artifact_path.exists() else "draft"
        goal = execution["goal"]
        if not isinstance(goal, Mapping):
            raise ContractError("resolved execution goal is invalid")
        return ExecutionEnvelope(
            goal_id=str(goal["id"]),
            approval_status=status,
            approval_artifact=str(artifact_path),
            execution_digest=_execution_digest(execution),
            execution=execution,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError(f"invalid harness-native Contract: {error}") from error


def approve_execution(
    contract_path: Path,
    *,
    approved_by: str,
    artifact_path: Path,
    workflow_path: Optional[Path] = None,
    approved_at: Optional[datetime] = None,
) -> ExecutionApproval:
    """Write one external artifact approving the exact resolved execution."""
    if not approved_by.strip():
        raise ValueError("Execution Approval requires an approver")
    _source, data, execution = _resolve_execution_input(contract_path, workflow_path)
    configured_path = _approval_artifact_path(data, contract_path)
    artifact_path = Path(artifact_path).expanduser().resolve()
    if artifact_path != configured_path:
        raise ValueError(
            "Execution Approval artifact path does not match the Contract"
        )
    repository = Path(execution["repository"]["path"])
    try:
        artifact_path.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError(
            "Execution Approval artifact must stay outside the target repository"
        )
    if artifact_path.exists():
        raise ValueError(f"Execution Approval artifact already exists: {artifact_path}")
    approval = ExecutionApproval(
        status="approved",
        approved_by=approved_by.strip(),
        approved_at=(approved_at or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(),
        artifact_path=str(artifact_path),
        execution_digest=_execution_digest(execution),
        execution=execution,
    )
    _write_json_atomically(artifact_path, approval.to_dict())
    return approval
