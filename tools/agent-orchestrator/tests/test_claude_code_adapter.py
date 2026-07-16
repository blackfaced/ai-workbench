from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb.agent import (  # noqa: E402
    AgentRequest,
    AgentResult,
    AgentRouter,
    ClaudeCodeCliAdapter,
)


def test_claude_code_adapter_runs_a_fresh_json_session_in_the_worktree() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        worktree = root / "worktree"
        worktree.mkdir()
        capture = root / "capture.json"
        executable = root / "fake-claude"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            f"open({str(capture)!r}, 'w').write(json.dumps({{'args': sys.argv[1:], 'cwd': os.getcwd()}}))\n"
            "print(json.dumps({'type': 'result', 'subtype': 'success', "
            "'is_error': False, 'result': 'implemented', 'session_id': 'session-123'}))\n"
        )
        executable.chmod(0o700)

        result = ClaudeCodeCliAdapter(str(executable)).run(
            AgentRequest(
                role="implementer",
                prompt="Implement the approved Todo",
                worktree=str(worktree),
                model="sonnet",
            )
        )

        assert result.session_id == "session-123"
        assert result.final_output == "implemented"
        invocation = json.loads(capture.read_text())
        assert invocation["cwd"] == str(worktree.resolve())
        assert invocation["args"] == [
            "-p",
            "--output-format",
            "json",
            "--setting-sources",
            "project,local",
            "--strict-mcp-config",
            "--permission-mode",
            "auto",
            "--model",
            "sonnet",
            "Implement the approved Todo",
        ]
        assert "--dangerously-skip-permissions" not in invocation["args"]


def test_claude_code_adapter_forces_read_only_requests_into_plan_mode() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        capture = root / "arguments.json"
        executable = root / "fake-claude"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            f"open({str(capture)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
            "print(json.dumps({'is_error': False, 'result': 'checked', "
            "'session_id': 'session-read-only'}))\n"
        )
        executable.chmod(0o700)

        ClaudeCodeCliAdapter(
            str(executable), permission_mode="dontAsk"
        ).run(
            AgentRequest(
                role="verifier",
                prompt="Inspect only",
                worktree=str(root),
                sandbox="read-only",
            )
        )

        arguments = json.loads(capture.read_text())
        mode_index = arguments.index("--permission-mode") + 1
        assert arguments[mode_index] == "plan"


def test_claude_code_adapter_rejects_bypass_permissions() -> None:
    with pytest.raises(ValueError, match="permission mode"):
        ClaudeCodeCliAdapter(permission_mode="bypassPermissions")


def test_agent_router_uses_only_the_provider_fixed_on_the_request() -> None:
    class SelectedAdapter:
        def run(self, request: AgentRequest) -> AgentResult:
            return AgentResult(session_id="claude-session", final_output=request.role)

    class NeverCalledAdapter:
        def run(self, request: AgentRequest) -> AgentResult:
            raise AssertionError(f"unexpected provider for {request.role}")

    result = AgentRouter(
        {
            "codex": NeverCalledAdapter(),
            "claude-code": SelectedAdapter(),
        }
    ).run(
        AgentRequest(
            role="implementer",
            prompt="Implement",
            worktree="/tmp/worktree",
            provider="claude-code",
        )
    )

    assert result == AgentResult(
        session_id="claude-session",
        final_output="implementer",
    )
