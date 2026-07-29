from __future__ import annotations

import configparser
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9 and 3.10
    import tomli as tomllib


@dataclass(frozen=True)
class CapabilityAssessment:
    name: str
    disposition: str
    command: Tuple[str, ...]
    evidence: Tuple[str, ...]
    confidence: str
    reason: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "disposition": self.disposition,
            "command": list(self.command),
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TargetProfile:
    path: str
    language: str
    purpose_tags: Tuple[str, ...]
    capabilities: Tuple[CapabilityAssessment, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "path": self.path,
            "language": self.language,
            "purpose_tags": list(self.purpose_tags),
            "capabilities": [
                capability.to_dict() for capability in self.capabilities
            ],
        }


@dataclass(frozen=True)
class EvidenceStatus:
    name: str
    status: str
    detail: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CodeStructureEvidence:
    provider: str
    confidence: str
    source_roots: Tuple[str, ...]
    test_roots: Tuple[str, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "provider": self.provider,
            "confidence": self.confidence,
            "source_roots": list(self.source_roots),
            "test_roots": list(self.test_roots),
        }


@dataclass(frozen=True)
class ExternalAnalysisEvidence:
    code_structure: Optional[CodeStructureEvidence] = None
    remote_review_history: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectProfile:
    repository: str
    targets: Tuple[TargetProfile, ...]
    build_system: str
    pipeline_files: Tuple[str, ...]
    git_history: Tuple[str, ...]
    remote_review_history: Tuple[str, ...]
    code_structure: CodeStructureEvidence
    unavailable_evidence: Tuple[EvidenceStatus, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "repository": self.repository,
            "targets": [target.to_dict() for target in self.targets],
            "build_system": self.build_system,
            "pipeline_files": list(self.pipeline_files),
            "git_history": list(self.git_history),
            "remote_review_history": list(self.remote_review_history),
            "code_structure": self.code_structure.to_dict(),
            "unavailable_evidence": [
                evidence.to_dict() for evidence in self.unavailable_evidence
            ],
        }


@dataclass(frozen=True)
class CommandCandidate:
    name: str
    argv: Tuple[str, ...]
    working_directory: str
    source: str
    confidence: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PythonPlanningResult:
    profile: ProjectProfile
    command_candidates: Tuple[CommandCandidate, ...]
    owner_decisions: Tuple[str, ...]


def inspect_python_l0(
    repository: Path,
    external_analysis: Optional[ExternalAnalysisEvidence] = None,
    analysis_error: str = "",
) -> PythonPlanningResult:
    repository = Path(repository).expanduser().resolve()
    target_roots = _python_target_roots(repository)
    if not target_roots:
        raise ValueError("python-l0 planning requires a Python project target")

    targets = []
    build_systems = []
    all_source_roots = []
    all_test_roots = []
    for root in target_roots:
        metadata = _target_metadata(root)
        capabilities = _capabilities(metadata)
        relative_root = _relative(root, repository)
        purpose_tags = _purpose_tags(root, metadata)
        targets.append(
            TargetProfile(
                path=relative_root,
                language="python",
                purpose_tags=purpose_tags,
                capabilities=capabilities,
            )
        )
        if metadata.build_backend:
            build_systems.append(metadata.build_backend)
        all_source_roots.extend(
            _relative(path, repository)
            for path in _source_roots(root)
        )
        all_test_roots.extend(
            _relative(path, repository)
            for path in _test_roots(root)
        )

    pipeline_files = tuple(
        sorted(
            _relative(path, repository)
            for pattern in (
                ".github/workflows/*",
                ".gitlab-ci.yml",
                "Jenkinsfile",
                "buildkite.yml",
            )
            for path in repository.glob(pattern)
            if path.is_file()
        )
    )
    git_history, history_status = _bounded_git_history(repository)
    fallback_structure = CodeStructureEvidence(
        provider="filesystem",
        confidence="medium",
        source_roots=tuple(sorted(set(all_source_roots))),
        test_roots=tuple(sorted(set(all_test_roots))),
    )
    code_structure = (
        external_analysis.code_structure
        if external_analysis is not None
        and external_analysis.code_structure is not None
        else fallback_structure
    )
    remote_review_history = (
        external_analysis.remote_review_history
        if external_analysis is not None
        else ()
    )
    unavailable = []
    if code_structure == fallback_structure:
        unavailable.append(
            EvidenceStatus(
                name="code_graph",
                status="unavailable",
                detail=(
                    analysis_error
                    or (
                        "No approved code-graph analysis result was supplied; "
                        "filesystem structure was used."
                    )
                ),
            )
        )
    if not remote_review_history:
        unavailable.append(
            EvidenceStatus(
                name="remote_review_history",
                status="unavailable",
                detail=(
                    analysis_error
                    or (
                        "Remote review history was not queried during read-only "
                        "repository assessment."
                    )
                ),
            )
        )
    if history_status is not None:
        unavailable.append(history_status)
    profile = ProjectProfile(
        repository=str(repository),
        targets=tuple(targets),
        build_system=", ".join(sorted(set(build_systems))) or "unknown",
        pipeline_files=pipeline_files,
        git_history=git_history,
        remote_review_history=remote_review_history,
        code_structure=code_structure,
        unavailable_evidence=tuple(unavailable),
    )
    return planning_from_profile(profile)


def planning_from_profile(profile: ProjectProfile) -> PythonPlanningResult:
    command_candidates = tuple(
        CommandCandidate(
            name=(
                capability.name
                if target.path == "."
                else f"{target.path}:{capability.name}"
            ),
            argv=capability.command,
            working_directory=target.path,
            source=capability.evidence[0],
            confidence=capability.confidence,
        )
        for target in profile.targets
        for capability in target.capabilities
        if capability.command
    )
    owner_decisions = tuple(
        decision
        for decision in (
            (
                "Confirm the canonical lint and formatting commands."
                if any(
                    capability.name in {"lint", "format"}
                    and capability.disposition != "keep"
                    for target in profile.targets
                    for capability in target.capabilities
                )
                else ""
            ),
            "Approve a measured coverage baseline before setting a threshold.",
            (
                "Confirm whether static type checking is required for this target."
                if any(
                    capability.name == "typecheck"
                    and capability.disposition == "adopt"
                    for target in profile.targets
                    for capability in target.capabilities
                )
                else ""
            ),
        )
        if decision
    )
    return PythonPlanningResult(
        profile=profile,
        command_candidates=command_candidates,
        owner_decisions=owner_decisions,
    )


@dataclass(frozen=True)
class _TargetMetadata:
    build_backend: str
    dependencies: Tuple[str, ...]
    sections: Tuple[str, ...]
    entry_points: Tuple[str, ...]


def _python_target_roots(repository: Path) -> Tuple[Path, ...]:
    roots = {
        path.parent
        for name in ("pyproject.toml", "setup.cfg")
        for path in repository.glob(f"**/{name}")
        if not set(path.relative_to(repository).parts) & _IGNORED_DIRECTORY_NAMES
    }
    return tuple(
        sorted(
            roots,
            key=lambda path: (
                len(path.relative_to(repository).parts),
                path.as_posix(),
            ),
        )
    )


_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


def _target_metadata(root: Path) -> _TargetMetadata:
    build_backend = ""
    dependencies = []
    sections = []
    entry_points = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot parse {pyproject}: {error}") from error
        build = data.get("build-system", {})
        if isinstance(build, dict):
            backend = build.get("build-backend")
            if isinstance(backend, str):
                build_backend = backend
        project = data.get("project", {})
        if isinstance(project, dict):
            dependencies.extend(_strings(project.get("dependencies")))
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for values in optional.values():
                    dependencies.extend(_strings(values))
            scripts = project.get("scripts", {})
            if isinstance(scripts, dict):
                entry_points.extend(str(name) for name in scripts)
        tool = data.get("tool", {})
        if isinstance(tool, dict):
            sections.extend(str(name).lower() for name in tool)

    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(setup_cfg, encoding="utf-8")
        except configparser.Error as error:
            raise ValueError(f"cannot parse {setup_cfg}: {error}") from error
        sections.extend(section.lower() for section in parser.sections())
        for section in ("options", "options.extras_require"):
            if parser.has_section(section):
                for _, value in parser.items(section):
                    dependencies.extend(
                        line.strip()
                        for line in value.splitlines()
                        if line.strip()
                    )
        if parser.has_section("options.entry_points"):
            entry_points.extend(name for name, _ in parser.items("options.entry_points"))

    return _TargetMetadata(
        build_backend=build_backend,
        dependencies=tuple(dependencies),
        sections=tuple(sections),
        entry_points=tuple(entry_points),
    )


def _capabilities(
    metadata: _TargetMetadata,
) -> Tuple[CapabilityAssessment, ...]:
    dependency_text = " ".join(metadata.dependencies).lower()
    sections = set(metadata.sections)
    has_pytest = "pytest" in dependency_text or "pytest" in sections
    has_ruff = "ruff" in dependency_text or "ruff" in sections
    has_flake8 = "flake8" in dependency_text or "flake8" in sections
    has_black = "black" in dependency_text or "black" in sections
    has_coverage = (
        "pytest-cov" in dependency_text
        or "coverage" in dependency_text
        or "coverage" in sections
    )
    type_tool = next(
        (
            name
            for name in ("mypy", "pyright")
            if name in dependency_text or name in sections
        ),
        ""
    )
    capabilities = [
        _capability(
            "unit",
            "keep" if has_pytest else "adopt",
            ("python3", "-m", "pytest", "-q"),
            "pytest project metadata" if has_pytest else "Python target structure",
            "high" if has_pytest else "medium",
            "Preserve the existing Pytest path."
            if has_pytest
            else "No project-owned unit test runner was detected.",
        ),
        _capability(
            "lint",
            "keep" if has_flake8 or has_ruff else "adopt",
            (
                ("python3", "-m", "flake8", ".")
                if has_flake8
                else ("python3", "-m", "ruff", "check", ".")
            ),
            (
                "Flake8 project metadata"
                if has_flake8
                else "Ruff project metadata"
                if has_ruff
                else "Python target structure"
            ),
            "high" if has_flake8 or has_ruff else "medium",
            "Preserve the existing Flake8 lint path."
            if has_flake8
            else "Preserve the existing Ruff lint path."
            if has_ruff
            else "No project-owned lint tool was detected.",
        ),
        _capability(
            "format",
            "keep" if has_black or has_ruff else "adopt",
            (
                ("python3", "-m", "black", "--check", ".")
                if has_black
                else ("python3", "-m", "ruff", "format", "--check", ".")
            ),
            (
                "Black project metadata"
                if has_black
                else "Ruff project metadata"
                if has_ruff
                else "Python target structure"
            ),
            "high" if has_black or has_ruff else "medium",
            "Preserve the existing Black formatter."
            if has_black
            else "Preserve the existing Ruff formatter."
            if has_ruff
            else "No project-owned formatting tool was detected.",
        ),
        _capability(
            "typecheck",
            "keep" if type_tool else "adopt",
            (
                ("python3", "-m", type_tool, ".")
                if type_tool
                else ("python3", "-m", "mypy", ".")
            ),
            f"{type_tool} project metadata" if type_tool else "Python target structure",
            "high" if type_tool else "low",
            f"Preserve the existing {type_tool} path."
            if type_tool
            else "No project-owned type checker was detected.",
        ),
        _capability(
            "coverage",
            "augment" if has_coverage else "adopt",
            (
                "python3",
                "-m",
                "pytest",
                "--cov",
                "--cov-report=xml",
            ),
            (
                "coverage project metadata"
                if has_coverage
                else "Python target structure"
            ),
            "high" if has_coverage else "low",
            (
                "Coverage tooling exists, but the measured baseline and "
                "threshold remain owner decisions."
                if has_coverage
                else "No project-owned coverage tool was detected."
            ),
        ),
    ]
    if has_flake8 and has_ruff:
        capabilities.append(
            _capability(
                "ruff_lint_migration",
                "migrate_later",
                ("python3", "-m", "ruff", "check", "."),
                "Flake8 and Ruff project metadata",
                "high",
                "Keep Flake8 working; evaluate Ruff consolidation separately.",
            )
        )
    if has_black and has_ruff:
        capabilities.append(
            _capability(
                "ruff_format_migration",
                "migrate_later",
                ("python3", "-m", "ruff", "format", "--check", "."),
                "Black and Ruff project metadata",
                "high",
                "Keep Black working; evaluate Ruff consolidation separately.",
            )
        )
    return tuple(capabilities)


def _capability(
    name: str,
    disposition: str,
    command: Tuple[str, ...],
    evidence: str,
    confidence: str,
    reason: str,
) -> CapabilityAssessment:
    return CapabilityAssessment(
        name=name,
        disposition=disposition,
        command=command,
        evidence=(evidence,),
        confidence=confidence,
        reason=reason,
    )


def _purpose_tags(root: Path, metadata: _TargetMetadata) -> Tuple[str, ...]:
    tags = []
    if _source_roots(root):
        tags.append("library")
    if _test_roots(root):
        tags.append("test")
    if metadata.entry_points:
        tags.append("cli")
    return tuple(tags or ["library"])


def _source_roots(root: Path) -> Tuple[Path, ...]:
    candidates = [root / "src"]
    return tuple(path for path in candidates if path.is_dir())


def _test_roots(root: Path) -> Tuple[Path, ...]:
    candidates = [root / "tests", root / "test"]
    return tuple(path for path in candidates if path.is_dir())


def _bounded_git_history(
    repository: Path,
) -> Tuple[Tuple[str, ...], Optional[EvidenceStatus]]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "log",
            "--max-count=20",
            "--format=%H%x09%s",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    if completed.returncode != 0:
        return (), EvidenceStatus(
            name="local_git_history",
            status="unavailable",
            detail="The repository has no readable local Git history.",
        )
    return (
        tuple(line for line in completed.stdout.splitlines() if line),
        None,
    )


def _strings(value: object) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _relative(path: Path, repository: Path) -> str:
    relative = path.relative_to(repository).as_posix()
    return relative or "."
