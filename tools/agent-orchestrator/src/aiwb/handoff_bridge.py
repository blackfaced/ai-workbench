from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Tuple

import yaml

from .intake import GoalIntake, IntakeBlocker
from .project import ProjectPolicy
from .runner import preview_execution


@dataclass(frozen=True)
class HandoffBridgeResult:
    readiness: str
    artifact_kind: str
    artifact_path: str
    blockers: Tuple[IntakeBlocker, ...]
    warnings: Tuple[str, ...]
    preflight: Mapping[str, object]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "readiness": self.readiness,
            "artifact_kind": self.artifact_kind,
            "artifact_path": self.artifact_path,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "warnings": list(self.warnings),
            "preflight": dict(self.preflight),
        }


class GoalHandoffBridge:
    """Create the next safe artifact from a reviewed planning handoff."""

    def create(
        self,
        *,
        repository: Path,
        handoff_path: Path,
        policy_path: Path,
        output_path: Path,
    ) -> HandoffBridgeResult:
        repository = Path(repository).expanduser().resolve()
        handoff_path = Path(handoff_path).expanduser().resolve()
        policy_path = Path(policy_path).expanduser().resolve()
        output_path = Path(output_path).expanduser().resolve()
        _require_external_new_output(output_path, repository)

        intake = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff_path,
        )
        normalized = intake.planning_handoff
        if not normalized:
            draft = _policy_draft_document(
                repository=repository,
                handoff={},
                policy_path=policy_path,
                blockers=intake.blockers,
                warnings=intake.warnings,
                policy={},
            )
            _write_yaml_atomically(output_path, draft)
            return HandoffBridgeResult(
                readiness="blocked",
                artifact_kind="policy_draft",
                artifact_path=str(output_path),
                blockers=intake.blockers,
                warnings=intake.warnings,
                preflight={},
            )
        handoff_blockers = tuple(
            blocker
            for blocker in intake.blockers
            if blocker.code in _HANDOFF_BLOCKER_CODES
        )
        policy_data = _read_mapping(policy_path, "reviewed policy")
        policy_blockers = list(
            _policy_review_blockers(
                policy_data,
                repository=repository,
            )
        )
        command_definitions = _approved_command_definitions(policy_data)
        policy = (
            ProjectPolicy.load(policy_path)
            if not policy_blockers
            else None
        )
        contract, blockers, warnings = _contract_document(
            repository=repository,
            handoff=normalized,
            policy=policy,
            command_definitions=command_definitions,
        )
        blockers = _dedupe_blockers(
            handoff_blockers + tuple(policy_blockers) + blockers
        )
        if blockers:
            draft = _policy_draft_document(
                repository=repository,
                handoff=normalized,
                policy_path=policy_path,
                blockers=blockers,
                warnings=warnings,
                policy=policy_data,
            )
            _write_yaml_atomically(output_path, draft)
            return HandoffBridgeResult(
                readiness="blocked",
                artifact_kind="policy_draft",
                artifact_path=str(output_path),
                blockers=blockers,
                warnings=warnings,
                preflight={},
            )

        temporary_path = _write_yaml_temporary(output_path, contract)
        try:
            preflight = preview_execution(
                temporary_path,
                workflow_path=policy_path,
            ).to_dict()
            temporary_path.replace(output_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        return HandoffBridgeResult(
            readiness="ready_for_contract_approval",
            artifact_kind="contract",
            artifact_path=str(output_path),
            blockers=(),
            warnings=warnings,
            preflight=preflight,
        )


def _contract_document(
    *,
    repository: Path,
    handoff: Mapping[str, object],
    policy: ProjectPolicy | None,
    command_definitions: Mapping[str, Tuple[str, ...]],
) -> Tuple[Mapping[str, object], Tuple[IntakeBlocker, ...], Tuple[str, ...]]:
    goal = handoff.get("goal")
    goal = goal if isinstance(goal, dict) else {}
    acceptance = handoff.get("acceptance")
    acceptance = acceptance if isinstance(acceptance, list) else []
    todos = handoff.get("todos")
    todos = todos if isinstance(todos, list) else []
    blockers = []
    warnings = []
    contract_todos = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        todo_id = str(todo.get("id", "unknown"))
        command_name = todo.get("command_name")
        command = (
            command_definitions.get(command_name)
            if isinstance(command_name, str)
            else None
        )
        if (
            command is None
            or policy is None
            or command not in policy.approved_commands
        ):
            blockers.append(
                IntakeBlocker(
                    code="approved_command_missing",
                    message=f"Todo {todo_id} has no exact approved command mapping.",
                    action=(
                        "Add command_name referencing one approved policy "
                        "capability, then rerun the bridge."
                    ),
                )
            )
        allowed_paths = todo.get("allowed_paths")
        if (
            not isinstance(allowed_paths, list)
            or not allowed_paths
            or not all(isinstance(item, str) and item for item in allowed_paths)
        ):
            blockers.append(
                IntakeBlocker(
                    code="allowed_paths_missing",
                    message=f"Todo {todo_id} has no executable allowed_paths boundary.",
                    action=(
                        "Add non-empty allowed_paths for the Todo before "
                        "creating an executable Contract."
                    ),
                )
            )
            warnings.append(
                f"Todo {todo_id} needs reviewed allowed_paths before execution."
            )
        if command is None or not isinstance(allowed_paths, list) or not allowed_paths:
            continue
        contract_todos.append(
            {
                "id": todo_id,
                "title": str(todo.get("title", todo_id)),
                "depends_on": list(todo.get("depends_on", [])),
                "test_ids": list(todo.get("acceptance_ids", [])),
                "test": {
                    "command": list(command),
                    "allowed_paths": list(allowed_paths),
                    "timeout_seconds": 600,
                },
            }
        )
    if not todos:
        blockers.append(
            IntakeBlocker(
                code="todo_structure",
                message="The planning handoff has no executable Todos.",
                action="Add reviewed Todo structure before creating a Contract.",
            )
        )
    provenance = handoff.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    return (
        {
            "schema_version": 1,
            "draft": {
                "source_provenance": dict(provenance),
                "source_handoff_kind": handoff.get("kind", ""),
                "review_required": [
                    "Review every command and allowed path against the source handoff.",
                    "Review the fixed provider, resource decision, and non-production policy.",
                    "Approve the Contract only after the acceptance boundary is complete.",
                ],
            },
            "goal": {
                "id": str(goal.get("id", "handoff-goal")),
                "title": str(goal.get("title", "Planning handoff")),
                "requirement": str(goal.get("requirement", "")),
                "acceptance": acceptance,
            },
            "approval": {
                "status": "draft",
                "approved_by": "",
                "approved_at": "",
            },
            "agent": {"provider": "codex"},
            "project": {"repo": str(repository), "base_ref": "main"},
            "resources": {},
            "todos": contract_todos,
        },
        _dedupe_blockers(tuple(blockers)),
        tuple(dict.fromkeys(warnings)),
    )


def _approved_command_definitions(
    policy: Mapping[str, object],
) -> Mapping[str, Tuple[str, ...]]:
    capabilities = policy.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    commands = capabilities.get("commands")
    commands = commands if isinstance(commands, dict) else {}
    return {
        str(name): tuple(definition["argv"])
        for name, definition in commands.items()
        if isinstance(name, str)
        and isinstance(definition, dict)
        and definition.get("approved") is True
        and isinstance(definition.get("argv"), list)
        and all(isinstance(item, str) and item for item in definition["argv"])
    }


def _policy_draft_document(
    *,
    repository: Path,
    handoff: Mapping[str, object],
    policy_path: Path,
    blockers: Tuple[IntakeBlocker, ...],
    warnings: Tuple[str, ...],
    policy: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "schema_version": 1,
        "kind": "aiwb.workflow-policy-draft",
        "status": "draft",
        "executable": False,
        "project": {"root": str(repository), "trusted": False},
        "source": {
            "handoff_provenance": dict(handoff.get("provenance", {})),
            "input_policy": str(policy_path),
        },
        "candidate_commands": _candidate_command_definitions(policy),
        "blockers": [asdict(blocker) for blocker in blockers],
        "warnings": list(warnings),
        "review_actions": [blocker.action for blocker in blockers],
    }


def _policy_review_blockers(
    policy: Mapping[str, object],
    *,
    repository: Path,
) -> Tuple[IntakeBlocker, ...]:
    blockers = []
    project = policy.get("project")
    project = project if isinstance(project, dict) else {}
    root = project.get("root")
    root_matches = (
        isinstance(root, str)
        and bool(root)
        and Path(root).expanduser().resolve() == repository
    )
    if (
        policy.get("schema_version") != 1
        or policy.get("status") != "approved"
        or project.get("trusted") is not True
        or not root_matches
    ):
        blockers.append(
            IntakeBlocker(
                code="policy_not_approved",
                message=(
                    "The supplied policy must be schema version 1, approved, "
                    "trusted, and bound to the target repository."
                ),
                action=(
                    "Review the draft policy, approve repository trust and "
                    "capabilities, then rerun the bridge."
                ),
            )
        )
    if not _approved_command_definitions(policy):
        blockers.append(
            IntakeBlocker(
                code="approved_command_missing",
                message="The supplied policy has no approved command capabilities.",
                action=(
                    "Review and approve the exact command capabilities needed "
                    "by the planning handoff."
                ),
            )
        )
    return tuple(blockers)


def _candidate_command_definitions(
    policy: Mapping[str, object],
) -> Mapping[str, object]:
    suggestions = policy.get("suggestions")
    suggestions = suggestions if isinstance(suggestions, dict) else {}
    commands = suggestions.get("commands")
    if not isinstance(commands, dict):
        return {}
    return {
        str(name): {
            "argv": list(definition["argv"]),
            "reason": definition.get("reason", ""),
        }
        for name, definition in commands.items()
        if isinstance(name, str)
        and isinstance(definition, dict)
        and isinstance(definition.get("argv"), list)
        and all(isinstance(item, str) and item for item in definition["argv"])
        and isinstance(definition.get("reason", ""), str)
    }


def _require_external_new_output(path: Path, repository: Path) -> None:
    try:
        path.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("bridge output must stay outside the target repository")
    if path.exists():
        raise ValueError(f"bridge output already exists: {path}")


def _read_mapping(path: Path, label: str) -> Mapping[str, object]:
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _write_yaml_atomically(path: Path, value: Mapping[str, object]) -> None:
    temporary_path = _write_yaml_temporary(path, value)
    temporary_path.replace(path)


def _write_yaml_temporary(path: Path, value: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            yaml.safe_dump(value, output, sort_keys=False)
        return temporary_path
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _dedupe_blockers(
    blockers: Tuple[IntakeBlocker, ...],
) -> Tuple[IntakeBlocker, ...]:
    return tuple(
        {
            (blocker.code, blocker.message, blocker.action): blocker
            for blocker in blockers
        }.values()
    )


_HANDOFF_BLOCKER_CODES = frozenset(
    {
        "acceptance_boundary",
        "handoff_provenance",
        "handoff_validation",
        "todo_dependencies",
        "unsupported_handoff_schema",
    }
)
