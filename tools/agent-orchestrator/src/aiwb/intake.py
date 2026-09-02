"""Read-only readiness checks for one harness-native Run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

from .project import ProjectConfigError, ProjectPolicy
from .runner import ContractError, preview_execution


@dataclass(frozen=True)
class IntakeBlocker:
    code: str
    message: str
    action: str


@dataclass(frozen=True)
class GoalIntakeResult:
    source: str
    readiness: str
    cheapest_viable_path: str
    blockers: Tuple[IntakeBlocker, ...]
    execution_envelope: Mapping[str, object]
    next_action: str
    daemon_status: str
    approval_required: bool
    submission_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source, "readiness": self.readiness,
            "cheapest_viable_path": self.cheapest_viable_path,
            "blockers": [asdict(item) for item in self.blockers],
            "execution_envelope": dict(self.execution_envelope),
            "next_action": self.next_action, "daemon_status": self.daemon_status,
            "approval_required": self.approval_required,
            "submission_required": self.submission_required,
        }


class GoalIntake:
    """Inspect admission readiness without planning or decomposing a Run."""

    def __init__(self, daemon_probe: Optional[Callable[[], bool]] = None) -> None:
        self._daemon_probe = daemon_probe or (lambda: False)

    def inspect(
        self,
        *,
        repository: Path,
        contract_path: Path,
    ) -> GoalIntakeResult:
        repository = Path(repository).expanduser().resolve()
        if not repository.is_dir():
            raise ValueError(f"repository is not a directory: {repository}")
        daemon_status = "ok" if self._daemon_probe() else "unavailable"
        return self._contract(repository, Path(contract_path), daemon_status)

    def _contract(self, repository: Path, path: Path, daemon_status: str) -> GoalIntakeResult:
        blockers = list(_policy_blockers(repository))
        try:
            envelope = preview_execution(path).to_dict()
            if envelope.get("approval_status") != "approved":
                blockers.append(IntakeBlocker("approval", "The Contract is not approved.", "Obtain explicit owner approval before submitting a Run."))
        except (ContractError, OSError, ValueError) as error:
            blockers.append(IntakeBlocker("contract_validation", str(error), "Resolve the Contract validation error."))
            envelope = {}
        return GoalIntakeResult("contract", "ready" if not blockers else "blocked", "ai_workbench_unattended", tuple(blockers), envelope, "submit_run" if not blockers else "resolve_contract_blockers", daemon_status, bool(blockers), not bool(blockers))

def _policy_blockers(repository: Path) -> Tuple[IntakeBlocker, ...]:
    try:
        ProjectPolicy.load(repository / ".ai-workbench" / "workflow.yaml")
    except ProjectConfigError as error:
        return (IntakeBlocker("permissions", str(error), "Run aiwb setup, then explicitly approve the project policy."),)
    return ()
