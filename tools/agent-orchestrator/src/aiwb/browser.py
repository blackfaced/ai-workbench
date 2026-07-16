from __future__ import annotations

import base64
import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol, TextIO, Tuple

from .project import BrowserDiagnosticProfile


@dataclass(frozen=True)
class BrowserDiagnosticRequest:
    profile: BrowserDiagnosticProfile
    base_url: str
    cwd: Path
    artifact_dir: Path
    run_id: str
    execution_id: str
    gate_stdout: str
    gate_stderr: str


@dataclass(frozen=True)
class BrowserDiagnosticResult:
    adapter: str
    summary: str
    artifacts: Tuple[str, ...] = field(default_factory=tuple)
    error: str = ""


class BrowserDiagnosticAdapter(Protocol):
    """Inspect a live browser target without deciding whether its gate passed."""

    def diagnose(self, request: BrowserDiagnosticRequest) -> BrowserDiagnosticResult:
        ...


class BrowserDiagnosticError(RuntimeError):
    pass


_TOOL_PLANS: Mapping[str, Tuple[Tuple[str, Mapping[str, object]], ...]] = {
    "playwright-mcp": (
        ("browser_navigate", {}),
        ("browser_snapshot", {}),
        ("browser_console_messages", {"level": "debug", "all": True}),
        ("browser_network_requests", {"static": False}),
        ("browser_take_screenshot", {"type": "png", "fullPage": True}),
    ),
    "chrome-devtools-mcp": (
        ("new_page", {}),
        ("take_snapshot", {"verbose": False}),
        ("list_console_messages", {"includePreservedMessages": True}),
        ("list_network_requests", {"includePreservedRequests": True}),
        ("take_screenshot", {"format": "png", "fullPage": True}),
    ),
}


class McpBrowserDiagnosticAdapter:
    """Collect a bounded, read-mostly diagnostic bundle from an approved MCP server."""

    def diagnose(self, request: BrowserDiagnosticRequest) -> BrowserDiagnosticResult:
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        gate_failure = request.artifact_dir / "gate-failure.json"
        _write_json(
            gate_failure,
            {
                "base_url": request.base_url,
                "execution_id": request.execution_id,
                "stdout": request.gate_stdout,
                "stderr": request.gate_stderr,
            },
        )
        stderr_path = request.artifact_dir / "mcp-server.stderr.log"
        environment = os.environ.copy()
        environment.update(
            {
                "AIWB_ARTIFACT_DIR": str(request.artifact_dir),
                "AIWB_BASE_URL": request.base_url,
                "AIWB_BROWSER_DIAGNOSTIC_ADAPTER": request.profile.adapter,
                "AIWB_RUN_ID": request.run_id,
                "NO_COLOR": "1",
            }
        )
        artifacts = [str(gate_failure), str(stderr_path)]
        plan = _TOOL_PLANS.get(request.profile.adapter)
        if plan is None:
            raise BrowserDiagnosticError(
                f"unsupported browser diagnostic adapter: {request.profile.adapter}"
            )

        with _McpSession(
            command=request.profile.command,
            cwd=request.cwd,
            environment=environment,
            stderr_path=stderr_path,
            timeout_seconds=request.profile.timeout_seconds,
        ) as session:
            session.initialize()
            available = session.list_tools()
            missing = [name for name, _ in plan if name not in available]
            if missing:
                raise BrowserDiagnosticError(
                    "browser MCP server is missing required tools: " + ", ".join(missing)
                )
            for index, (name, default_arguments) in enumerate(plan):
                arguments = dict(default_arguments)
                if index == 0:
                    arguments["url"] = request.base_url
                result = session.call_tool(name, arguments)
                artifact_name = _artifact_name(index)
                artifact_path = request.artifact_dir / f"{artifact_name}.json"
                _write_json(artifact_path, result)
                artifacts.append(str(artifact_path))
                if index == len(plan) - 1:
                    screenshot = _image_content(result)
                    if screenshot is not None:
                        screenshot_path = request.artifact_dir / "browser-screenshot.png"
                        screenshot_path.write_bytes(screenshot)
                        artifacts.append(str(screenshot_path))

        return BrowserDiagnosticResult(
            adapter=request.profile.adapter,
            summary=(
                f"Captured {len(plan)} browser observations with "
                f"{request.profile.adapter}; the failing gate remains authoritative."
            ),
            artifacts=tuple(artifacts),
        )


class _McpSession:
    def __init__(
        self,
        command: Tuple[str, ...],
        cwd: Path,
        environment: Mapping[str, str],
        stderr_path: Path,
        timeout_seconds: int,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._environment = environment
        self._stderr_path = stderr_path
        self._timeout_seconds = timeout_seconds
        self._deadline = 0.0
        self._next_id = 1
        self._messages: "queue.Queue[Optional[Mapping[str, object]]]" = queue.Queue()
        self._stderr_file: Optional[TextIO] = None
        self._process: Optional[subprocess.Popen[str]] = None

    def __enter__(self) -> "_McpSession":
        self._stderr_file = self._stderr_path.open("w", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                list(self._command),
                cwd=str(self._cwd),
                env=dict(self._environment),
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                bufsize=1,
                start_new_session=True,
            )
        except Exception:
            self._stderr_file.close()
            self._stderr_file = None
            raise
        self._deadline = time.monotonic() + self._timeout_seconds
        reader = threading.Thread(target=self._read_messages, daemon=True)
        reader.start()
        return self

    def __exit__(self, *unused: object) -> None:
        process = self._required_process()
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        if self._stderr_file is not None:
            self._stderr_file.close()

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "ai-workbench", "version": "0.1"},
            },
        )
        self._notify("notifications/initialized", {})

    def list_tools(self) -> Tuple[str, ...]:
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise BrowserDiagnosticError("browser MCP tools/list returned invalid tools")
        return tuple(
            str(tool["name"])
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        )

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        if result.get("isError") is True:
            raise BrowserDiagnosticError(
                f"browser MCP tool {name} returned an error result"
            )
        return result

    def _request(
        self,
        method: str,
        params: Mapping[str, object],
    ) -> Mapping[str, object]:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserDiagnosticError("browser MCP diagnostic timed out")
            try:
                message = self._messages.get(timeout=remaining)
            except queue.Empty as error:
                raise BrowserDiagnosticError("browser MCP diagnostic timed out") from error
            if message is None:
                returncode = self._required_process().poll()
                raise BrowserDiagnosticError(
                    f"browser MCP server exited before response with code {returncode}"
                )
            if message.get("id") != request_id:
                continue
            rpc_error = message.get("error")
            if rpc_error is not None:
                raise BrowserDiagnosticError(
                    f"browser MCP {method} failed: {rpc_error}"
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise BrowserDiagnosticError(
                    f"browser MCP {method} returned an invalid result"
                )
            return result

    def _notify(self, method: str, params: Mapping[str, object]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, value: Mapping[str, object]) -> None:
        process = self._required_process()
        if process.stdin is None:
            raise BrowserDiagnosticError("browser MCP stdin is unavailable")
        process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def _read_messages(self) -> None:
        process = self._required_process()
        if process.stdout is None:
            self._messages.put(None)
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                self._messages.put(message)
        self._messages.put(None)

    def _required_process(self) -> subprocess.Popen[str]:
        if self._process is None:
            raise BrowserDiagnosticError("browser MCP session is not running")
        return self._process


def _artifact_name(index: int) -> str:
    return ("navigate", "snapshot", "console", "network", "screenshot")[index]


def _image_content(result: Mapping[str, object]) -> Optional[bytes]:
    content = result.get("content", [])
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        data = item.get("data")
        if isinstance(data, str):
            try:
                return base64.b64decode(data, validate=True)
            except ValueError:
                return None
    return None


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
