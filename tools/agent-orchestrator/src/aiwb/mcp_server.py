from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import IO, Dict, Mapping, Optional, Sequence

from .daemon import DaemonClient, DaemonError
from .runner import preview_execution


_PROTOCOL_VERSION = "2025-06-18"


class McpServer:
    """Expose the durable daemon control interface over MCP stdio."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = Path(socket_path).expanduser().resolve()
        self._client = DaemonClient(self._socket_path)

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        for line in stdin:
            if not line.strip():
                continue
            response = self._handle_line(line)
            if response is None:
                continue
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()

    def _handle_line(self, line: str) -> Optional[Mapping[str, object]]:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as error:
            return _error(None, -32700, f"parse error: {error.msg}")
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return _error(_request_id(request), -32600, "invalid JSON-RPC request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return _error(request_id, -32600, "request method must be a string")
        if request_id is None:
            return None
        try:
            result = self._dispatch(method, request.get("params", {}))
        except LookupError as error:
            return _error(request_id, -32601, str(error))
        except ValueError as error:
            return _error(request_id, -32602, str(error))
        except Exception as error:
            return _error(request_id, -32603, str(error))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: object) -> Mapping[str, object]:
        if not isinstance(params, dict):
            raise ValueError("params must be a mapping")
        if method == "initialize":
            return {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-workbench", "version": "0.1.0"},
                "instructions": (
                    "Submit only human-approved Contracts. Use status and report to "
                    "observe Runs owned by the local ai-workbench daemon."
                ),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": _tools()}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("tools/call requires a tool name and argument mapping")
            return self._call_tool(name, arguments)
        raise LookupError(f"method not found: {method}")

    def _call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        try:
            if name == "aiwb_daemon_status":
                value = {
                    "socket": str(self._socket_path),
                    "status": "ok" if self._client.ping() else "unavailable",
                }
            elif name == "aiwb_goal_preflight":
                contract_path = _string_argument(arguments, "contract_path")
                value = preview_execution(Path(contract_path)).to_dict()
            elif name == "aiwb_goal_submit":
                contract_path = _string_argument(arguments, "contract_path")
                value = self._client.submit(Path(contract_path)).__dict__
            elif name == "aiwb_goal_status":
                run_id = _string_argument(arguments, "run_id")
                value = self._client.status(run_id).__dict__
            elif name == "aiwb_goal_report":
                run_id = _string_argument(arguments, "run_id")
                value = self._client.report(run_id).to_dict()
            elif name == "aiwb_goal_resume":
                run_id = _string_argument(arguments, "run_id")
                value = self._client.resume(run_id).__dict__
            else:
                return _tool_result(
                    {"error": "unknown_tool", "message": f"unknown tool: {name}"},
                    is_error=True,
                )
        except (DaemonError, OSError, ValueError) as error:
            return _tool_result(
                {
                    "error": getattr(error, "code", "operation_error"),
                    "message": str(error),
                },
                is_error=True,
            )
        return _tool_result(value, is_error=False)


def _tools():
    string_argument = {"type": "string", "minLength": 1}
    return [
        {
            "name": "aiwb_daemon_status",
            "description": "Check whether the local AI Workbench daemon is reachable.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "aiwb_goal_preflight",
            "description": (
                "Preview the deterministic and conditional execution envelope "
                "for a draft or approved Contract without creating a Run."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"contract_path": string_argument},
                "required": ["contract_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "aiwb_goal_report",
            "description": "Read the durable Evidence report for an existing Run.",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": string_argument},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "aiwb_goal_resume",
            "description": (
                "Resume a Run paused at a durable resource, deadline, or "
                "provider-quota checkpoint without changing provider or model."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": string_argument},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "aiwb_goal_status",
            "description": "Read the lightweight status of an existing Run.",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": string_argument},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "aiwb_goal_submit",
            "description": (
                "Submit an already-approved Contract to the durable local daemon. "
                "This returns immediately and does not wait for the Run to finish."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"contract_path": string_argument},
                "required": ["contract_path"],
                "additionalProperties": False,
            },
        },
    ]


def _string_argument(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _tool_result(value: object, is_error: bool) -> Mapping[str, object]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, indent=2, sort_keys=True),
            }
        ],
        "isError": is_error,
    }


def _error(request_id: object, code: int, message: str) -> Mapping[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _request_id(request: object) -> object:
    return request.get("id") if isinstance(request, dict) else None


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="aiwb-mcp")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("~/.ai-workbench").expanduser(),
    )
    parser.add_argument("--socket", type=Path)
    options = parser.parse_args(arguments)
    socket_path = (
        options.socket.expanduser().resolve()
        if options.socket
        else options.state_dir.expanduser().resolve() / "run" / "daemon.sock"
    )
    McpServer(socket_path).serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
