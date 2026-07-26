from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

import yaml

from .project import ProjectInitializer
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
    next_actions: Tuple[str, ...] = ()


class WorkbenchSetup:
    """Plan explicit project setup without changing repository or user configuration."""

    def __init__(
        self,
        catalog: Optional[SkillCatalog] = None,
        pack_catalog: Optional[SkillPackCatalog] = None,
        command_runner: Optional[Callable[[Tuple[str, ...], Path], None]] = None,
    ) -> None:
        self._catalog = catalog or SkillCatalog()
        self._pack_catalog = pack_catalog or SkillPackCatalog()
        self._command_runner = command_runner or _run_pack_command
        self._initializer = ProjectInitializer()

    def inspect(
        self,
        repository: Path,
        agent_targets: Tuple[str, ...] = (),
    ) -> SetupInspection:
        if any(target not in {"codex", "claude-code"} for target in agent_targets):
            raise ValueError("agent targets must be codex or claude-code")
        preview = self._initializer.preview(repository)
        return SetupInspection(
            workflow_action=(
                "inspect_existing"
                if Path(preview.config).exists()
                else "create_draft"
            ),
            workflow_path=preview.config,
            suggestions=preview.suggestions,
            agent_targets=agent_targets,
            catalog=self._catalog.inspect(repository),
            packs=self._pack_catalog.inspect(),
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
    ) -> SetupApplyResult:
        if not confirmed:
            raise ValueError("setup requires explicit confirmation before writing")
        inspection = self.inspect(repository, agent_targets)
        repository = Path(repository).expanduser().resolve()
        selected_packs = pack_skills or {}
        selected_profiles = pack_profiles or {}
        if (install_skills or selected_packs or selected_profiles) and not agent_targets:
            raise ValueError("installing a Skill requires an explicit agent target")
        pack_plans = self._pack_catalog.plans(
            selected_packs,
            agent_targets,
            profiles=selected_profiles,
        )
        workflow = Path(inspection.workflow_path)
        created = not workflow.exists()
        if created:
            self._initializer.initialize(repository)
        document = _workflow_document(workflow)
        changed = created
        workflow_changed = created
        known_local_paths = {
            skill.path for skill in inspection.catalog.skills if skill.source == "project"
        }
        selected = role_skills or {}
        capabilities = document.setdefault("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ValueError("workflow capabilities must be a mapping")
        configured_skills = capabilities.setdefault("skills", {})
        if not isinstance(configured_skills, dict):
            raise ValueError("workflow capabilities.skills must be a mapping")
        for role, paths in selected.items():
            if role not in _ROLE_NAMES:
                raise ValueError(f"unsupported role: {role}")
            paths = tuple(paths)
            if not paths or any(path not in known_local_paths for path in paths):
                raise ValueError(f"role skills must be discovered project-local Skills: {role}")
            configured = configured_skills.setdefault(role, [])
            if not isinstance(configured, list):
                raise ValueError(f"workflow capabilities.skills.{role} must be a list")
            for path in paths:
                if path not in configured:
                    configured.append(path)
                    changed = True
                    workflow_changed = True
        for target in agent_targets:
            target_root = repository / _TARGET_SKILL_ROOTS[target]
            _require_within_repository(target_root.parent, repository)
            for name in install_skills:
                source = self._catalog.bundled_source(name)
                destination = target_root / name / "SKILL.md"
                _require_within_repository(destination.parent, repository)
                if destination.is_symlink():
                    raise ValueError("Skill destination must remain inside the repository")
                source_bytes = source.read_bytes()
                if destination.is_file() and destination.read_bytes() == source_bytes:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                _require_within_repository(destination.parent, repository)
                destination.write_bytes(source_bytes)
                changed = True
        for plan in pack_plans:
            self._command_runner(plan.command, repository)
            changed = True
        if workflow_changed:
            workflow.write_text(
                yaml.safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
        return SetupApplyResult(
            workflow_path=str(workflow),
            workflow_action=("created" if created else "updated" if changed else "unchanged"),
            changed=changed,
            agent_targets=agent_targets,
            installed_packs=tuple(dict.fromkeys(plan.name for plan in pack_plans)),
            next_actions=tuple(
                dict.fromkeys(
                    plan.setup_action for plan in pack_plans if plan.setup_action
                )
            ),
        )


_ROLE_NAMES = frozenset(
    {"test_designer", "implementer", "verifier", "conflict_repairer"}
)
_TARGET_SKILL_ROOTS = {
    "codex": ".codex/skills",
    "claude-code": ".claude/skills",
}


def _workflow_document(path: Path) -> dict[str, object]:
    try:
        document = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read workflow: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("workflow must be a mapping")
    return document


def _require_within_repository(path: Path, repository: Path) -> None:
    try:
        path.resolve().relative_to(repository)
    except ValueError as error:
        raise ValueError("Skill destination must remain inside the repository") from error


def _run_pack_command(command: Tuple[str, ...], repository: Path) -> None:
    try:
        subprocess.run(
            command,
            cwd=str(repository),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"Skill pack installation failed: {error}") from error
