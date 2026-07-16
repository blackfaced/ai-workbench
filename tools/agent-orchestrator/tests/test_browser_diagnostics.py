from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    BrowserDiagnosticProfile,
    BrowserDiagnosticRequest,
    BrowserDiagnosticResult,
    HarnessProfile,
    HarnessRequest,
    LocalProcessHarness,
    McpBrowserDiagnosticAdapter,
    ProjectConfigError,
    ProjectPolicy,
)


class RecordingBrowserDiagnosticAdapter:
    def __init__(self) -> None:
        self.requests: list[BrowserDiagnosticRequest] = []

    def diagnose(self, request: BrowserDiagnosticRequest) -> BrowserDiagnosticResult:
        self.requests.append(request)
        body = urlopen(request.base_url, timeout=2).read().decode()
        artifact = request.artifact_dir / "browser-diagnostic.md"
        artifact.write_text(f"snapshot: {body}\n", encoding="utf-8")
        return BrowserDiagnosticResult(
            adapter=request.profile.adapter,
            summary=f"page remained reachable: {body}",
            artifacts=(str(artifact),),
        )


class FailingBrowserDiagnosticAdapter:
    def diagnose(self, request: BrowserDiagnosticRequest) -> BrowserDiagnosticResult:
        raise RuntimeError("browser process unavailable")


def test_failed_browser_gate_is_diagnosed_before_local_target_cleanup() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        server = root / "server.py"
        server.write_text(
            "import os\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200)\n"
            "        self.end_headers()\n"
            "        self.wfile.write(b'diagnostic target')\n"
            "    def log_message(self, *args):\n"
            "        pass\n\n"
            "HTTPServer(('127.0.0.1', int(os.environ['AIWB_PORT'])), Handler).serve_forever()\n",
            encoding="utf-8",
        )
        diagnostic = RecordingBrowserDiagnosticAdapter()
        profile = HarnessProfile(
            name="local-browser",
            kind="local_process",
            environment="local",
            start_command=(sys.executable, "server.py"),
            ready_url="http://127.0.0.1:{port}/",
            ready_timeout_seconds=5,
            browser_gate="playwright",
            browser_diagnostic=BrowserDiagnosticProfile(
                adapter="playwright-mcp",
                command=(sys.executable, "fake-mcp.py"),
                timeout_seconds=30,
            ),
        )

        execution = LocalProcessHarness(browser_diagnostics=diagnostic).execute(
            HarnessRequest(
                profile=profile,
                command=(sys.executable, "-c", "raise SystemExit(7)"),
                cwd=root,
                timeout_seconds=30,
                run_id="run-browser-diagnostic",
                artifact_dir=root / "artifacts",
                execution_id="T-1:verify",
                stage="verify",
            )
        )

        assert execution.returncode == 7
        assert len(diagnostic.requests) == 1
        assert diagnostic.requests[0].gate_stderr == ""
        assert execution.browser_diagnostic is not None
        assert execution.browser_diagnostic.adapter == "playwright-mcp"
        assert "diagnostic target" in execution.browser_diagnostic.summary
        assert all(Path(path).is_file() for path in execution.browser_diagnostic.artifacts)
        with pytest.raises(URLError):
            urlopen(execution.base_url, timeout=0.2)


def test_diagnostic_failure_does_not_mask_the_authoritative_gate_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        server = root / "server.py"
        server.write_text(
            "import os\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  self.send_response(200); self.end_headers()\n"
            " def log_message(self, *args): pass\n"
            "HTTPServer(('127.0.0.1', int(os.environ['AIWB_PORT'])), Handler).serve_forever()\n",
            encoding="utf-8",
        )
        profile = HarnessProfile(
            name="local-browser",
            kind="local_process",
            environment="local",
            start_command=(sys.executable, "server.py"),
            ready_url="http://127.0.0.1:{port}/",
            ready_timeout_seconds=5,
            browser_gate="playwright",
            browser_diagnostic=BrowserDiagnosticProfile(
                adapter="chrome-devtools-mcp",
                command=(sys.executable, "missing.py"),
                timeout_seconds=10,
            ),
        )

        execution = LocalProcessHarness(
            browser_diagnostics=FailingBrowserDiagnosticAdapter()
        ).execute(
            HarnessRequest(
                profile=profile,
                command=(sys.executable, "-c", "raise SystemExit(23)"),
                cwd=root,
                timeout_seconds=30,
                run_id="run-diagnostic-failure",
                artifact_dir=root / "artifacts",
                execution_id="T-1:verify",
                stage="verify",
            )
        )

        assert execution.returncode == 23
        assert execution.browser_diagnostic is not None
        assert execution.browser_diagnostic.error == "browser process unavailable"


def test_project_policy_loads_an_approved_browser_diagnostic_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory).resolve()
        test_command = ("npx", "playwright", "test")
        start_command = ("npm", "run", "dev")
        diagnostic_command = ("npx", "-y", "@playwright/mcp@latest", "--headless")
        workflow = repository / "workflow.yaml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "browser_test": {"argv": list(test_command), "approved": True},
                            "serve": {"argv": list(start_command), "approved": True},
                            "browser_diagnostic": {
                                "argv": list(diagnostic_command),
                                "approved": True,
                            },
                        }
                    },
                    "harness": {
                        "profiles": {
                            "local-browser": {
                                "kind": "local_process",
                                "environment": "local",
                                "browser_gate": "playwright",
                                "browser_diagnostic": {
                                    "adapter": "playwright-mcp",
                                    "command": list(diagnostic_command),
                                    "timeout_seconds": 90,
                                },
                                "start": {"command": list(start_command)},
                                "ready": {
                                    "url": "http://127.0.0.1:{port}/health",
                                    "timeout_seconds": 30,
                                },
                            }
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        profile = ProjectPolicy.load(workflow).authorize(
            repository,
            test_command,
            "local-browser",
        )

        assert profile is not None
        assert profile.browser_diagnostic == BrowserDiagnosticProfile(
            adapter="playwright-mcp",
            command=diagnostic_command,
            timeout_seconds=90,
        )


def test_project_policy_rejects_an_unapproved_browser_diagnostic_command() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory).resolve()
        workflow = repository / "workflow.yaml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "browser_test": {
                                "argv": ["npx", "playwright", "test"],
                                "approved": True,
                            },
                            "serve": {
                                "argv": ["npm", "run", "dev"],
                                "approved": True,
                            },
                        }
                    },
                    "harness": {
                        "profiles": {
                            "local-browser": {
                                "kind": "local_process",
                                "environment": "local",
                                "browser_gate": "playwright",
                                "browser_diagnostic": {
                                    "adapter": "chrome-devtools-mcp",
                                    "command": ["npx", "-y", "chrome-devtools-mcp@latest"],
                                },
                                "start": {"command": ["npm", "run", "dev"]},
                                "ready": {"url": "http://127.0.0.1:{port}/health"},
                            }
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigError, match="diagnostic command is not approved"):
            ProjectPolicy.load(workflow)


def test_playwright_mcp_adapter_collects_browser_diagnostic_artifacts() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fake_server = root / "fake_mcp.py"
        fake_server.write_text(
            "import base64,json,sys\n"
            "tools = [\n"
            " 'browser_navigate', 'browser_snapshot', 'browser_console_messages',\n"
            " 'browser_network_requests', 'browser_take_screenshot'\n"
            "]\n"
            "for line in sys.stdin:\n"
            " request = json.loads(line)\n"
            " if 'id' not in request:\n"
            "  continue\n"
            " method = request['method']\n"
            " if method == 'initialize':\n"
            "  result = {'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fake','version':'1'}}\n"
            " elif method == 'tools/list':\n"
            "  result = {'tools':[{'name':name,'inputSchema':{'type':'object'}} for name in tools]}\n"
            " elif method == 'tools/call':\n"
            "  name = request['params']['name']\n"
            "  args = request['params']['arguments']\n"
            "  if name == 'browser_take_screenshot':\n"
            "   result = {'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(b'png').decode()}]}\n"
            "  else:\n"
            "   result = {'content':[{'type':'text','text':json.dumps({'name':name,'arguments':args})}]}\n"
            " else:\n"
            "  result = {}\n"
            " print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)\n",
            encoding="utf-8",
        )
        artifacts = root / "artifacts"
        request = BrowserDiagnosticRequest(
            profile=BrowserDiagnosticProfile(
                adapter="playwright-mcp",
                command=(sys.executable, str(fake_server)),
                timeout_seconds=10,
            ),
            base_url="http://127.0.0.1:43210",
            cwd=root,
            artifact_dir=artifacts,
            run_id="run-mcp",
            execution_id="T-1:verify",
            gate_stdout="one failed",
            gate_stderr="assertion error",
        )

        result = McpBrowserDiagnosticAdapter().diagnose(request)

        assert result.adapter == "playwright-mcp"
        assert result.error == ""
        assert "5 browser observations" in result.summary
        assert (artifacts / "browser-screenshot.png").read_bytes() == b"png"
        navigate = json.loads(
            (artifacts / "navigate.json").read_text(encoding="utf-8")
        )
        assert json.loads(navigate["content"][0]["text"])["arguments"] == {
            "url": request.base_url
        }
        failure = json.loads(
            (artifacts / "gate-failure.json").read_text(encoding="utf-8")
        )
        assert failure["stderr"] == "assertion error"
        assert all(Path(path).is_file() for path in result.artifacts)


def test_chrome_devtools_mcp_adapter_uses_its_browser_tool_vocabulary() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fake_server = root / "fake_chrome_mcp.py"
        fake_server.write_text(
            "import base64,json,sys\n"
            "tools = ['new_page','take_snapshot','list_console_messages','list_network_requests','take_screenshot']\n"
            "for line in sys.stdin:\n"
            " request = json.loads(line)\n"
            " if 'id' not in request:\n"
            "  continue\n"
            " if request['method'] == 'initialize':\n"
            "  result = {'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fake','version':'1'}}\n"
            " elif request['method'] == 'tools/list':\n"
            "  result = {'tools':[{'name':name,'inputSchema':{'type':'object'}} for name in tools]}\n"
            " else:\n"
            "  name = request['params']['name']; args = request['params']['arguments']\n"
            "  result = {'content':[{'type':'text','text':json.dumps({'name':name,'arguments':args})}]}\n"
            "  if name == 'take_screenshot':\n"
            "   result = {'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(b'chrome-png').decode()}]}\n"
            " print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)\n",
            encoding="utf-8",
        )
        artifacts = root / "artifacts"
        request = BrowserDiagnosticRequest(
            profile=BrowserDiagnosticProfile(
                adapter="chrome-devtools-mcp",
                command=(sys.executable, str(fake_server)),
                timeout_seconds=10,
            ),
            base_url="https://preview.example.test",
            cwd=root,
            artifact_dir=artifacts,
            run_id="run-chrome-mcp",
            execution_id="T-2:integrate",
            gate_stdout="",
            gate_stderr="browser assertion failed",
        )

        result = McpBrowserDiagnosticAdapter().diagnose(request)

        navigate = json.loads(
            (artifacts / "navigate.json").read_text(encoding="utf-8")
        )
        navigate_call = json.loads(navigate["content"][0]["text"])
        assert navigate_call == {
            "name": "new_page",
            "arguments": {"url": request.base_url},
        }
        console = json.loads(
            (artifacts / "console.json").read_text(encoding="utf-8")
        )
        assert json.loads(console["content"][0]["text"])["arguments"] == {
            "includePreservedMessages": True
        }
        assert (artifacts / "browser-screenshot.png").read_bytes() == b"chrome-png"
        assert result.adapter == "chrome-devtools-mcp"
