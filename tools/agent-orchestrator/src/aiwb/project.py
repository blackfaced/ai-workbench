from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import yaml


_ROLE_NAMES = frozenset(
    {"test_designer", "implementer", "verifier", "conflict_repairer"}
)
_MAX_ROLE_SKILL_BYTES = 16 * 1024
_MAX_ROLE_GUIDANCE_BYTES = 32 * 1024


@dataclass(frozen=True)
class ProjectInitResult:
    config: str
    status: str
    suggestions: int


@dataclass(frozen=True)
class ProjectInitPreview:
    config: str
    suggestions: int
    document: Mapping[str, object]


class ProjectInitError(RuntimeError):
    pass


class ProjectConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserDiagnosticProfile:
    adapter: str
    command: Tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class HarnessProfile:
    name: str
    kind: str
    environment: str
    start_command: Tuple[str, ...] = field(default_factory=tuple)
    ready_url: str = ""
    ready_timeout_seconds: int = 0
    browser_gate: str = ""
    browser_diagnostic: Optional[BrowserDiagnosticProfile] = None
    kubernetes_context: str = ""
    namespace_prefix: str = ""
    ttl_seconds: int = 0
    provision_command: Tuple[str, ...] = field(default_factory=tuple)
    collect_command: Tuple[str, ...] = field(default_factory=tuple)
    cleanup_command: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ImageProfile:
    name: str
    environment: str
    start_command: Tuple[str, ...]
    status_command: Tuple[str, ...]
    result_command: Tuple[str, ...]


@dataclass(frozen=True)
class CandidatePublishProfile:
    remote: str
    branch_prefix: str


@dataclass(frozen=True)
class ProjectPolicy:
    repository: Path
    candidate_commands: Tuple[Mapping[str, object], ...]
    approved_commands: Tuple[Tuple[str, ...], ...]
    role_skill_texts: Mapping[str, Tuple[Tuple[str, str], ...]]
    harness_profiles: Mapping[str, HarnessProfile]
    image_profiles: Mapping[str, ImageProfile]
    candidate_publish: Optional[CandidatePublishProfile]

    @classmethod
    def load(cls, config_path: Path) -> "ProjectPolicy":
        config_path = Path(config_path).expanduser().resolve()
        try:
            data = yaml.safe_load(config_path.read_bytes())
        except (OSError, yaml.YAMLError) as error:
            raise ProjectConfigError(f"cannot read project policy: {error}") from error
        if not isinstance(data, dict):
            raise ProjectConfigError("project policy must be a YAML mapping")
        if data.get("schema_version") != 1:
            raise ProjectConfigError("project policy schema_version must be 1")
        if data.get("status") != "approved":
            raise ProjectConfigError("project policy status must be approved")

        project = data.get("project")
        if not isinstance(project, dict):
            raise ProjectConfigError("project policy project must be a mapping")
        if project.get("trusted") is not True:
            raise ProjectConfigError("project must be explicitly trusted")
        root = project.get("root")
        if not isinstance(root, str) or not root:
            raise ProjectConfigError("project policy root must be a non-empty string")
        repository = Path(root).expanduser().resolve()

        capabilities = data.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ProjectConfigError("project policy capabilities must be a mapping")
        candidate_commands = _load_candidate_commands(data)
        commands = capabilities.get("commands")
        if not isinstance(commands, dict) or not commands:
            raise ProjectConfigError("project policy requires an approved command")
        approved_commands = []
        for name, definition in commands.items():
            if not isinstance(definition, dict) or definition.get("approved") is not True:
                raise ProjectConfigError(f"project command {name!r} must be approved")
            argv = definition.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(item, str) and item for item in argv)
            ):
                raise ProjectConfigError(
                    f"project command {name!r} argv must be a non-empty string list"
                )
            approved_commands.append(tuple(argv))

        role_skill_texts = _load_role_skill_texts(capabilities, repository)
        environments_ok, detail = ProjectDoctor._validate_environments(data)
        if not environments_ok:
            raise ProjectConfigError(detail)
        harness_profiles = _load_harness_profiles(data, tuple(approved_commands))
        image_profiles = _load_image_profiles(data, tuple(approved_commands))
        candidate_publish = _load_candidate_publish_profile(data)
        return cls(
            repository=repository,
            candidate_commands=candidate_commands,
            approved_commands=tuple(approved_commands),
            role_skill_texts=role_skill_texts,
            harness_profiles=harness_profiles,
            image_profiles=image_profiles,
            candidate_publish=candidate_publish,
        )

    def authorize(
        self,
        repository: Path,
        command: Tuple[str, ...],
        harness_name: str = "",
    ) -> Optional[HarnessProfile]:
        if Path(repository).resolve() != self.repository:
            raise ProjectConfigError(
                "Contract repository does not match the trusted project policy root"
            )
        if command not in self.approved_commands:
            raise ProjectConfigError(
                "Contract test command is not an approved project capability"
            )
        if not harness_name:
            return None
        profile = self.harness_profiles.get(harness_name)
        if profile is None:
            raise ProjectConfigError(
                f"Contract Harness profile is not approved: {harness_name}"
            )
        if profile.browser_gate == "playwright" and not any(
            "playwright" in part.lower() for part in command
        ):
            raise ProjectConfigError(
                f"Harness profile {harness_name!r} requires a Playwright Test command"
            )
        return profile

    def authorize_image(self, image_profile_name: str) -> Optional[ImageProfile]:
        if not image_profile_name:
            return None
        profile = self.image_profiles.get(image_profile_name)
        if profile is None:
            raise ProjectConfigError(
                f"Contract image profile is not approved: {image_profile_name}"
            )
        return profile

    def authorize_publish(self, repository: Path) -> Optional[CandidatePublishProfile]:
        profile = self.candidate_publish
        if profile is None:
            return None
        if Path(repository).resolve() != self.repository:
            raise ProjectConfigError(
                "Candidate publishing repository does not match project policy root"
            )
        remote = subprocess.run(
            ["git", "-C", str(self.repository), "remote", "get-url", profile.remote],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if remote.returncode != 0:
            raise ProjectConfigError(
                f"Candidate publishing remote is not configured: {profile.remote}"
            )
        return profile


def _load_candidate_commands(
    data: Mapping[str, object],
) -> Tuple[Mapping[str, object], ...]:
    suggestions = data.get("suggestions", {})
    if not isinstance(suggestions, dict):
        raise ProjectConfigError("suggestions must be a mapping")
    commands = suggestions.get("commands", {})
    if not isinstance(commands, dict):
        return ()
    result = []
    for name, definition in commands.items():
        if not isinstance(name, str) or not name or not isinstance(definition, dict):
            continue
        argv = definition.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            continue
        reason = definition.get("reason", "")
        if not isinstance(reason, str):
            continue
        result.append({"name": name, "argv": list(argv), "reason": reason})
    return tuple(result)


def _load_role_skill_texts(
    capabilities: Mapping[str, object],
    repository: Path,
) -> Mapping[str, Tuple[Tuple[str, str], ...]]:
    skills = capabilities.get("skills", {})
    if not isinstance(skills, dict):
        raise ProjectConfigError("capabilities.skills must be a mapping")
    role_skill_texts: Dict[str, Tuple[Tuple[str, str], ...]] = {}
    for role, paths in skills.items():
        if not isinstance(role, str) or role not in _ROLE_NAMES:
            raise ProjectConfigError(f"capabilities.skills has unsupported role: {role!r}")
        if not isinstance(paths, list) or not paths:
            raise ProjectConfigError(
                f"capabilities.skills.{role} must be a non-empty list of paths"
            )
        seen = set()
        guidance_bytes = 0
        entries = []
        for value in paths:
            if not isinstance(value, str) or not value:
                raise ProjectConfigError(
                    f"capabilities.skills.{role} paths must be non-empty strings"
                )
            relative_path = Path(value)
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.name != "SKILL.md"
            ):
                raise ProjectConfigError(
                    f"capabilities.skills.{role} must reference a local SKILL.md"
                )
            resolved_path = (repository / relative_path).resolve()
            try:
                resolved_path.relative_to(repository)
            except ValueError as error:
                raise ProjectConfigError(
                    f"capabilities.skills.{role} must stay inside project.root"
                ) from error
            if not resolved_path.is_file():
                raise ProjectConfigError(
                    f"capabilities.skills.{role} file does not exist: {value}"
                )
            stable_path = resolved_path.relative_to(repository).as_posix()
            if stable_path in seen:
                raise ProjectConfigError(
                    f"capabilities.skills.{role} contains a duplicate path: {stable_path}"
                )
            try:
                content = resolved_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise ProjectConfigError(
                    f"cannot read capabilities.skills.{role}: {error}"
                ) from error
            content_bytes = len(content.encode("utf-8"))
            if not content.strip() or content_bytes > _MAX_ROLE_SKILL_BYTES:
                raise ProjectConfigError(
                    f"capabilities.skills.{role} must be non-empty and at most "
                    f"{_MAX_ROLE_SKILL_BYTES} bytes"
                )
            guidance_bytes += content_bytes
            if guidance_bytes > _MAX_ROLE_GUIDANCE_BYTES:
                raise ProjectConfigError(
                    f"capabilities.skills.{role} exceeds {_MAX_ROLE_GUIDANCE_BYTES} bytes"
                )
            seen.add(stable_path)
            entries.append((stable_path, content))
        role_skill_texts[role] = tuple(entries)
    return role_skill_texts


def _load_candidate_publish_profile(
    data: Mapping[str, object],
) -> Optional[CandidatePublishProfile]:
    publishing = data.get("publishing", {})
    if not isinstance(publishing, dict):
        raise ProjectConfigError("publishing must be a mapping")
    candidate = publishing.get("candidate")
    if candidate is None:
        return None
    if not isinstance(candidate, dict):
        raise ProjectConfigError("publishing.candidate must be a mapping")
    if candidate.get("approved") is not True:
        raise ProjectConfigError("Candidate publishing must be explicitly approved")
    remote = candidate.get("remote")
    if (
        not isinstance(remote, str)
        or not remote
        or remote.startswith("-")
        or any(character.isspace() for character in remote)
    ):
        raise ProjectConfigError("Candidate publishing remote must be a safe Git remote")
    branch_prefix = candidate.get("branch_prefix")
    if (
        not isinstance(branch_prefix, str)
        or not branch_prefix.endswith("/")
        or branch_prefix.startswith("/")
        or ".." in branch_prefix
        or any(character in branch_prefix for character in " ~^:?*[\\")
    ):
        raise ProjectConfigError(
            "Candidate publishing branch_prefix must be a safe namespace ending in /"
        )
    return CandidatePublishProfile(remote=remote, branch_prefix=branch_prefix)


def _load_harness_profiles(
    data: Mapping[str, object],
    approved_commands: Tuple[Tuple[str, ...], ...],
) -> Mapping[str, HarnessProfile]:
    harness = data.get("harness", {})
    if not isinstance(harness, dict):
        raise ProjectConfigError("harness must be a mapping")
    profiles = harness.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ProjectConfigError("harness.profiles must be a mapping")
    allowed_contexts_value = harness.get("allowed_kubernetes_contexts", [])
    if not isinstance(allowed_contexts_value, list) or not all(
        isinstance(item, str) and item for item in allowed_contexts_value
    ):
        raise ProjectConfigError(
            "harness.allowed_kubernetes_contexts must be a string list"
        )
    allowed_contexts = tuple(allowed_contexts_value)
    result: Dict[str, HarnessProfile] = {}
    for name, value in profiles.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ProjectConfigError("Harness profile definitions must be mappings")
        if value.get("kind") is None:
            continue
        result[name] = _parse_harness_profile(
            name,
            value,
            approved_commands,
            allowed_contexts,
        )
    return result


def _parse_harness_profile(
    name: str,
    value: Mapping[str, object],
    approved_commands: Tuple[Tuple[str, ...], ...],
    allowed_kubernetes_contexts: Tuple[str, ...],
) -> HarnessProfile:
    kind = value.get("kind")
    if kind == "kubernetes":
        return _parse_kubernetes_harness_profile(
            name,
            value,
            approved_commands,
            allowed_kubernetes_contexts,
        )
    environment = value.get("environment")
    if kind != "local_process" or environment != "local":
        raise ProjectConfigError(
            f"Harness profile {name!r} must be kind local_process in local environment"
        )
    start = value.get("start")
    ready = value.get("ready")
    if not isinstance(start, dict) or not isinstance(ready, dict):
        raise ProjectConfigError(
            f"Harness profile {name!r} requires start and ready mappings"
        )
    start_command = _command_tuple(start.get("command"), f"Harness {name!r} start")
    if start_command not in approved_commands:
        raise ProjectConfigError(f"Harness profile {name!r} start command is not approved")
    ready_url = ready.get("url")
    if not isinstance(ready_url, str) or "{port}" not in ready_url:
        raise ProjectConfigError(
            f"Harness profile {name!r} ready.url must contain {{port}}"
        )
    parsed = urlparse(ready_url.replace("{port}", "1"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ProjectConfigError(
            f"Harness profile {name!r} readiness must use loopback HTTP"
        )
    ready_timeout = ready.get("timeout_seconds", 30)
    if not isinstance(ready_timeout, int) or ready_timeout <= 0:
        raise ProjectConfigError(
            f"Harness profile {name!r} ready timeout must be positive"
        )
    browser_gate = value.get("browser_gate", "")
    if browser_gate not in {"", "playwright"}:
        raise ProjectConfigError(
            f"Harness profile {name!r} browser pass Evidence requires Playwright Test"
        )
    browser_diagnostic = _parse_browser_diagnostic(
        name,
        value.get("browser_diagnostic"),
        browser_gate,
        approved_commands,
    )
    return HarnessProfile(
        name=name,
        kind=kind,
        environment=environment,
        start_command=start_command,
        ready_url=ready_url,
        ready_timeout_seconds=ready_timeout,
        browser_gate=browser_gate,
        browser_diagnostic=browser_diagnostic,
    )


def _parse_browser_diagnostic(
    harness_name: str,
    value: object,
    browser_gate: str,
    approved_commands: Tuple[Tuple[str, ...], ...],
) -> Optional[BrowserDiagnosticProfile]:
    if value is None:
        return None
    if browser_gate != "playwright":
        raise ProjectConfigError(
            f"Harness profile {harness_name!r} browser diagnostics require a Playwright gate"
        )
    if not isinstance(value, dict):
        raise ProjectConfigError(
            f"Harness profile {harness_name!r} browser_diagnostic must be a mapping"
        )
    adapter = value.get("adapter")
    if adapter not in {"playwright-mcp", "chrome-devtools-mcp"}:
        raise ProjectConfigError(
            f"Harness profile {harness_name!r} browser diagnostic adapter is unsupported"
        )
    command = _command_tuple(
        value.get("command"),
        f"Harness {harness_name!r} browser diagnostic",
    )
    if command not in approved_commands:
        raise ProjectConfigError(
            f"Harness profile {harness_name!r} browser diagnostic command is not approved"
        )
    timeout_seconds = value.get("timeout_seconds", 120)
    if (
        not isinstance(timeout_seconds, int)
        or timeout_seconds <= 0
        or timeout_seconds > 300
    ):
        raise ProjectConfigError(
            f"Harness profile {harness_name!r} browser diagnostic timeout must be 1-300 seconds"
        )
    return BrowserDiagnosticProfile(
        adapter=str(adapter),
        command=command,
        timeout_seconds=timeout_seconds,
    )


def _parse_kubernetes_harness_profile(
    name: str,
    value: Mapping[str, object],
    approved_commands: Tuple[Tuple[str, ...], ...],
    allowed_contexts: Tuple[str, ...],
) -> HarnessProfile:
    environment = value.get("environment")
    if environment != "non-production":
        raise ProjectConfigError(
            f"Kubernetes Harness profile {name!r} must be non-production"
        )
    context = value.get("context")
    if not isinstance(context, str) or context not in allowed_contexts:
        raise ProjectConfigError(
            f"Kubernetes Harness profile {name!r} context is not allowlisted"
        )
    namespace_prefix = value.get("namespace_prefix")
    if (
        not isinstance(namespace_prefix, str)
        or not namespace_prefix
        or len(namespace_prefix) > 30
        or not all(character.islower() or character.isdigit() or character == "-" for character in namespace_prefix)
        or namespace_prefix.startswith("-")
        or namespace_prefix.endswith("-")
    ):
        raise ProjectConfigError(
            f"Kubernetes Harness profile {name!r} namespace_prefix must be a DNS label"
        )
    ttl_seconds = value.get("ttl_seconds")
    if not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= 86400:
        raise ProjectConfigError(
            f"Kubernetes Harness profile {name!r} ttl_seconds must be 60..86400"
        )
    commands = {}
    for operation in ("provision", "collect", "cleanup"):
        definition = value.get(operation)
        if not isinstance(definition, dict):
            raise ProjectConfigError(
                f"Kubernetes Harness profile {name!r} requires {operation} mapping"
            )
        command = _command_tuple(
            definition.get("command"),
            f"Kubernetes Harness {name!r} {operation}",
        )
        if command not in approved_commands:
            raise ProjectConfigError(
                f"Kubernetes Harness profile {name!r} {operation} command is not approved"
            )
        commands[operation] = command
    browser_gate = value.get("browser_gate", "")
    if browser_gate not in {"", "playwright"}:
        raise ProjectConfigError(
            f"Harness profile {name!r} browser pass Evidence requires Playwright Test"
        )
    browser_diagnostic = _parse_browser_diagnostic(
        name,
        value.get("browser_diagnostic"),
        browser_gate,
        approved_commands,
    )
    return HarnessProfile(
        name=name,
        kind="kubernetes",
        environment=environment,
        browser_gate=browser_gate,
        browser_diagnostic=browser_diagnostic,
        kubernetes_context=context,
        namespace_prefix=namespace_prefix,
        ttl_seconds=ttl_seconds,
        provision_command=commands["provision"],
        collect_command=commands["collect"],
        cleanup_command=commands["cleanup"],
    )


def _command_tuple(value: object, name: str) -> Tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ProjectConfigError(f"{name} command must be a non-empty string list")
    return tuple(value)


def _load_image_profiles(
    data: Mapping[str, object],
    approved_commands: Tuple[Tuple[str, ...], ...],
) -> Mapping[str, ImageProfile]:
    images = data.get("images", {})
    if not isinstance(images, dict):
        raise ProjectConfigError("images must be a mapping")
    profiles = images.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ProjectConfigError("images.profiles must be a mapping")
    result: Dict[str, ImageProfile] = {}
    for name, value in profiles.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ProjectConfigError("image profile definitions must be mappings")
        result[name] = _parse_image_profile(name, value, approved_commands)
    return result


def _parse_image_profile(
    name: str,
    value: Mapping[str, object],
    approved_commands: Tuple[Tuple[str, ...], ...],
) -> ImageProfile:
    environment = value.get("environment")
    if environment in {"production", "prod"}:
        raise ProjectConfigError(f"production image profile is forbidden: {name}")
    if environment not in {"local", "non-production"}:
        raise ProjectConfigError(
            f"image profile {name!r} environment must be local or non-production"
        )
    commands = {}
    for operation in ("start", "status", "result"):
        definition = value.get(operation)
        if not isinstance(definition, dict):
            raise ProjectConfigError(
                f"image profile {name!r} requires {operation} mapping"
            )
        command = _command_tuple(
            definition.get("command"),
            f"image profile {name!r} {operation}",
        )
        if command not in approved_commands:
            raise ProjectConfigError(
                f"image profile {name!r} {operation} command is not approved"
            )
        commands[operation] = command
    return ImageProfile(
        name=name,
        environment=environment,
        start_command=commands["start"],
        status_command=commands["status"],
        result_command=commands["result"],
    )


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    status: str
    checks: Tuple[DoctorCheck, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "checks": [check.__dict__ for check in self.checks],
        }


class ProjectInitializer:
    """Discover repository capabilities and render an inert draft configuration."""

    def preview(
        self,
        repository: Path,
        output_path: Optional[Path] = None,
    ) -> ProjectInitPreview:
        repository = Path(repository).expanduser().resolve()
        if not repository.is_dir():
            raise ProjectInitError(f"repository is not a directory: {repository}")
        output_path = (
            Path(output_path).expanduser().resolve()
            if output_path
            else repository / ".ai-workbench" / "workflow.yaml"
        )
        document, suggestions = self._draft_document(repository)
        return ProjectInitPreview(
            config=str(output_path),
            suggestions=suggestions,
            document=document,
        )

    def initialize(
        self,
        repository: Path,
        output_path: Optional[Path] = None,
        force: bool = False,
    ) -> ProjectInitResult:
        preview = self.preview(repository, output_path)
        output_path = Path(preview.config)
        if output_path.exists() and not force:
            raise ProjectInitError(
                f"configuration already exists: {output_path}; use --force to replace it"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump(preview.document, sort_keys=False),
            encoding="utf-8",
        )
        return ProjectInitResult(
            config=preview.config,
            status="draft",
            suggestions=preview.suggestions,
        )

    def _draft_document(self, repository: Path) -> Tuple[Mapping[str, object], int]:
        skills = self._discover_skills(repository)
        scripts = self._discover_scripts(repository)
        signals: List[str] = []
        suggestions: Dict[str, Mapping[str, object]] = {}

        if self._has_playwright(repository):
            signals.append("playwright")
            suggestions["browser_e2e"] = {
                "argv": ["npx", "playwright", "test"],
                "reason": "playwright configuration detected",
            }
        if self._has_pytest(repository):
            signals.append("pytest")
            suggestions["unit"] = {
                "argv": [sys.executable, "-m", "pytest", "-q"],
                "reason": "pytest configuration or tests directory detected",
            }
        local_e2e = next(
            (
                script
                for script in scripts
                if "e2e" in Path(script).name.lower()
                and os.access(repository / script, os.X_OK)
            ),
            None,
        )
        if local_e2e:
            suggestions["local_e2e"] = {
                "argv": [f"./{local_e2e}"],
                "reason": "executable repository script detected",
            }

        document = {
            "schema_version": 1,
            "status": "draft",
            "project": {"root": str(repository), "trusted": False},
            "discovery": {
                "skills": skills,
                "scripts": scripts,
                "signals": sorted(signals),
            },
            "suggestions": {"commands": dict(sorted(suggestions.items()))},
            "capabilities": {"commands": {}, "skills": {}},
            "harness": {
                "allowed_kubernetes_contexts": [],
                "profiles": {},
            },
            "images": {"profiles": {}},
        }
        return document, len(suggestions)

    @staticmethod
    def _discover_skills(repository: Path) -> List[str]:
        paths = []
        for root_name in (
            ".agents/skills",
            ".claude/skills",
            ".codex/skills",
            "skills",
        ):
            root = repository / root_name
            if root.is_dir():
                paths.extend(
                    str(path.relative_to(repository))
                    for path in root.rglob("SKILL.md")
                    if path.is_file()
                )
        return sorted(set(paths))

    @staticmethod
    def _discover_scripts(repository: Path) -> List[str]:
        paths = []
        for root_name in ("scripts", "harness"):
            root = repository / root_name
            if root.is_dir():
                paths.extend(
                    str(path.relative_to(repository))
                    for path in root.rglob("*")
                    if path.is_file()
                )
        return sorted(set(paths))

    @staticmethod
    def _has_pytest(repository: Path) -> bool:
        if (repository / "tests").is_dir() or (repository / "pytest.ini").is_file():
            return True
        pyproject = repository / "pyproject.toml"
        return pyproject.is_file() and "pytest" in _read_small_text(pyproject).lower()

    @staticmethod
    def _has_playwright(repository: Path) -> bool:
        if any(repository.glob("playwright.config.*")):
            return True
        package = repository / "package.json"
        if not package.is_file():
            return False
        try:
            content = json.loads(_read_small_text(package))
        except json.JSONDecodeError:
            return False
        if not isinstance(content, dict):
            return False
        dependencies = {
            **_string_mapping(content.get("dependencies")),
            **_string_mapping(content.get("devDependencies")),
        }
        return any("playwright" in name.lower() for name in dependencies)


class ProjectDoctor:
    """Validate an approved project configuration without executing capabilities."""

    def inspect(
        self,
        config_path: Path,
        codex_bin: str = "codex",
        agent_provider: str = "codex",
        claude_bin: str = "claude",
    ) -> DoctorReport:
        config_path = Path(config_path).expanduser().resolve()
        try:
            data = yaml.safe_load(config_path.read_bytes())
        except (OSError, yaml.YAMLError) as error:
            raise ProjectConfigError(f"cannot read project configuration: {error}") from error
        if not isinstance(data, dict):
            raise ProjectConfigError("project configuration must be a YAML mapping")

        checks: List[DoctorCheck] = []
        checks.append(
            _check(
                "schema",
                data.get("schema_version") == 1,
                "schema_version is 1",
                "schema_version must be 1",
            )
        )
        checks.append(
            _check(
                "approved",
                data.get("status") == "approved",
                "configuration is approved",
                "configuration status must be approved",
            )
        )

        project = data.get("project")
        project = project if isinstance(project, dict) else {}
        checks.append(
            _check(
                "trusted",
                project.get("trusted") is True,
                "repository is explicitly trusted",
                "project.trusted must be true",
            )
        )
        root_value = project.get("root")
        repository = (
            Path(root_value).expanduser().resolve()
            if isinstance(root_value, str) and root_value
            else None
        )
        repository_ok = repository is not None and repository.is_dir()
        if repository_ok:
            repository_ok = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "--is-inside-work-tree"],
                check=False,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
        checks.append(
            _check(
                "repository",
                repository_ok,
                f"Git repository is available at {repository}",
                "project.root must identify a Git repository",
            )
        )

        provider_bin = claude_bin if agent_provider == "claude-code" else codex_bin
        provider_name = "Claude Code" if agent_provider == "claude-code" else "Codex"
        provider_path = shutil.which(provider_bin)
        checks.append(
            _check(
                "provider",
                provider_path is not None,
                f"{provider_name} executable is available at {provider_path}",
                f"{provider_name} executable is unavailable: {provider_bin}",
            )
        )

        commands_ok, commands_detail = self._validate_commands(data, repository)
        checks.append(
            _check(
                "commands",
                commands_ok,
                commands_detail,
                commands_detail,
            )
        )
        non_production_ok, environment_detail = self._validate_environments(data)
        checks.append(
            _check(
                "non_production",
                non_production_ok,
                environment_detail,
                environment_detail,
            )
        )
        publishing_ok, publishing_detail = self._validate_publishing(data, repository)
        checks.append(
            _check(
                "publishing",
                publishing_ok,
                publishing_detail,
                publishing_detail,
            )
        )

        status = "ok" if all(check.status == "pass" for check in checks) else "failed"
        return DoctorReport(status=status, checks=tuple(checks))

    @staticmethod
    def _validate_publishing(
        data: Mapping[str, object],
        repository: Optional[Path],
    ) -> Tuple[bool, str]:
        try:
            profile = _load_candidate_publish_profile(data)
        except ProjectConfigError as error:
            return False, str(error)
        if profile is None:
            return True, "Candidate publishing is disabled"
        if repository is None:
            return False, "Candidate publishing requires a valid Git repository"
        remote = subprocess.run(
            ["git", "-C", str(repository), "remote", "get-url", profile.remote],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if remote.returncode != 0:
            return False, f"Candidate publishing remote is not configured: {profile.remote}"
        return (
            True,
            f"Candidate publishing is approved for {profile.remote}/{profile.branch_prefix}",
        )

    @staticmethod
    def _validate_commands(
        data: Mapping[str, object],
        repository: Optional[Path],
    ) -> Tuple[bool, str]:
        capabilities = data.get("capabilities")
        if not isinstance(capabilities, dict):
            return False, "capabilities must be a mapping"
        commands = capabilities.get("commands")
        if not isinstance(commands, dict) or not commands:
            return False, "at least one approved command is required"
        for name, definition in commands.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                return False, "command definitions must be mappings"
            if definition.get("approved") is not True:
                return False, f"command {name!r} is not approved"
            argv = definition.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(item, str) and item for item in argv)
            ):
                return False, f"command {name!r} argv must be a non-empty string list"
            executable = argv[0]
            if "/" in executable:
                path = Path(executable).expanduser()
                if not path.is_absolute() and repository is not None:
                    path = repository / path
                available = path.is_file() and os.access(path, os.X_OK)
            else:
                available = shutil.which(executable) is not None
            if not available:
                return False, f"command {name!r} executable is unavailable: {executable}"
        return True, f"{len(commands)} approved command(s) are available"

    @staticmethod
    def _validate_environments(data: Mapping[str, object]) -> Tuple[bool, str]:
        harness = data.get("harness")
        if harness is None:
            return True, "no Harness profiles request production access"
        if not isinstance(harness, dict):
            return False, "harness must be a mapping"
        profiles = harness.get("profiles", {})
        if not isinstance(profiles, dict):
            return False, "harness.profiles must be a mapping"
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                return False, f"Harness profile {name!r} must be a mapping"
            environment = str(profile.get("environment", "")).lower()
            if str(name).lower() in {"production", "prod"} or environment in {
                "production",
                "prod",
            }:
                return False, f"production Harness profile is forbidden: {name}"
        capabilities = data.get("capabilities", {})
        commands = capabilities.get("commands", {}) if isinstance(capabilities, dict) else {}
        approved_commands = tuple(
            tuple(definition["argv"])
            for definition in commands.values()
            if isinstance(definition, dict)
            and definition.get("approved") is True
            and isinstance(definition.get("argv"), list)
        ) if isinstance(commands, dict) else tuple()
        try:
            _load_harness_profiles(data, approved_commands)
            image_profiles = _load_image_profiles(data, approved_commands)
        except ProjectConfigError as error:
            return False, str(error)
        return True, (
            f"{len(profiles)} Harness and {len(image_profiles)} image profile(s) "
            "are non-production"
        )


def _read_small_text(path: Path, limit: int = 1024 * 1024) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as source:
        return source.read(limit)


def _string_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _check(name: str, passed: bool, success: str, failure: str) -> DoctorCheck:
    return DoctorCheck(
        name=name,
        status="pass" if passed else "fail",
        detail=success if passed else failure,
    )
