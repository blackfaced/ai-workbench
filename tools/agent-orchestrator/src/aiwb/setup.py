from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

from .harness_setup import (
    HarnessApplyRequest,
    HarnessSetup,
    HarnessSetupRequest,
)
from .skills import (
    SkillCatalog,
    SkillCatalogSnapshot,
    SkillPackCatalog,
    SkillPackDescriptor,
)


@dataclass(frozen=True)
class SetupInspection:
    workflow_action: str
    workflow_path: str
    suggestions: int
    agent_targets: Tuple[str, ...]
    catalog: SkillCatalogSnapshot
    packs: Tuple[SkillPackDescriptor, ...]


@dataclass(frozen=True)
class SetupApplyResult:
    workflow_path: str
    workflow_action: str
    changed: bool
    agent_targets: Tuple[str, ...]
    installed_packs: Tuple[str, ...] = ()
    updated_packs: Tuple[str, ...] = ()
    next_actions: Tuple[str, ...] = ()


class WorkbenchSetup:
    """Plan explicit project setup without changing repository or user configuration."""

    def __init__(
        self,
        catalog: Optional[SkillCatalog] = None,
        pack_catalog: Optional[SkillPackCatalog] = None,
        command_runner: Optional[Callable[[Tuple[str, ...], Path], None]] = None,
    ) -> None:
        self._setup = HarnessSetup(
            catalog=catalog,
            pack_catalog=pack_catalog,
            command_runner=command_runner,
        )

    def inspect(
        self,
        repository: Path,
        agent_targets: Tuple[str, ...] = (),
    ) -> SetupInspection:
        assessment = self._setup.inspect(
            HarnessSetupRequest(
                repository=repository,
                agent_targets=agent_targets,
            )
        )
        return SetupInspection(
            workflow_action=assessment.workflow_action,
            workflow_path=assessment.workflow_path,
            suggestions=assessment.suggestions,
            agent_targets=assessment.agent_targets,
            catalog=assessment.catalog,
            packs=assessment.packs,
        )

    def apply(
        self,
        repository: Path,
        confirmed: bool,
        agent_targets: Tuple[str, ...] = (),
        role_skills: Optional[Mapping[str, Sequence[str]]] = None,
        install_skills: Tuple[str, ...] = (),
        pack_skills: Optional[Mapping[str, Sequence[str]]] = None,
        pack_profiles: Optional[Mapping[str, Sequence[str]]] = None,
        update_packs: Tuple[str, ...] = (),
    ) -> SetupApplyResult:
        plan = self._setup.plan(
            HarnessSetupRequest(
                repository=repository,
                agent_targets=agent_targets,
            )
        )
        candidate = self._setup.apply(
            HarnessApplyRequest(
                plan=plan,
                confirmed=confirmed,
                role_skills=role_skills,
                install_skills=install_skills,
                pack_skills=pack_skills,
                pack_profiles=pack_profiles,
                update_packs=update_packs,
            )
        )
        return SetupApplyResult(
            workflow_path=candidate.workflow_path,
            workflow_action=candidate.workflow_action,
            changed=candidate.changed,
            agent_targets=candidate.agent_targets,
            installed_packs=candidate.installed_packs,
            updated_packs=candidate.updated_packs,
            next_actions=candidate.next_actions,
        )
