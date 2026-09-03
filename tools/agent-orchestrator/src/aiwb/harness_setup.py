from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

import yaml

from ._paths import contains_symlink
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
from .profile_setup import (
    HarnessProfileResolution,
    HarnessProfileSelections,
    harness_profile_document,
    resolve_harness_profile,
)
from .codex_driver import CodexDriver
from .recipe_catalog import RecipeCatalog
from .skills import (
    AGENT_SKILL_ROOTS,
    SkillCatalog,
    SkillCatalogSnapshot,
    SkillPackCatalog,
    SkillPackDescriptor,
)


_EXTENSION_PROBE_TIMEOUT_SECONDS = 30.0
_EXTENSION_PROBE_REAP_SECONDS = 0.5


@dataclass(frozen=True)
class HarnessSetupRequest:
    repository: Path
    agent_targets: Tuple[str, ...] = ()
    operation: str = "setup"
    output_path: Optional[Path] = None
    planning_mode: str = ""
    profile_selections: Optional["HarnessProfileSelections"] = None


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
    install_skills: Tuple[str, ...] = ()
    install_extensions: Tuple[Path, ...] = ()
    pack_skills: Optional[Mapping[str, Sequence[str]]] = None
    pack_profiles: Optional[Mapping[str, Sequence[str]]] = None


@dataclass(frozen=True)
class HarnessExtensionResolution:
    identity: str
    agent_target: str
    source: str
    destination: str
    entrypoint: str
    descriptor_sha256: str
    entrypoint_sha256: str
    harness_probe: Tuple[str, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "identity": self.identity,
            "agent_target": self.agent_target,
            "source": self.source,
            "destination": self.destination,
            "entrypoint": self.entrypoint,
            "descriptor_sha256": self.descriptor_sha256,
            "entrypoint_sha256": self.entrypoint_sha256,
            "harness_probe": list(self.harness_probe),
        }


@dataclass(frozen=True)
class HarnessSkillResolution:
    name: str
    agent_target: str
    source: str
    destination: str
    sha256: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "agent_target": self.agent_target,
            "source": self.source,
            "destination": self.destination,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class HarnessCandidate:
    state: str
    workflow_path: str
    workflow_action: str
    changed: bool
    agent_targets: Tuple[str, ...]
    extensions: Tuple[HarnessExtensionResolution, ...] = ()
    selected_skills: Tuple[HarnessSkillResolution, ...] = ()
    installed_packs: Tuple[str, ...] = ()
    next_actions: Tuple[str, ...] = ()
    status: str = ""
    suggestions: int = 0
    profile: Optional["HarnessProfileResolution"] = None


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


@dataclass(frozen=True)
class _ExtensionInstall:
    identity: str
    agent_target: str
    source: Path
    source_bytes: bytes
    descriptor_sha256: str
    destination: Path
    descriptor: Mapping[str, object]
    repository: Path
    entrypoint: Path
    entrypoint_sha256: str
    harness_probe: Tuple[str, ...]


@dataclass(frozen=True)
class _SkillInstall:
    resolution: HarnessSkillResolution
    repository: Path
    source: Path
    source_bytes: bytes
    destination: Path


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
        extension_probe: Optional[
            Callable[[str, Mapping[str, object], Path, Path], None]
        ] = None,
        codex_driver: Optional[CodexDriver] = None,
    ) -> None:
        self._catalog = catalog or SkillCatalog()
        self._pack_catalog = pack_catalog or SkillPackCatalog()
        self._command_runner = command_runner or _run_pack_command
        self._analysis_provider = analysis_provider
        self._recipe_catalog = recipe_catalog or RecipeCatalog()
        self._project_recipe_catalog = project_recipe_catalog
        self._extension_probe = extension_probe or _run_declared_harness_probe
        self._codex_driver = codex_driver or CodexDriver()
        self._initializer = ProjectInitializer()

    def resolve_profile(
        self, request: HarnessSetupRequest
    ) -> Optional[HarnessProfileResolution]:
        """Resolve the selected Agent Harness Profile without writing anything."""
        if request.profile_selections is None:
            return None
        return resolve_harness_profile(
            Path(request.repository),
            request.profile_selections,
            request.agent_targets,
            driver=self._codex_driver,
        )

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

    def preview_extensions(
        self,
        repository: Path,
        sources: Sequence[Path],
        agent_targets: Tuple[str, ...],
    ) -> Tuple[HarnessExtensionResolution, ...]:
        repository = Path(repository).expanduser().resolve()
        if sources and not agent_targets:
            raise ValueError(
                "installing a Harness Extension requires an explicit agent target"
            )
        installs = tuple(
            _extension_install(repository, source, agent_targets)
            for source in sources
        )
        _require_unique_extension_destinations(installs)
        return tuple(_extension_resolution(install) for install in installs)

    def preview_skills(
        self,
        repository: Path,
        names: Sequence[str],
        agent_targets: Tuple[str, ...],
    ) -> Tuple[HarnessSkillResolution, ...]:
        repository = Path(repository).expanduser().resolve()
        if names and not agent_targets:
            raise ValueError(
                "installing a Harness Extension requires an explicit agent target"
            )
        return tuple(
            install.resolution
            for install in _skill_installs(
                repository, names, agent_targets, self._catalog
            )
        )

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
            request.install_skills
            or request.install_extensions
            or selected_packs
            or selected_profiles
        ) and not plan.request.agent_targets:
            raise ValueError("installing a Harness Extension requires an explicit agent target")
        extension_installs = tuple(
            _extension_install(repository, source, plan.request.agent_targets)
            for source in request.install_extensions
        )
        _require_unique_extension_destinations(extension_installs)
        skill_installs = _skill_installs(
            repository,
            request.install_skills,
            plan.request.agent_targets,
            self._catalog,
        )
        for install in extension_installs:
            _assert_extension_entrypoint(install)
            self._extension_probe(
                install.agent_target,
                install.descriptor,
                repository,
                install.entrypoint,
            )
            _assert_extension_entrypoint(install)
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
        capabilities = document.setdefault("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ValueError("workflow capabilities must be a mapping")
        for install in skill_installs:
            _assert_skill_install(install)
            if (
                install.destination.is_file()
                and install.destination.read_bytes() == install.source_bytes
            ):
                continue
            install.destination.parent.mkdir(parents=True, exist_ok=True)
            _assert_skill_install(install)
            _write_bytes_atomically(install.destination, install.source_bytes)
            changed = True
        for install in extension_installs:
            destination = install.destination
            _assert_extension_destination(install)
            if (
                destination.is_file()
                and destination.read_bytes() == install.source_bytes
            ):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            _assert_extension_destination(install)
            _write_bytes_atomically(destination, install.source_bytes)
            changed = True
        for pack_plan in pack_plans:
            self._command_runner(pack_plan.command, repository)
            changed = True
        if workflow_changed:
            workflow.write_text(
                yaml.safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
        profile_resolution = self.resolve_profile(plan.request)
        if profile_resolution is not None:
            if _write_harness_profile(repository, profile_resolution):
                changed = True
        return HarnessCandidate(
            state="candidate",
            workflow_path=str(workflow),
            workflow_action=(
                "created" if created else "updated" if changed else "unchanged"
            ),
            changed=changed,
            agent_targets=plan.request.agent_targets,
            extensions=tuple(
                _extension_resolution(install)
                for install in extension_installs
            ),
            selected_skills=tuple(
                install.resolution for install in skill_installs
            ),
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
            profile=profile_resolution,
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


def _extension_install(
    repository: Path,
    source: Path,
    agent_targets: Tuple[str, ...],
) -> _ExtensionInstall:
    source = Path(source).expanduser().resolve()
    try:
        source.relative_to(repository)
    except ValueError as error:
        raise ValueError(
            "Harness Extension source must remain inside the repository"
        ) from error
    try:
        source_bytes = source.read_bytes()
        descriptor = yaml.safe_load(source_bytes)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read Harness Extension descriptor: {error}") from error
    if not isinstance(descriptor, dict):
        raise ValueError("Harness Extension descriptor must be a mapping")
    kind = descriptor.get("kind")
    name = descriptor.get("name")
    version = str(descriptor.get("version", ""))
    agent_target = descriptor.get("driver")
    configuration = descriptor.get("configuration")
    if kind not in {"mcp", "plugin", "hook", "command"}:
        raise ValueError("Harness Extension kind is unsupported")
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9._-]+", name) is None:
        raise ValueError("Harness Extension name is invalid")
    if re.fullmatch(r"[A-Za-z0-9._-]+", version) is None:
        raise ValueError("Harness Extension version is invalid")
    if agent_target not in agent_targets:
        raise ValueError(
            "Harness Extension Driver must match an explicit Agent target"
        )
    if not isinstance(configuration, dict):
        raise ValueError("Harness Extension configuration must be a mapping")
    declared_probe = configuration.get("harness_probe")
    if declared_probe is None:
        harness_probe: Tuple[str, ...] = ()
    elif (
        isinstance(declared_probe, list)
        and declared_probe
        and all(isinstance(value, str) and value for value in declared_probe)
    ):
        harness_probe = tuple(declared_probe)
    else:
        raise ValueError("Harness Extension availability probe is invalid")
    entrypoint = configuration.get("entrypoint")
    entrypoint_path = Path(entrypoint) if isinstance(entrypoint, str) else Path()
    if (
        not isinstance(entrypoint, str)
        or not entrypoint
        or entrypoint_path.is_absolute()
        or ".." in entrypoint_path.parts
    ):
        raise ValueError("Harness Extension entrypoint is invalid")
    if contains_symlink(repository, entrypoint_path):
        raise ValueError("Harness Extension entrypoint must not contain symlinks")
    executable = (repository / entrypoint_path).resolve()
    try:
        executable.relative_to(repository)
    except ValueError as error:
        raise ValueError(
            "Harness Extension entrypoint must remain inside the repository"
        ) from error
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Harness Extension entrypoint is not executable")
    try:
        entrypoint_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"cannot read Harness Extension entrypoint: {error}") from error
    return _ExtensionInstall(
        identity=f"{kind}:{name}@{version}",
        agent_target=agent_target,
        source=source,
        source_bytes=source_bytes,
        descriptor_sha256=hashlib.sha256(source_bytes).hexdigest(),
        destination=(
            repository / ".ai-workbench" / "extensions" / kind / f"{name}.yaml"
        ),
        descriptor=descriptor,
        repository=repository,
        entrypoint=executable,
        entrypoint_sha256=entrypoint_sha256,
        harness_probe=harness_probe,
    )


def _skill_installs(
    repository: Path,
    names: Sequence[str],
    agent_targets: Tuple[str, ...],
    catalog: SkillCatalog,
) -> Tuple[_SkillInstall, ...]:
    installs = []
    for target in agent_targets:
        target_root = repository / AGENT_SKILL_ROOTS[target]
        for name in names:
            source = catalog.install_source(repository, name, target)
            source_bytes = source.read_bytes()
            destination = target_root / name / "SKILL.md"
            resolution = HarnessSkillResolution(
                name=name,
                agent_target=target,
                source=str(source),
                destination=str(destination),
                sha256=hashlib.sha256(source_bytes).hexdigest(),
            )
            install = _SkillInstall(
                resolution=resolution,
                repository=repository,
                source=source,
                source_bytes=source_bytes,
                destination=destination,
            )
            _assert_skill_install(install)
            installs.append(install)
    return tuple(installs)


def _assert_skill_install(install: _SkillInstall) -> None:
    relative = install.destination.relative_to(install.repository)
    if contains_symlink(install.repository, relative):
        raise ValueError("Agent target Skill root must not contain symlinks")
    try:
        source_bytes = install.source.read_bytes()
    except OSError as error:
        raise ValueError(f"Skill source changed during Setup: {error}") from error
    if (
        source_bytes != install.source_bytes
        or hashlib.sha256(source_bytes).hexdigest()
        != install.resolution.sha256
    ):
        raise ValueError("Skill source changed during Setup")


def _extension_resolution(
    install: _ExtensionInstall,
) -> HarnessExtensionResolution:
    return HarnessExtensionResolution(
        identity=install.identity,
        agent_target=install.agent_target,
        source=str(install.source),
        destination=str(install.destination),
        entrypoint=str(install.entrypoint),
        descriptor_sha256=install.descriptor_sha256,
        entrypoint_sha256=install.entrypoint_sha256,
        harness_probe=install.harness_probe,
    )


def _require_unique_extension_destinations(
    installs: Sequence[_ExtensionInstall],
) -> None:
    destinations = tuple(install.destination for install in installs)
    if len(set(destinations)) != len(destinations):
        raise ValueError("duplicate Harness Extension installation target")
    for install in installs:
        _assert_extension_destination(install)


def _assert_extension_destination(install: _ExtensionInstall) -> None:
    relative = install.destination.relative_to(install.repository)
    if contains_symlink(install.repository, relative):
        raise ValueError("Harness Extension destination must not contain symlinks")
    try:
        install.destination.parent.resolve().relative_to(install.repository)
    except ValueError as error:
        raise ValueError(
            "Harness Extension destination must remain inside the repository"
        ) from error


def _assert_extension_entrypoint(install: _ExtensionInstall) -> None:
    configured = install.descriptor["configuration"]["entrypoint"]
    if contains_symlink(install.repository, Path(configured)):
        raise ValueError("Harness Extension entrypoint changed during Setup")
    current = (install.repository / configured).resolve()
    try:
        current_digest = hashlib.sha256(current.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(
            f"Harness Extension entrypoint changed during Setup: {error}"
        ) from error
    if (
        current != install.entrypoint
        or current_digest != install.entrypoint_sha256
        or not os.access(current, os.X_OK)
    ):
        raise ValueError("Harness Extension entrypoint changed during Setup")


def _run_declared_harness_probe(
    agent_target: str,
    descriptor: Mapping[str, object],
    repository: Path,
    entrypoint: Path,
) -> None:
    configuration = descriptor["configuration"]
    command = configuration.get("harness_probe")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(value, str) and value for value in command)
    ):
        raise ValueError(
            "Agent Harness extension availability probe is unavailable"
        )
    environment = os.environ.copy()
    environment["AIWB_AGENT_TARGET"] = agent_target
    environment["AIWB_EXTENSION_ENTRYPOINT"] = str(entrypoint)
    process: Optional[subprocess.Popen[bytes]] = None
    try:
        process = subprocess.Popen(
            tuple(command),
            cwd=repository,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=_EXTENSION_PROBE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise ValueError(
                "Agent Harness extension availability probe failed: TimeoutExpired"
            ) from error
    except OSError as error:
        raise ValueError(
            f"Agent Harness extension availability probe failed: {type(error).__name__}"
        ) from error
    finally:
        if process is not None:
            _terminate_process_group(process.pid)
            try:
                process.wait(timeout=_EXTENSION_PROBE_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=_EXTENSION_PROBE_REAP_SECONDS)
                except subprocess.TimeoutExpired as error:
                    raise ValueError(
                        "Agent Harness extension availability probe cleanup timed out"
                    ) from error
    if returncode:
        raise ValueError(
            "Agent Harness extension availability probe rejected the Extension"
        )


def _terminate_process_group(process_group: int) -> None:
    try:
        os.killpg(process_group, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    time.sleep(0.2)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _write_harness_profile(
    repository: Path, resolution: HarnessProfileResolution
) -> bool:
    path = repository / ".ai-workbench" / "agent-harness.yaml"
    document = yaml.safe_dump(
        harness_profile_document(resolution), sort_keys=False
    )
    if path.is_file() and path.read_text(encoding="utf-8") == document:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomically(path, document.encode("utf-8"))
    return True


def _workflow_document(path: Path) -> dict[str, object]:
    try:
        document = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read workflow: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("workflow must be a mapping")
    return document


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


def _write_bytes_atomically(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
