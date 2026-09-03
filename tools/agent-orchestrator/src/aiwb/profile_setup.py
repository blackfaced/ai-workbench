"""Resolve one exact Agent Harness Profile during guided setup.

Resolution is read-only: it discovers the selected Harness's model catalog
without starting an Attempt, fails closed on unsupported Models, reasoning
efforts, or Extensions, and locks the resolved Profile, Extension digests, and
catalog evidence behind one digest so any drift requires a new explicit setup.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

import yaml

from .agent_harness import AgentHarnessProfile
from .codex_driver import CodexDriver
from .skills import AGENT_SKILL_ROOTS

_CODEX_DISCOVERY_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class HarnessProfileSelections:
    """The owner's explicit Harness Profile selections for one setup."""

    model: str
    effort: str = ""
    permissions: Tuple[str, ...] = ("workspace-write",)
    capability_ceiling: Tuple[str, ...] = ("git",)
    tools: Tuple[str, ...] = ("shell",)
    allowed_paths: Tuple[str, ...] = (".",)
    extensions: Tuple[str, ...] = ()
    timeout_seconds: int = 1800
    max_attempts: int = 1
    resource_limits: Mapping[str, object] = field(
        default_factory=lambda: {"tokens": 100000}
    )
    native_configuration: Mapping[str, object] = field(
        default_factory=lambda: {"mode": "autonomous"}
    )
    trace_coverage: Tuple[str, ...] = ("activity",)
    input_artifact: str = "contract.yaml"
    output_schema: str = "attempt-outcome/v1"


@dataclass(frozen=True)
class HarnessModelDescriptor:
    slug: str
    default_effort: str
    efforts: Tuple[str, ...]
    visibility: str


@dataclass(frozen=True)
class HarnessModelCatalog:
    binary: str
    version: str
    resolved_at: str
    catalog_sha256: str
    models: Tuple[HarnessModelDescriptor, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "binary": self.binary,
            "version": self.version,
            "resolved_at": self.resolved_at,
            "catalog_sha256": self.catalog_sha256,
            "models": [
                {
                    "slug": model.slug,
                    "default_effort": model.default_effort,
                    "efforts": list(model.efforts),
                    "visibility": model.visibility,
                }
                for model in self.models
            ],
        }


@dataclass(frozen=True)
class HarnessExtensionDigest:
    identity: str
    path: str
    sha256: str
    entrypoint_sha256: str = ""

    def to_dict(self) -> Mapping[str, object]:
        return {
            "identity": self.identity,
            "path": self.path,
            "sha256": self.sha256,
            "entrypoint_sha256": self.entrypoint_sha256,
        }


@dataclass(frozen=True)
class HarnessProfileResolution:
    profile: AgentHarnessProfile
    catalog: HarnessModelCatalog
    internal_role_models: Tuple[str, ...]
    extensions: Tuple[HarnessExtensionDigest, ...]
    profile_digest: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "profile": harness_profile_mapping(self.profile),
            "profile_digest": self.profile_digest,
            "catalog": self.catalog.to_dict(),
            "internal_role_models": list(self.internal_role_models),
            "extensions": [extension.to_dict() for extension in self.extensions],
        }


def harness_profile_mapping(profile: AgentHarnessProfile) -> Mapping[str, object]:
    """The contract-ready agent_harness mapping for one resolved Profile."""
    return {
        "driver": profile.driver,
        "model": profile.model,
        "effort": profile.effort,
        "permissions": list(profile.permissions),
        "capability_ceiling": list(profile.capability_ceiling),
        "extensions": list(profile.extensions),
        "allowed_paths": list(profile.allowed_paths),
        "tools": list(profile.tools),
        "input_artifact": profile.input_artifact,
        "output_schema": profile.output_schema,
        "timeout_seconds": profile.timeout_seconds,
        "max_attempts": profile.max_attempts,
        "resource_limits": dict(profile.resource_limits),
        "native_configuration": dict(profile.native_configuration),
        "trace_coverage": list(profile.trace_coverage),
    }


def harness_profile_document(resolution: HarnessProfileResolution) -> Mapping[str, object]:
    """The persisted .ai-workbench/agent-harness.yaml document.

    Freshness evidence (resolved_at) is display-only and stays out of the
    persisted document so an unchanged resolved Profile is idempotent.
    """
    catalog = resolution.catalog
    return {
        "schema_version": 1,
        "profile_digest": resolution.profile_digest,
        "agent_harness": harness_profile_mapping(resolution.profile),
        "catalog": {
            "binary": catalog.binary,
            "version": catalog.version,
            "catalog_sha256": catalog.catalog_sha256,
        },
        "extensions": [extension.to_dict() for extension in resolution.extensions],
    }


def resolve_harness_profile(
    repository: Path,
    selections: HarnessProfileSelections,
    agent_targets: Tuple[str, ...],
    *,
    driver: Optional[CodexDriver] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> HarnessProfileResolution:
    """Resolve one exact Agent Harness Profile without starting an Attempt."""
    repository = Path(repository).expanduser().resolve()
    if not selections.model.strip():
        raise ValueError("Harness Profile resolution requires an explicit Model")
    if tuple(agent_targets) != ("codex",):
        raise ValueError(
            "Harness Profile resolution requires exactly the codex Agent target"
        )
    driver = driver or CodexDriver()
    catalog = _discover_model_catalog(driver.codex_binary, clock)
    models = {model.slug: model for model in catalog.models}
    descriptor = models.get(selections.model)
    if descriptor is None:
        raise ValueError(f"Model is not in the Codex catalog: {selections.model}")
    if descriptor.visibility != "list":
        raise ValueError(
            "Model is an internal Harness identifier, not a selectable primary "
            f"Model: {selections.model}"
        )
    effort = selections.effort or descriptor.default_effort
    if effort not in descriptor.efforts:
        raise ValueError(
            f"Model {selections.model} does not support reasoning effort: {effort}"
        )
    extensions = tuple(
        _resolve_extension(repository, identity)
        for identity in selections.extensions
    )
    profile = AgentHarnessProfile(
        driver="codex",
        model=selections.model,
        effort=effort,
        permissions=tuple(selections.permissions),
        capability_ceiling=tuple(selections.capability_ceiling),
        extensions=tuple(selections.extensions),
        allowed_paths=tuple(selections.allowed_paths),
        tools=tuple(selections.tools),
        input_artifact=selections.input_artifact,
        output_schema=selections.output_schema,
        timeout_seconds=selections.timeout_seconds,
        max_attempts=selections.max_attempts,
        resource_limits=dict(selections.resource_limits),
        native_configuration=dict(selections.native_configuration),
        trace_coverage=tuple(selections.trace_coverage),
        resolved_extensions=tuple(
            {
                "identity": extension.identity,
                "path": extension.path,
                "sha256": extension.sha256,
            }
            for extension in extensions
        ),
    )
    driver.validate(profile)
    digest_material = {
        "profile": harness_profile_mapping(profile),
        "extensions": [extension.to_dict() for extension in extensions],
        "catalog_sha256": catalog.catalog_sha256,
        "driver_version": catalog.version,
    }
    profile_digest = hashlib.sha256(
        _canonical_json(digest_material).encode("utf-8")
    ).hexdigest()
    return HarnessProfileResolution(
        profile=profile,
        catalog=catalog,
        internal_role_models=tuple(
            model.slug for model in catalog.models if model.visibility != "list"
        ),
        extensions=extensions,
        profile_digest=profile_digest,
    )


def _discover_model_catalog(
    binary: str,
    clock: Optional[Callable[[], datetime]],
) -> HarnessModelCatalog:
    path = shutil.which(binary)
    if path is None:
        raise ValueError(f"Codex binary is unavailable: {binary}")
    version = _run_codex_discovery(path, ("--version",)).strip()
    raw = _run_codex_discovery(path, ("debug", "models"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Codex model catalog is invalid: {error}") from error
    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("Codex model catalog is invalid: missing models")
    models = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Codex model catalog entry is invalid")
        slug = entry.get("slug")
        levels = entry.get("supported_reasoning_levels")
        efforts = (
            tuple(
                str(level.get("effort"))
                for level in levels
                if isinstance(level, dict) and level.get("effort")
            )
            if isinstance(levels, list)
            else ()
        )
        if not isinstance(slug, str) or not slug or not efforts:
            raise ValueError("Codex model catalog entry is invalid")
        models.append(
            HarnessModelDescriptor(
                slug=slug,
                default_effort=str(entry.get("default_reasoning_level", "")),
                efforts=efforts,
                visibility=str(entry.get("visibility", "")),
            )
        )
    instant = (clock or (lambda: datetime.now(timezone.utc)))()
    return HarnessModelCatalog(
        binary=path,
        version=version,
        resolved_at=instant.astimezone(timezone.utc).isoformat(),
        catalog_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        models=tuple(models),
    )


def _run_codex_discovery(binary: str, arguments: Tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            (binary, *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_CODEX_DISCOVERY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(
            f"Codex discovery command failed: {type(error).__name__}"
        ) from error
    if completed.returncode != 0:
        raise ValueError(
            f"Codex discovery command failed: exit status {completed.returncode}"
        )
    return completed.stdout


def _resolve_extension(repository: Path, identity: str) -> HarnessExtensionDigest:
    match = re.fullmatch(
        r"(skill|mcp|plugin|hook|command):([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+)",
        identity,
    )
    if match is None:
        raise ValueError(f"Harness extension is unsupported or unresolved: {identity}")
    kind, name, version = match.groups()
    if kind == "skill":
        skill_root = AGENT_SKILL_ROOTS.get("codex")
        candidates = (
            f"{skill_root}/{name}/SKILL.md",
            f".agents/skills/{name}/SKILL.md",
            f"skills/{name}/SKILL.md",
        )
    else:
        candidates = (f".ai-workbench/extensions/{kind}/{name}.yaml",)
    for relative in candidates:
        source = repository / relative
        if not source.is_file():
            continue
        source_bytes = source.read_bytes()
        try:
            text = source_bytes.decode("utf-8")
            if kind == "skill":
                if not text.startswith("---\n"):
                    raise ValueError("missing metadata")
                end = text.find("\n---\n", 4)
                if end == -1:
                    raise ValueError("unterminated metadata")
                metadata = yaml.safe_load(text[4:end])
            else:
                metadata = yaml.safe_load(text)
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
            raise ValueError(
                f"Harness extension metadata is invalid: {identity}: {error}"
            ) from error
        if not isinstance(metadata, Mapping):
            raise ValueError(f"Harness extension metadata is invalid: {identity}")
        if (
            metadata.get("name") != name
            or str(metadata.get("version", "")) != version
            or (kind != "skill" and metadata.get("kind") != kind)
        ):
            raise ValueError(
                f"Harness extension identity or version does not match: {identity}"
            )
        digest = HarnessExtensionDigest(
            identity=identity,
            path=relative,
            sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
        if kind != "skill":
            configuration = metadata.get("configuration")
            entrypoint = (
                configuration.get("entrypoint")
                if isinstance(configuration, Mapping)
                else None
            )
            entrypoint_path = (
                (repository / entrypoint).resolve()
                if isinstance(entrypoint, str) and entrypoint
                else None
            )
            if entrypoint_path is None or not entrypoint_path.is_file():
                raise ValueError(
                    f"Harness extension has no callable entrypoint: {identity}"
                )
            digest = replace(
                digest,
                entrypoint_sha256=hashlib.sha256(
                    entrypoint_path.read_bytes()
                ).hexdigest(),
            )
        return digest
    raise ValueError(f"Harness extension is not installed: {identity}")


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
