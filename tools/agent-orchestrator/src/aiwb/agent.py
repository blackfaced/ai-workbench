from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol


@dataclass(frozen=True)
class AgentRequest:
    role: str
    prompt: str
    worktree: str
    todo_id: str = ""
    sandbox: str = "workspace-write"
    model: Optional[str] = None
    timeout_seconds: int = 1800
    provider: str = "codex"


@dataclass(frozen=True)
class AgentResult:
    session_id: str
    final_output: str
    usage: Mapping[str, int] = field(default_factory=dict)


class ProviderQuotaError(RuntimeError):
    def __init__(
        self,
        provider: str,
        detail: str,
        usage: Optional[Mapping[str, int]] = None,
    ) -> None:
        safe_detail = f"{provider} provider usage limit reached"
        super().__init__(safe_detail)
        self.provider = provider
        self.detail = safe_detail
        self.usage = dict(usage) if usage else None


class AgentExecutionError(RuntimeError):
    """An Agent failure whose string form is safe for routine persistence."""

    def __init__(
        self,
        *,
        provider: str,
        role: str,
        reason: str,
        stdout: str = "",
        stderr: str = "",
        returncode: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        if reason == "timeout":
            detail = f"{provider} role {role!r} timed out after {timeout_seconds} seconds"
        else:
            detail = f"{provider} role {role!r} failed"
            if returncode is not None:
                detail += f" with exit code {returncode}"
        super().__init__(detail)
        self.provider = provider
        self.role = role
        self.reason = reason
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timeout_seconds = timeout_seconds


class AgentAdapter(Protocol):
    """The only seam between orchestration and an external Agent CLI."""

    def run(self, request: AgentRequest) -> AgentResult:
        ...


class AgentRouter:
    """Route each immutable Agent request to exactly one configured provider."""

    def __init__(self, adapters: Mapping[str, AgentAdapter]) -> None:
        self._adapters = dict(adapters)

    def run(self, request: AgentRequest) -> AgentResult:
        try:
            adapter = self._adapters[request.provider]
        except KeyError as error:
            raise RuntimeError(
                f"Agent provider is not configured: {request.provider}"
            ) from error
        return adapter.run(request)


class CodexCliAdapter:
    """Run one fresh, non-interactive Codex session for an Agent role."""

    def __init__(self, executable: str = "codex") -> None:
        self._executable = executable

    def run(self, request: AgentRequest) -> AgentResult:
        command = [
            self._executable,
            "exec",
            "--json",
            "--ignore-user-config",
            "--cd",
            request.worktree,
            "--sandbox",
            request.sandbox,
        ]
        if request.model:
            command.extend(["--model", request.model])
        command.append(request.prompt)

        try:
            completed = _run_captured(
                command,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentExecutionError(
                provider=request.provider,
                role=request.role,
                reason="timeout",
                stdout=_output_text(error.stdout),
                stderr=_output_text(error.stderr),
                timeout_seconds=request.timeout_seconds,
            ) from None
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            if _is_provider_quota(detail):
                raise ProviderQuotaError(
                    provider=request.provider,
                    detail=detail,
                )
            raise AgentExecutionError(
                provider=request.provider,
                role=request.role,
                reason="nonzero_exit",
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
            )

        session_id = ""
        final_output = ""
        usage: Mapping[str, int] = {}
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = session_id or _find_string(
                event,
                ("thread_id", "threadId", "session_id", "sessionId"),
            )
            message = _agent_message(event)
            if message:
                final_output = message
            reported_usage = _normalize_usage(event.get("usage"))
            if reported_usage:
                usage = reported_usage

        if not session_id:
            raise RuntimeError("Codex JSONL output did not include a session identifier")

        return AgentResult(
            session_id=session_id,
            final_output=final_output or completed.stdout.strip(),
            usage=usage,
        )


class ClaudeCodeCliAdapter:
    """Run one fresh, non-interactive Claude Code session for an Agent role."""

    def __init__(
        self,
        executable: str = "claude",
        permission_mode: str = "auto",
    ) -> None:
        if permission_mode not in {"auto", "acceptEdits", "dontAsk"}:
            raise ValueError(
                "Claude Code permission mode must be auto, acceptEdits, or dontAsk"
            )
        self._executable = executable
        self._permission_mode = permission_mode

    def run(self, request: AgentRequest) -> AgentResult:
        command = [
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--setting-sources",
            "project,local",
            "--strict-mcp-config",
            "--permission-mode",
            "plan" if request.sandbox == "read-only" else self._permission_mode,
        ]
        if request.model:
            command.extend(["--model", request.model])
        command.append(request.prompt)

        try:
            completed = _run_captured(
                command,
                cwd=request.worktree,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentExecutionError(
                provider=request.provider,
                role=request.role,
                reason="timeout",
                stdout=_output_text(error.stdout),
                stderr=_output_text(error.stderr),
                timeout_seconds=request.timeout_seconds,
            ) from None
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            if _is_provider_quota(detail):
                raise ProviderQuotaError(
                    provider=request.provider,
                    detail=detail,
                )
            raise AgentExecutionError(
                provider=request.provider,
                role=request.role,
                reason="nonzero_exit",
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
            )

        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("Claude Code output was not valid JSON") from error
        if not isinstance(result, dict):
            raise RuntimeError("Claude Code JSON output must be an object")
        if result.get("is_error") is True:
            detail = str(result.get("result", ""))
            if _is_provider_quota(detail):
                raise ProviderQuotaError(
                    provider=request.provider,
                    detail=detail,
                    usage=_normalize_usage(result.get("usage")),
                )
            raise AgentExecutionError(
                provider=request.provider,
                role=request.role,
                reason="reported_error",
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        session_id = result.get("session_id")
        final_output = result.get("result")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("Claude Code JSON output did not include a session identifier")
        return AgentResult(
            session_id=session_id,
            final_output=final_output if isinstance(final_output, str) else "",
            usage=_normalize_usage(result.get("usage")),
        )


def _find_string(value: object, keys: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for candidate in value.values():
            found = _find_string(candidate, keys)
            if found:
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _find_string(candidate, keys)
            if found:
                return found
    return ""


def _run_captured(
    command: list[str],
    *,
    cwd: Optional[str] = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, \
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
        try:
            completed = subprocess.run(
                command,
                check=False,
                cwd=cwd,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            stdout_file.seek(0)
            stderr_file.seek(0)
            error.output = stdout_file.read()
            error.stderr = stderr_file.read()
            raise
        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            args=completed.args,
            returncode=completed.returncode,
            stdout=stdout_file.read(),
            stderr=stderr_file.read(),
        )


def _output_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _agent_message(event: object) -> str:
    if not isinstance(event, dict):
        return ""
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "agent_message":
        return ""
    text = item.get("text")
    return text if isinstance(text, str) else ""


def _normalize_usage(value: object) -> Mapping[str, int]:
    if not isinstance(value, dict):
        return {}
    usage = {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str)
        and key.endswith("_tokens")
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }
    if usage and "total_tokens" not in usage:
        usage["total_tokens"] = sum(usage.values())
    return usage


def _is_provider_quota(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "usage limit",
            "quota",
            "rate limit",
            "too many requests",
            "credit balance",
        )
    )
