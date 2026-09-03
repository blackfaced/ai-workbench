"""The small external boundary for one bounded Agent Harness Attempt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Protocol, Tuple


@dataclass(frozen=True)
class AgentHarnessProfile:
    driver: str
    model: str
    effort: str
    permissions: Tuple[str, ...]
    capability_ceiling: Tuple[str, ...]
    extensions: Tuple[str, ...]
    allowed_paths: Tuple[str, ...]
    tools: Tuple[str, ...]
    input_artifact: str
    output_schema: str
    timeout_seconds: int
    max_attempts: int
    resource_limits: Mapping[str, object]
    native_configuration: Mapping[str, object]
    trace_coverage: Tuple[str, ...]
    resolved_extensions: Tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "permissions", "capability_ceiling", "extensions", "allowed_paths",
            "tools", "trace_coverage",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not all(isinstance(value, str) and value for value in (self.driver, self.model, self.effort)):
            raise ValueError("Agent Harness Profile identity must be non-empty")
        for name, values in (
            ("permissions", self.permissions),
            ("capability_ceiling", self.capability_ceiling),
            ("extensions", self.extensions),
            ("allowed_paths", self.allowed_paths),
            ("tools", self.tools),
            ("trace_coverage", self.trace_coverage),
        ):
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"Agent Harness Profile {name} must be non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"Agent Harness Profile {name} must be unique")
        if not self.input_artifact or not self.output_schema:
            raise ValueError("Agent Harness Profile input and output contracts must be non-empty")
        if self.timeout_seconds <= 0 or self.max_attempts <= 0:
            raise ValueError("Agent Harness Profile limits must be positive")
        if not self.resource_limits or not self.native_configuration:
            raise ValueError("Agent Harness Profile resource and native configuration must be explicit")
        object.__setattr__(self, "resource_limits", _freeze_mapping(self.resource_limits))
        object.__setattr__(self, "native_configuration", _freeze_mapping(self.native_configuration))
        object.__setattr__(
            self,
            "resolved_extensions",
            tuple(_freeze_mapping(value) for value in self.resolved_extensions),
        )
        if self.resolved_extensions and tuple(
            value.get("identity") for value in self.resolved_extensions
        ) != self.extensions:
            raise ValueError("resolved Harness Extensions must match their Profile identities")

    def __reduce__(self):
        """Keep the immutable profile transferable to an isolated Attempt process."""
        return (
            type(self),
            (
                self.driver, self.model, self.effort, self.permissions,
                self.capability_ceiling, self.extensions, self.allowed_paths,
                self.tools, self.input_artifact, self.output_schema,
                self.timeout_seconds, self.max_attempts,
                _thaw_mapping(self.resource_limits), _thaw_mapping(self.native_configuration),
                self.trace_coverage,
                tuple(_thaw_mapping(value) for value in self.resolved_extensions),
            ),
        )


@dataclass(frozen=True)
class AttemptSpec:
    run_id: str
    attempt_id: str
    worktree: Path
    instructions: str
    profile: AgentHarnessProfile

    def __post_init__(self) -> None:
        if not self.run_id or not self.attempt_id or not self.instructions:
            raise ValueError("AttemptSpec identity and instructions must be non-empty")


@dataclass(frozen=True)
class ActivityEvent:
    kind: str
    summary: str
    session_id: str = ""
    usage_tokens: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.kind or not self.summary:
            raise ValueError("ActivityEvent kind and summary must be non-empty")
        if self.kind not in {
            "activity", "edit", "error", "extension", "lifecycle", "session",
            "status", "terminal", "tool", "usage",
        }:
            raise ValueError("ActivityEvent kind is not declared by the common trace vocabulary")
        if len(self.kind) > 32:
            raise ValueError("ActivityEvent kind exceeds the bounded limit")
        if len(self.summary) > 1024:
            raise ValueError("ActivityEvent summary exceeds the bounded limit")
        if len(self.session_id) > 128:
            raise ValueError("ActivityEvent session_id exceeds the bounded limit")
        if self.usage_tokens is not None and self.usage_tokens < 0:
            raise ValueError("ActivityEvent usage_tokens must not be negative")

    @classmethod
    def activity(cls, kind: str, summary: str) -> "ActivityEvent":
        return cls(kind=kind, summary=summary)


@dataclass(frozen=True)
class AttemptOutcome:
    status: str
    summary: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "interrupted"}:
            raise ValueError("AttemptOutcome must be terminal")
        if len(self.summary) > 4096:
            raise ValueError("AttemptOutcome summary exceeds the bounded limit")
        if len(self.session_id) > 128:
            raise ValueError("AttemptOutcome session_id exceeds the bounded limit")

    @classmethod
    def completed(cls, summary: str = "", session_id: str = "") -> "AttemptOutcome":
        return cls("completed", summary, session_id)

    @classmethod
    def failed(cls, summary: str = "", session_id: str = "") -> "AttemptOutcome":
        return cls("failed", summary, session_id)

    @classmethod
    def interrupted(cls, summary: str = "", session_id: str = "") -> "AttemptOutcome":
        return cls("interrupted", summary, session_id)


class AgentHarnessDriver(Protocol):
    def validate(self, profile: AgentHarnessProfile) -> None:
        """Fail closed before an external Harness Attempt is created."""

    def execute(
        self,
        attempt_spec: AttemptSpec,
        event_sink: Callable[[ActivityEvent], None],
    ) -> AttemptOutcome:
        """Run exactly one Attempt without fallback or resume semantics."""


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(entry) for key, entry in item.items()})
        if isinstance(item, (tuple, list)):
            return tuple(freeze(entry) for entry in item)
        return item

    return MappingProxyType({str(key): freeze(item) for key, item in value.items()})


def _thaw_mapping(value: Mapping[str, object]) -> dict[str, object]:
    def thaw(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): thaw(entry) for key, entry in item.items()}
        if isinstance(item, tuple):
            return tuple(thaw(entry) for entry in item)
        return item

    return {str(key): thaw(item) for key, item in value.items()}
