"""Production Agent Harness Driver for one bounded Codex Attempt.

The Driver runs `codex exec --json` inside the admitted AIWB-owned worktree and
streams the native JSONL surface into bounded ActivityEvents. It never resumes a
provider Session, never falls back to another provider, and keeps large or raw
provider payloads out of terminal summaries.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

from .agent_harness import (
    ActivityEvent,
    AgentHarnessProfile,
    AttemptOutcome,
    AttemptSpec,
)

_SUPPORTED_SANDBOX_MODES = frozenset(
    ("read-only", "workspace-write", "danger-full-access")
)
_SUPPORTED_EFFORTS = frozenset(
    ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
)
_SUPPORTED_CAPABILITIES = frozenset(("git",))
_SUPPORTED_TOOLS = frozenset(("shell", "edit"))
_SUPPORTED_ALLOWED_PATHS = (".",)
_SUPPORTED_INPUT_ARTIFACT = "contract.yaml"
_SUPPORTED_OUTPUT_SCHEMA = "attempt-outcome/v1"
_SUPPORTED_RESOURCE_LIMIT_KEYS = frozenset(("tokens",))
_SUPPORTED_NATIVE_CONFIGURATION = {"mode": "autonomous"}
_SUPPORTED_EXTENSION_KINDS = ("skill",)
_TRACE_CATEGORIES = frozenset(
    ("activity", "extension", "lifecycle", "session", "terminal", "tool", "usage")
)
_EVENT_SUMMARY_LIMIT = 1024
_OUTCOME_SUMMARY_LIMIT = 4096
_STDERR_CAPTURE_LIMIT = 4096
_TERMINATE_GRACE_SECONDS = 10.0


@dataclass(frozen=True)
class CodexDriver:
    """Execute exactly one Codex Attempt through the native codex exec surface."""

    codex_binary: str = "codex"

    def validate(self, profile: AgentHarnessProfile) -> None:
        """Fail closed before an external Codex Attempt is created."""
        if profile.driver != "codex":
            raise ValueError(f"unsupported Agent Harness Driver: {profile.driver}")
        if shutil.which(self.codex_binary) is None:
            raise ValueError(f"Codex binary is unavailable: {self.codex_binary}")
        if (
            len(profile.permissions) != 1
            or profile.permissions[0] not in _SUPPORTED_SANDBOX_MODES
        ):
            raise ValueError(
                f"unsupported Codex sandbox permissions: {', '.join(profile.permissions)}"
            )
        if profile.effort not in _SUPPORTED_EFFORTS:
            raise ValueError(f"unsupported Codex reasoning effort: {profile.effort}")
        unsupported = sorted(set(profile.capability_ceiling) - _SUPPORTED_CAPABILITIES)
        if unsupported:
            raise ValueError(f"unsupported Codex capability: {', '.join(unsupported)}")
        unsupported = sorted(set(profile.tools) - _SUPPORTED_TOOLS)
        if unsupported:
            raise ValueError(f"unsupported Codex tool: {', '.join(unsupported)}")
        if tuple(profile.allowed_paths) != _SUPPORTED_ALLOWED_PATHS:
            raise ValueError(
                "Codex supports the workspace root as the only allowed path"
            )
        if profile.input_artifact != _SUPPORTED_INPUT_ARTIFACT:
            raise ValueError(
                f"unsupported Codex input artifact: {profile.input_artifact}"
            )
        if profile.output_schema != _SUPPORTED_OUTPUT_SCHEMA:
            raise ValueError(
                f"unsupported Codex output schema: {profile.output_schema}"
            )
        unsupported = sorted(
            set(profile.resource_limits) - _SUPPORTED_RESOURCE_LIMIT_KEYS
        )
        if unsupported:
            raise ValueError(
                f"unsupported Codex resource limit: {', '.join(unsupported)}"
            )
        tokens = profile.resource_limits.get("tokens")
        if tokens is not None and (not isinstance(tokens, int) or tokens <= 0):
            raise ValueError("Codex token resource limit must be a positive integer")
        if dict(profile.native_configuration) != _SUPPORTED_NATIVE_CONFIGURATION:
            raise ValueError(
                "unsupported Codex native configuration: "
                f"{dict(profile.native_configuration)}"
            )
        for extension in profile.extensions:
            kind = extension.split(":", 1)[0]
            if kind not in _SUPPORTED_EXTENSION_KINDS:
                raise ValueError(f"unsupported Codex Harness Extension: {extension}")
        if profile.extensions and not profile.resolved_extensions:
            raise ValueError(
                "Harness Extensions were not resolved before external execution"
            )
        unsupported = sorted(set(profile.trace_coverage) - _TRACE_CATEGORIES)
        if unsupported:
            raise ValueError(
                f"unsupported Codex trace coverage: {', '.join(unsupported)}"
            )

    def execute(
        self,
        attempt_spec: AttemptSpec,
        event_sink: Callable[[ActivityEvent], None],
    ) -> AttemptOutcome:
        """Run exactly one Codex Attempt without fallback or resume semantics."""
        self.validate(attempt_spec.profile)
        profile = attempt_spec.profile
        binary = shutil.which(self.codex_binary)
        if binary is None:
            return AttemptOutcome.failed(
                "Codex Attempt failed: Codex binary unavailable"
            )
        argv = (
            binary,
            "exec",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            profile.permissions[0],
            "-m",
            profile.model,
            "-c",
            f'model_reasoning_effort="{profile.effort}"',
            "-C",
            str(attempt_spec.worktree),
            attempt_spec.instructions,
        )
        event_sink(
            ActivityEvent(kind="lifecycle", summary="Codex Attempt started")
        )
        for extension in profile.extensions:
            event_sink(
                ActivityEvent(
                    kind="extension",
                    summary=_bounded(f"Harness Extension resolved: {extension}"),
                )
            )
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            return AttemptOutcome.failed(
                f"Codex Attempt failed: {type(error).__name__}: {error}"
            )
        stderr_tail: list = []
        drain = threading.Thread(
            target=_drain_stderr,
            args=(process, stderr_tail),
            name="aiwb-codex-stderr",
            daemon=True,
        )
        drain.start()
        stream = _CodexAttemptStream()
        token_limit = profile.resource_limits.get("tokens")
        token_budget_exceeded = False
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                stream.mark_invalid_output()
                event_sink(
                    ActivityEvent(
                        kind="error",
                        summary="Codex emitted invalid output",
                        session_id=stream.session_id,
                    )
                )
                continue
            if isinstance(payload, Mapping):
                for event in stream.events_for(payload):
                    event_sink(event)
            if (
                isinstance(token_limit, int)
                and stream.usage_tokens > token_limit
            ):
                token_budget_exceeded = True
                process.terminate()
                break
        try:
            returncode = process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait()
        drain.join(timeout=_TERMINATE_GRACE_SECONDS)
        if token_budget_exceeded:
            event_sink(
                ActivityEvent(
                    kind="terminal",
                    summary="Codex Attempt failed: token budget exhausted",
                    session_id=stream.session_id,
                )
            )
            return AttemptOutcome.failed(
                "Codex Attempt failed: token budget exhausted",
                session_id=stream.session_id,
            )
        if stream.invalid_output:
            summary = "Codex Attempt failed: invalid output"
        elif stream.failure_message or returncode != 0:
            summary = _classify_failure(
                stream.failure_message, "".join(stderr_tail), returncode
            )
        else:
            event_sink(
                ActivityEvent(
                    kind="terminal",
                    summary="Codex Attempt completed",
                    session_id=stream.session_id,
                )
            )
            message = stream.last_agent_message or "Codex Attempt completed"
            return AttemptOutcome.completed(
                _bounded(message, _OUTCOME_SUMMARY_LIMIT),
                session_id=stream.session_id,
            )
        event_sink(
            ActivityEvent(
                kind="terminal",
                summary=_bounded(summary),
                session_id=stream.session_id,
            )
        )
        return AttemptOutcome.failed(summary, session_id=stream.session_id)


def _bounded(text: str, limit: int = _EVENT_SUMMARY_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _drain_stderr(process: subprocess.Popen, tail: list) -> None:
    captured = 0
    assert process.stderr is not None
    for line in process.stderr:
        if captured >= _STDERR_CAPTURE_LIMIT:
            continue
        tail.append(line)
        captured += len(line)


def _usage_tokens(usage: Mapping) -> int:
    total = 0
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value > 0:
            total += value
    return total


def _classify_failure(failure_message: str, stderr_tail: str, returncode: int) -> str:
    detail = failure_message or stderr_tail.strip()
    lowered = detail.lower()
    if any(
        marker in lowered
        for marker in ("usage limit", "rate limit", "insufficient_quota", "quota")
    ):
        return f"Codex Attempt failed: quota exhausted{_excerpt(detail)}"
    if any(
        marker in lowered
        for marker in ("401", "unauthorized", "not logged in", "authentication")
    ):
        return f"Codex Attempt failed: authentication required{_excerpt(detail)}"
    if "timed out" in lowered or "timeout" in lowered:
        return f"Codex Attempt failed: timeout{_excerpt(detail)}"
    if any(
        marker in lowered
        for marker in ("connection", "transport", "dns", "econn", "socket")
    ):
        return f"Codex Attempt failed: transport error{_excerpt(detail)}"
    if detail:
        return f"Codex Attempt failed{_excerpt(detail)}"
    return f"Codex Attempt failed: exit status {returncode}"


def _excerpt(detail: str) -> str:
    excerpt = " ".join(detail.split())[:200]
    return f": {excerpt}" if excerpt else ""


class _CodexAttemptStream:
    """Track one streamed Codex Attempt's terminal-relevant state."""

    def __init__(self) -> None:
        self.session_id = ""
        self.last_agent_message = ""
        self.failure_message = ""
        self.usage_tokens = 0
        self.invalid_output = False

    def mark_invalid_output(self) -> None:
        self.invalid_output = True

    def events_for(self, payload: Mapping) -> Tuple[ActivityEvent, ...]:
        event_type = payload.get("type")
        if event_type == "thread.started":
            self.session_id = str(payload.get("thread_id", ""))[:128]
            return (
                ActivityEvent(
                    kind="session",
                    summary="Codex Thread started",
                    session_id=self.session_id,
                ),
            )
        if event_type == "turn.started":
            return (
                ActivityEvent(
                    kind="lifecycle",
                    summary="Codex Turn started",
                    session_id=self.session_id,
                ),
            )
        if event_type == "turn.completed":
            usage = payload.get("usage")
            events = [
                ActivityEvent(
                    kind="lifecycle",
                    summary="Codex Turn completed",
                    session_id=self.session_id,
                )
            ]
            if isinstance(usage, Mapping):
                tokens = _usage_tokens(usage)
                if tokens:
                    self.usage_tokens = max(self.usage_tokens, tokens)
                    events.append(
                        ActivityEvent(
                            kind="usage",
                            summary=f"Codex usage: {tokens} tokens",
                            session_id=self.session_id,
                            usage_tokens=tokens,
                        )
                    )
            return tuple(events)
        if event_type == "turn.failed":
            error = payload.get("error")
            if isinstance(error, Mapping):
                message = str(error.get("message", ""))
            else:
                message = str(error or "")
            self.failure_message = message
            return (
                ActivityEvent(
                    kind="error",
                    summary=_bounded(f"Codex Turn failed: {message}"),
                    session_id=self.session_id,
                ),
            )
        if event_type == "error":
            message = str(payload.get("message", ""))
            if not self.failure_message:
                self.failure_message = message
            return (
                ActivityEvent(
                    kind="error",
                    summary=_bounded(f"Codex error: {message}"),
                    session_id=self.session_id,
                ),
            )
        if event_type == "item.completed":
            item = payload.get("item")
            if isinstance(item, Mapping):
                return self._item_events(item)
        return ()

    def _item_events(self, item: Mapping) -> Tuple[ActivityEvent, ...]:
        item_type = item.get("type")
        if item_type == "command_execution":
            command = str(item.get("command", ""))
            return (
                ActivityEvent(
                    kind="tool",
                    summary=_bounded(f"Codex shell: {command}"),
                    session_id=self.session_id,
                ),
            )
        if item_type == "file_change":
            changes = item.get("changes")
            paths = []
            if isinstance(changes, (list, tuple)):
                paths = [
                    str(change.get("path", ""))
                    for change in changes
                    if isinstance(change, Mapping)
                ]
            summary = (
                f"Codex file change: {', '.join(paths)}"
                if paths
                else "Codex file change"
            )
            return (
                ActivityEvent(
                    kind="edit",
                    summary=_bounded(summary),
                    session_id=self.session_id,
                ),
            )
        if item_type == "agent_message":
            text = str(item.get("text", ""))
            self.last_agent_message = text
            return (
                ActivityEvent(
                    kind="activity",
                    summary=_bounded(f"Codex message: {text}"),
                    session_id=self.session_id,
                ),
            )
        if item_type == "reasoning":
            text = str(item.get("text", ""))
            return (
                ActivityEvent(
                    kind="activity",
                    summary=_bounded(f"Codex reasoning: {text}"),
                    session_id=self.session_id,
                ),
            )
        if item_type in ("web_search", "mcp_tool_call"):
            label = "Codex web search" if item_type == "web_search" else "Codex MCP tool"
            return (
                ActivityEvent(
                    kind="tool",
                    summary=label,
                    session_id=self.session_id,
                ),
            )
        if item_type == "error":
            message = str(item.get("message", ""))
            return (
                ActivityEvent(
                    kind="error",
                    summary=_bounded(f"Codex item error: {message}"),
                    session_id=self.session_id,
                ),
            )
        return ()
