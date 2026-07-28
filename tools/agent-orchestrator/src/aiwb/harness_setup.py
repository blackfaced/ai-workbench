from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

import yaml

from ._python_setup import (
    CommandCandidate,
    ExternalAnalysisEvidence,
    ProjectProfile,
    inspect_python_l0,
    planning_from_profile,
)
from ._harness_apply import (
    HarnessApplyApproval,
    HarnessApplyPreview,
    HarnessApplyResult,
    apply_python_l0,
    approve_python_l0_apply,
    load_python_l0_apply_approval,
    preview_python_l0_apply,
)
from .github_pipeline import (
    GitHubActionsAdapter,
    GitHubPipelineRequest,
    PipelineVerification,
    append_pipeline_observation,
)
from .project import DoctorReport, ProjectDoctor, ProjectInitializer
from .recipe_catalog import RecipeCatalog
from .skills import (
    SkillCatalog,
    SkillCatalogSnapshot,
    SkillPackCatalog,
    SkillPackDescriptor,
)


@dataclass(frozen=True)
class HarnessSetupRequest:
    repository: Path
    agent_targets: Tuple[str, ...] = ()
    operation: str = "setup"
    output_path: Optional[Path] = None
    planning_mode: str = ""


@dataclass(frozen=True)
class HarnessAssessment:
    state: str
    repository: str
    workflow_action: str
    workflow_path: str
    suggestions: int
    agent_targets: Tuple[str, ...]
    catalog: SkillCatalogSnapshot
    packs: Tuple[SkillPackDescriptor, ...]
    project_profile: Optional[ProjectProfile] = None

    def to_dict(self) -> Mapping[str, object]:
        return {
            "state": self.state,
            "repository": self.repository,
            "workflow_action": self.workflow_action,
            "workflow_path": self.workflow_path,
            "suggestions": self.suggestions,
            "agent_targets": list(self.agent_targets),
            "project_profile": (
                self.project_profile.to_dict()
                if self.project_profile is not None
                else None
            ),
        }


@dataclass(frozen=True)
class PlanApproval:
    status: str
    approved_by: str = ""
    approved_at: str = ""
    artifact_path: str = ""

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "artifact_path": self.artifact_path,
        }


@dataclass(frozen=True)
class HarnessPlan:
    state: str
    request: HarnessSetupRequest
    assessment: HarnessAssessment
    command_candidates: Tuple[CommandCandidate, ...] = ()
    recipe_versions: Tuple[Tuple[str, int], ...] = ()
    coverage_decision: str = ""
    owner_decisions: Tuple[str, ...] = ()
    non_goals: Tuple[str, ...] = ()
    approval: PlanApproval = PlanApproval(status="unapproved")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "state": self.state,
            "request": {
                "repository": str(Path(self.request.repository).expanduser().resolve()),
                "agent_targets": list(self.request.agent_targets),
                "operation": self.request.operation,
                "output_path": (
                    str(Path(self.request.output_path).expanduser().resolve())
                    if self.request.output_path is not None
                    else None
                ),
                "planning_mode": self.request.planning_mode,
            },
            "assessment": self.assessment.to_dict(),
            "command_candidates": [
                candidate.to_dict() for candidate in self.command_candidates
            ],
            "recipe_versions": [
                {"name": name, "version": version}
                for name, version in self.recipe_versions
            ],
            "coverage_decision": self.coverage_decision,
            "owner_decisions": list(self.owner_decisions),
            "non_goals": list(self.non_goals),
            "approval": self.approval.to_dict(),
        }


@dataclass(frozen=True)
class HarnessApplyRequest:
    plan: HarnessPlan
    confirmed: bool
    force: bool = False
    role_skills: Optional[Mapping[str, Sequence[str]]] = None
    install_skills: Tuple[str, ...] = ()
    pack_skills: Optional[Mapping[str, Sequence[str]]] = None
    pack_profiles: Optional[Mapping[str, Sequence[str]]] = None


@dataclass(frozen=True)
class HarnessCandidate:
    state: str
    workflow_path: str
    workflow_action: str
    changed: bool
    agent_targets: Tuple[str, ...]
    installed_packs: Tuple[str, ...] = ()
    next_actions: Tuple[str, ...] = ()
    status: str = ""
    suggestions: int = 0


@dataclass(frozen=True)
class HarnessVerifyRequest:
    config_path: Path
    codex_bin: str = "codex"
    agent_provider: str = "codex"
    claude_bin: str = "claude"


@dataclass(frozen=True)
class HarnessVerification:
    state: str
    config_path: str
    report: DoctorReport


class HarnessSetup:
    """Own the project Harness setup lifecycle behind one public seam."""

    def __init__(
        self,
        catalog: Optional[SkillCatalog] = None,
        pack_catalog: Optional[SkillPackCatalog] = None,
        command_runner: Optional[Callable[[Tuple[str, ...], Path], None]] = None,
        analysis_provider: Optional[
            Callable[[Path], ExternalAnalysisEvidence]
        ] = None,
        recipe_catalog: Optional[RecipeCatalog] = None,
        project_recipe_catalog: Optional[Path] = None,
    ) -> None:
        self._catalog = catalog or SkillCatalog()
        self._pack_catalog = pack_catalog or SkillPackCatalog()
        self._command_runner = command_runner or _run_pack_command
        self._analysis_provider = analysis_provider
        self._recipe_catalog = recipe_catalog or RecipeCatalog()
        self._project_recipe_catalog = project_recipe_catalog
        self._initializer = ProjectInitializer()

    def inspect(self, request: HarnessSetupRequest) -> HarnessAssessment:
        if request.operation not in {"setup", "initialize"}:
            raise ValueError("Harness setup operation must be setup or initialize")
        if request.planning_mode not in {"", "python-l0"}:
            raise ValueError("Harness planning mode must be python-l0")
        if any(
            target not in {"codex", "claude-code"}
            for target in request.agent_targets
        ):
            raise ValueError("agent targets must be codex or claude-code")
        repository = Path(request.repository).expanduser().resolve()
        preview = self._initializer.preview(repository, request.output_path)
        planning = None
        if request.planning_mode == "python-l0":
            external_analysis = None
            analysis_error = ""
            if self._analysis_provider is not None:
                try:
                    external_analysis = self._analysis_provider(repository)
                except Exception as error:
                    analysis_error = str(error)
            planning = inspect_python_l0(
                repository,
                external_analysis=external_analysis,
                analysis_error=analysis_error,
            )
        return HarnessAssessment(
            state="assessed",
            repository=str(repository),
            workflow_action=(
                "inspect_existing"
                if Path(preview.config).exists()
                else "create_draft"
            ),
            workflow_path=preview.config,
            suggestions=preview.suggestions,
            agent_targets=request.agent_targets,
            catalog=self._catalog.inspect(repository),
            packs=self._pack_catalog.inspect(),
            project_profile=planning.profile if planning is not None else None,
        )

    def plan(self, request: HarnessSetupRequest) -> HarnessPlan:
        assessment = self.inspect(request)
        planning = (
            planning_from_profile(assessment.project_profile)
            if assessment.project_profile is not None
            else None
        )
        recipe_versions = ()
        if planning is not None:
            resolution = self._recipe_catalog.resolve(
                "python-l0-baseline",
                project_catalog=self._project_recipe_catalog,
            )
            recipe = self._recipe_catalog.require_verified(resolution)
            recipe_versions = ((recipe.name, recipe.version),)
        return HarnessPlan(
            state="planned",
            request=request,
            assessment=assessment,
            command_candidates=(
                planning.command_candidates if planning is not None else ()
            ),
            recipe_versions=(
                recipe_versions
            ),
            coverage_decision=(
                "measure_baseline_before_threshold"
                if planning is not None
                else ""
            ),
            owner_decisions=(
                planning.owner_decisions if planning is not None else ()
            ),
            non_goals=(
                (
                    "Do not write or invent business tests.",
                    "Do not apply tool migrations or Recipe upgrades.",
                    "Do not execute project commands or pipeline workflows.",
                    "Do not create candidate worktrees or modify the repository.",
                )
                if planning is not None
                else ()
            ),
        )

    def approve_plan(
        self,
        plan: HarnessPlan,
        approved_by: str,
        approved_at: Optional[datetime] = None,
        artifact_path: Optional[Path] = None,
    ) -> HarnessPlan:
        if plan.state != "planned":
            raise ValueError("Plan Approval requires a planned Harness Plan")
        if plan.approval.status != "unapproved":
            raise ValueError("Harness Plan is already approved")
        if not approved_by.strip():
            raise ValueError("Plan Approval requires an approver")
        if plan.assessment != self.inspect(plan.request):
            raise ValueError("Harness Plan assessment is stale or has been modified")
        if artifact_path is None:
            raise ValueError("Plan Approval requires an explicit artifact path")
        repository = Path(plan.request.repository).expanduser().resolve()
        artifact_path = Path(artifact_path).expanduser().resolve()
        try:
            artifact_path.relative_to(repository)
        except ValueError:
            pass
        else:
            raise ValueError(
                "Plan Approval artifact must stay outside the target repository"
            )
        approved_at = approved_at or datetime.now(timezone.utc)
        approved = HarnessPlan(
            state=plan.state,
            request=plan.request,
            assessment=plan.assessment,
            command_candidates=plan.command_candidates,
            recipe_versions=plan.recipe_versions,
            coverage_decision=plan.coverage_decision,
            owner_decisions=plan.owner_decisions,
            non_goals=plan.non_goals,
            approval=PlanApproval(
                status="approved",
                approved_by=approved_by.strip(),
                approved_at=approved_at.astimezone(timezone.utc).isoformat(),
                artifact_path=str(artifact_path),
            ),
        )
        _write_json_atomically(artifact_path, approved.to_dict())
        return approved

    def load_approved_plan(
        self,
        plan: HarnessPlan,
        artifact_path: Path,
    ) -> HarnessPlan:
        artifact_path = Path(artifact_path).expanduser().resolve()
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read Plan Approval: {error}") from error
        if not isinstance(data, dict):
            raise ValueError("Plan Approval must be a JSON object")
        approval_data = data.get("approval")
        if not isinstance(approval_data, dict):
            raise ValueError("Plan Approval is missing approval metadata")
        approved = replace(
            plan,
            approval=PlanApproval(
                status=str(approval_data.get("status", "")),
                approved_by=str(approval_data.get("approved_by", "")),
                approved_at=str(approval_data.get("approved_at", "")),
                artifact_path=str(approval_data.get("artifact_path", "")),
            ),
        )
        if approved.approval.status != "approved":
            raise ValueError("Plan Approval artifact is not approved")
        if approved.approval.artifact_path != str(artifact_path):
            raise ValueError("Plan Approval artifact path does not match its content")
        if approved.to_dict() != data:
            raise ValueError("Plan Approval artifact does not match the current Plan")
        return approved

    def preview_apply(
        self,
        plan: HarnessPlan,
        *,
        base_commit: str,
        state_dir: Path,
        command_names: Sequence[str],
    ) -> HarnessApplyPreview:
        return preview_python_l0_apply(
            plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=command_names,
        )

    def approve_apply(
        self,
        preview: HarnessApplyPreview,
        *,
        approved_by: str,
        artifact_path: Path,
        approved_at: Optional[datetime] = None,
    ) -> HarnessApplyApproval:
        return approve_python_l0_apply(
            preview,
            approved_by=approved_by,
            artifact_path=artifact_path,
            approved_at=approved_at,
        )

    def load_apply_approval(
        self,
        preview: HarnessApplyPreview,
        artifact_path: Path,
    ) -> HarnessApplyApproval:
        return load_python_l0_apply_approval(preview, artifact_path)

    def apply_approved(
        self,
        plan: HarnessPlan,
        approval: HarnessApplyApproval,
        *,
        state_dir: Path,
    ) -> HarnessApplyResult:
        return apply_python_l0(
            plan,
            approval,
            state_dir=state_dir,
        )

    def verify_pipeline(
        self,
        request: GitHubPipelineRequest,
        *,
        adapter: GitHubActionsAdapter,
        state_dir: Path,
    ) -> PipelineVerification:
        result = adapter.verify(request)
        append_pipeline_observation(
            request,
            result,
            state_dir=state_dir,
        )
        return result

    def apply(self, request: HarnessApplyRequest) -> HarnessCandidate:
        if request.plan.state != "planned":
            raise ValueError("apply requires a planned Harness Plan")
        if not request.confirmed:
            raise ValueError("setup requires explicit confirmation before writing")
        plan = request.plan
        assessment = plan.assessment
        if assessment.state != "assessed":
            raise ValueError("apply requires an assessed Harness Plan")
        if plan.request.planning_mode:
            raise ValueError(
                "an approved Harness Plan does not authorize Apply; "
                "candidate Apply is a separate lifecycle"
            )
        repository = Path(plan.request.repository).expanduser().resolve()
        if assessment.repository != str(repository):
            raise ValueError("Harness Plan repository does not match its request")
        if assessment != self.inspect(plan.request):
            raise ValueError("Harness Plan assessment is stale or has been modified")
        if plan.request.operation == "initialize":
            initialized = self._initializer.initialize(
                repository=repository,
                output_path=plan.request.output_path,
                force=request.force,
            )
            return HarnessCandidate(
                state="candidate",
                workflow_path=initialized.config,
                workflow_action=(
                    "replaced"
                    if assessment.workflow_action == "inspect_existing"
                    else "created"
                ),
                changed=True,
                agent_targets=plan.request.agent_targets,
                status=initialized.status,
                suggestions=initialized.suggestions,
            )

        selected_packs = request.pack_skills or {}
        selected_profiles = request.pack_profiles or {}
        if (
            request.install_skills or selected_packs or selected_profiles
        ) and not plan.request.agent_targets:
            raise ValueError("installing a Skill requires an explicit agent target")
        pack_plans = self._pack_catalog.plans(
            selected_packs,
            plan.request.agent_targets,
            profiles=selected_profiles,
        )
        workflow = Path(assessment.workflow_path)
        created = not workflow.exists()
        if created:
            self._initializer.initialize(repository)
        document = _workflow_document(workflow)
        changed = created
        workflow_changed = created
        known_local_paths = {
            skill.path for skill in assessment.catalog.skills if skill.source == "project"
        }
        selected = request.role_skills or {}
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
                raise ValueError(
                    f"role skills must be discovered project-local Skills: {role}"
                )
            configured = configured_skills.setdefault(role, [])
            if not isinstance(configured, list):
                raise ValueError(
                    f"workflow capabilities.skills.{role} must be a list"
                )
            for path in paths:
                if path not in configured:
                    configured.append(path)
                    changed = True
                    workflow_changed = True
        for target in plan.request.agent_targets:
            target_root = repository / _TARGET_SKILL_ROOTS[target]
            _require_within_repository(target_root.parent, repository)
            for name in request.install_skills:
                source = self._catalog.bundled_source(name)
                destination = target_root / name / "SKILL.md"
                _require_within_repository(destination.parent, repository)
                if destination.is_symlink():
                    raise ValueError(
                        "Skill destination must remain inside the repository"
                    )
                source_bytes = source.read_bytes()
                if destination.is_file() and destination.read_bytes() == source_bytes:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                _require_within_repository(destination.parent, repository)
                destination.write_bytes(source_bytes)
                changed = True
        for pack_plan in pack_plans:
            self._command_runner(pack_plan.command, repository)
            changed = True
        if workflow_changed:
            workflow.write_text(
                yaml.safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
        return HarnessCandidate(
            state="candidate",
            workflow_path=str(workflow),
            workflow_action=(
                "created" if created else "updated" if changed else "unchanged"
            ),
            changed=changed,
            agent_targets=plan.request.agent_targets,
            installed_packs=tuple(
                dict.fromkeys(pack_plan.name for pack_plan in pack_plans)
            ),
            next_actions=tuple(
                dict.fromkeys(
                    pack_plan.setup_action
                    for pack_plan in pack_plans
                    if pack_plan.setup_action
                )
            ),
        )

    def verify(self, request: HarnessVerifyRequest) -> HarnessVerification:
        config_path = Path(request.config_path).expanduser().resolve()
        report = ProjectDoctor().inspect(
            config_path=config_path,
            codex_bin=request.codex_bin,
            agent_provider=request.agent_provider,
            claude_bin=request.claude_bin,
        )
        return HarnessVerification(
            state="verified" if report.status == "ok" else "verification_failed",
            config_path=str(config_path),
            report=report,
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


def _write_json_atomically(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
