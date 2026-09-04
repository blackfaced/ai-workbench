"""Prepare one hash-stable overnight Run proposal.

A proposal composes the setup-resolved Agent Harness Profile
(`.ai-workbench/agent-harness.yaml`), one approved project policy command, and
the owner's natural-language goal and instructions into a schema-v5 Contract,
then validates it through the Admission-equivalent preview. Approval binding,
stale invalidation, and idempotent enqueue reuse the existing Contract
approval artifact and RunLedger idempotency keys; no separate proposal store is
created.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

import yaml

from .project import ProjectPolicy
from .runner import ExecutionEnvelope, preview_execution

_AGENT_HARNESS_PATH = ".ai-workbench/agent-harness.yaml"


@dataclass(frozen=True)
class RunProposal:
    contract_path: str
    goal_id: str
    approval_status: str
    approval_artifact: str
    execution_digest: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "contract_path": self.contract_path,
            "goal_id": self.goal_id,
            "approval_status": self.approval_status,
            "approval_artifact": self.approval_artifact,
            "execution_digest": self.execution_digest,
        }


def prepare_proposal(
    repository: Path,
    *,
    goal_id: str,
    title: str,
    requirement: str,
    acceptance: Tuple[str, ...],
    instructions: str,
    command_name: str,
    approval_artifact: Path,
    output_path: Optional[Path] = None,
    base_ref: str = "HEAD",
    verification_timeout_seconds: int = 900,
) -> RunProposal:
    """Prepare one read-only validated Run proposal Contract."""
    repository = Path(repository).expanduser().resolve()
    if not repository.is_dir():
        raise ValueError(f"repository is not a directory: {repository}")
    for name, value in (
        ("goal_id", goal_id),
        ("title", title),
        ("requirement", requirement),
        ("instructions", instructions),
        ("command_name", command_name),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"proposal {name} must be a non-empty string")
    acceptance_items = []
    for entry in acceptance:
        identifier, separator, statement = entry.partition(":")
        if not separator or not identifier.strip() or not statement.strip():
            raise ValueError(
                "proposal acceptance entries must be '<id>: <statement>'"
            )
        acceptance_items.append(
            {"id": identifier.strip(), "statement": statement.strip()}
        )
    if not acceptance_items:
        raise ValueError("proposal requires at least one acceptance statement")
    if verification_timeout_seconds <= 0:
        raise ValueError("proposal verification timeout must be positive")

    profile_document = _load_agent_harness_profile(repository)
    policy_path = repository / ".ai-workbench" / "workflow.yaml"
    policy = ProjectPolicy.load(policy_path)
    command = _approved_command(policy_path, policy, repository, command_name)

    approval_artifact = Path(approval_artifact).expanduser().resolve()
    try:
        approval_artifact.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError(
            "proposal approval artifact must stay outside the target repository"
        )
    if output_path is None:
        output_path = (
            repository / ".ai-workbench" / "proposals" / f"{goal_id}.contract.yaml"
        )
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise ValueError(f"proposal Contract already exists: {output_path}")

    contract = {
        "schema_version": 5,
        "goal": {
            "id": goal_id,
            "title": title,
            "requirement": requirement,
            "acceptance": acceptance_items,
        },
        "approval": {"artifact_path": str(approval_artifact)},
        "instructions": instructions,
        "agent_harness": profile_document,
        "project": {"repo": str(repository), "base_ref": base_ref},
        "verification": {
            "command": list(command),
            "timeout_seconds": verification_timeout_seconds,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    envelope = preview_execution(output_path)
    return _proposal(output_path, envelope)


def _proposal(contract_path: Path, envelope: ExecutionEnvelope) -> RunProposal:
    return RunProposal(
        contract_path=str(contract_path),
        goal_id=envelope.goal_id,
        approval_status=envelope.approval_status,
        approval_artifact=envelope.approval_artifact,
        execution_digest=envelope.execution_digest,
    )


def _load_agent_harness_profile(repository: Path) -> Mapping[str, object]:
    path = repository / _AGENT_HARNESS_PATH
    try:
        document = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(
            f"proposal requires a setup-resolved Agent Harness Profile at "
            f"{_AGENT_HARNESS_PATH}: {error}"
        ) from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError(
            f"Agent Harness Profile at {_AGENT_HARNESS_PATH} is invalid"
        )
    if not document.get("profile_digest"):
        raise ValueError(
            f"Agent Harness Profile at {_AGENT_HARNESS_PATH} has no digest"
        )
    profile = document.get("agent_harness")
    if not isinstance(profile, dict) or not profile:
        raise ValueError(
            f"Agent Harness Profile at {_AGENT_HARNESS_PATH} has no agent_harness mapping"
        )
    return profile


def _approved_command(
    policy_path: Path,
    policy: ProjectPolicy,
    repository: Path,
    command_name: str,
) -> Tuple[str, ...]:
    document = yaml.safe_load(policy_path.read_bytes())
    commands = document.get("capabilities", {}).get("commands", {})
    definition = commands.get(command_name)
    if not isinstance(definition, dict):
        raise ValueError(
            f"proposal command is not a declared project capability: {command_name}"
        )
    argv = definition.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) and item for item in argv)
    ):
        raise ValueError(f"proposal command has no argv: {command_name}")
    command = tuple(argv)
    policy.authorize(repository, command)
    return command
