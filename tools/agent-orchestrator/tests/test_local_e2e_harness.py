from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    AgentResult,
    GateError,
    GoalRunner,
    HarnessError,
    ProjectConfigError,
    ProjectDoctor,
    ProjectPolicy,
)


class BrowserFeatureAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_browser_e2e.py").write_text(
                "import os\n"
                "from urllib.request import urlopen\n\n"
                "def test_homepage_message():\n"
                "    body = urlopen(os.environ['AIWB_BASE_URL'], timeout=2).read()\n"
                "    assert body.decode() == 'Hello from the browser gate'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "app.py").write_text(
                "def message():\n"
                "    return 'Hello from the browser gate'\n",
                encoding="utf-8",
            )
        return AgentResult(
            session_id=f"{request.role}-session",
            final_output="completed",
        )


class BrokenBrowserFeatureAgent(BrowserFeatureAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.role == "implementer":
            (Path(request.worktree) / "app.py").write_text(
                "def message():\n"
                "    return 'Still broken'\n",
                encoding="utf-8",
            )
        return result


def test_local_e2e_harness_runs_gate_collects_logs_and_cleans_up() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)

        report = GoalRunner(
            state_dir=root / "state",
            agent=BrowserFeatureAgent(),
        ).run(contract)

        assert report.status == "merge_ready"
        assert [item.stage for item in report.evidence] == [
            "red",
            "green",
            "verify",
            "candidate_acceptance:T-1",
        ]
        assert all(item.harness_profile == "local-e2e" for item in report.evidence)
        assert all(item.environment == "local" for item in report.evidence)
        assert all(item.base_url.startswith("http://127.0.0.1:") for item in report.evidence)
        assert all(item.artifacts for item in report.evidence)
        assert all(item.artifact_refs for item in report.evidence)
        assert all(Path(path).is_file() for item in report.evidence for path in item.artifacts)
        first_reference = report.evidence[0].artifact_refs[0]
        assert GoalRunner(
            state_dir=root / "state",
            agent=BrowserFeatureAgent(),
        ).evidence(report.run_id, first_reference.artifact_id).reference == (
            first_reference
        )

        with pytest.raises(URLError):
            urlopen(report.evidence[-1].base_url, timeout=0.2)


def test_readiness_timeout_kills_the_local_process_group() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root, unready=True)
        contract = _write_contract(root, repository)
        runner = GoalRunner(state_dir=root / "state", agent=BrowserFeatureAgent())
        prepared = runner.prepare(contract)

        with pytest.raises(HarnessError, match="readiness timed out"):
            runner.run(contract)

        pid_file = (
            root
            / "state"
            / "evidence"
            / prepared.run_id
            / "T-1"
            / "red"
            / "service.pid"
        )
        pid = int(pid_file.read_text(encoding="utf-8"))
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_browser_pass_evidence_requires_playwright_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        data["harness"]["profiles"]["local-e2e"]["browser_gate"] = "chrome-devtools"
        workflow.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        with pytest.raises(ProjectConfigError, match="Playwright Test"):
            ProjectPolicy.load(workflow)
        report = ProjectDoctor().inspect(workflow, codex_bin=sys.executable)
        assert report.status == "failed"
        assert "Playwright Test" in next(
            check.detail for check in report.checks if check.name == "non_production"
        )


def test_goal_runner_diagnoses_unexpected_browser_failure_but_not_red_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        fake_mcp = repository / "fake_mcp.py"
        fake_mcp.write_text(
            "import base64,json,sys\n"
            "tools = ['browser_navigate','browser_snapshot','browser_console_messages','browser_network_requests','browser_take_screenshot']\n"
            "for line in sys.stdin:\n"
            " request = json.loads(line)\n"
            " if 'id' not in request:\n"
            "  continue\n"
            " if request['method'] == 'initialize':\n"
            "  result = {'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fake','version':'1'}}\n"
            " elif request['method'] == 'tools/list':\n"
            "  result = {'tools':[{'name':name,'inputSchema':{'type':'object'}} for name in tools]}\n"
            " else:\n"
            "  name = request['params']['name']\n"
            "  result = {'content':[{'type':'text','text':name}]}\n"
            "  if name == 'browser_take_screenshot':\n"
            "   result = {'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(b'png').decode()}]}\n"
            " print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)\n",
            encoding="utf-8",
        )
        diagnostic_command = [sys.executable, "fake_mcp.py"]
        playwright_command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-W",
            "ignore:playwright",
        ]
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        data["capabilities"]["commands"]["browser_e2e"]["argv"] = playwright_command
        data["capabilities"]["commands"]["browser_diagnostic"] = {
            "argv": diagnostic_command,
            "approved": True,
        }
        profile = data["harness"]["profiles"]["local-e2e"]
        profile["browser_gate"] = "playwright"
        profile["browser_diagnostic"] = {
            "adapter": "playwright-mcp",
            "command": diagnostic_command,
            "timeout_seconds": 10,
        }
        workflow.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Add approved browser diagnostics")
        contract = _write_contract(root, repository)
        contract_data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        contract_data["test"]["command"] = playwright_command
        contract.write_text(
            yaml.safe_dump(contract_data, sort_keys=False),
            encoding="utf-8",
        )
        runner = GoalRunner(state_dir=root / "state", agent=BrokenBrowserFeatureAgent())
        prepared = runner.prepare(contract)

        with pytest.raises(GateError, match="GREEN gate failed") as failure:
            runner.run(contract)

        evidence_root = root / "state" / "evidence" / prepared.run_id / "T-1"
        assert not (evidence_root / "red" / "browser-diagnostic").exists()
        diagnostic_dir = evidence_root / "green" / "browser-diagnostic"
        assert (diagnostic_dir / "snapshot.json").is_file()
        assert (diagnostic_dir / "console.json").is_file()
        assert (diagnostic_dir / "network.json").is_file()
        assert (diagnostic_dir / "browser-screenshot.png").is_file()
        assert "Captured 5 browser observations" in str(failure.value)
        assert str(diagnostic_dir / "snapshot.json") in str(failure.value)
        failed = runner.report(prepared.run_id)
        green = next(item for item in failed.evidence if item.stage == "green")
        assert green.artifact_refs
        assert any(
            "browser-screenshot.png" in reference.label
            for reference in green.artifact_refs
        )


def _create_repository(root: Path, unready: bool = False) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    (repository / "app.py").write_text(
        "def message():\n"
        "    return 'Old message'\n",
        encoding="utf-8",
    )
    (repository / "server.py").write_text(
        "import os\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/health':\n"
        "            body = b'ok'\n"
        "        else:\n"
        "            from app import message\n"
        "            body = message().encode()\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "    def log_message(self, *args):\n"
        "        pass\n\n"
        "HTTPServer(('127.0.0.1', int(os.environ['AIWB_PORT'])), Handler).serve_forever()\n",
        encoding="utf-8",
    )
    _write_policy(repository, unready=unready)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_policy(repository: Path, unready: bool = False) -> None:
    test_command = [sys.executable, "-m", "pytest", "-q"]
    serve_command = (
        [
            sys.executable,
            "-c",
            "import os,time; from pathlib import Path; "
            "Path(os.environ['AIWB_ARTIFACT_DIR'], 'service.pid').write_text(str(os.getpid())); "
            "time.sleep(60)",
        ]
        if unready
        else [sys.executable, "server.py"]
    )
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {
                        "browser_e2e": {"argv": test_command, "approved": True},
                        "serve_local": {"argv": serve_command, "approved": True},
                    },
                    "skills": {},
                },
                "harness": {
                    "profiles": {
                        "local-e2e": {
                            "kind": "local_process",
                            "environment": "local",
                            "start": {"command": serve_command},
                            "ready": {
                                "url": "http://127.0.0.1:{port}/health",
                                "timeout_seconds": 1 if unready else 5,
                            },
                        }
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_contract(root: Path, repository: Path) -> Path:
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "browser-message",
                    "title": "Update the browser message",
                    "requirement": "The local page exposes the approved message.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "The page returns the message."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Update the page message"},
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q"],
                    "allowed_paths": ["tests/test_browser_e2e.py"],
                    "harness": "local-e2e",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
