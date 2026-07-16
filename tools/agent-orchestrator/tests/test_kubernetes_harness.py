from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    AgentResult,
    AgentDaemon,
    BrowserDiagnosticProfile,
    BrowserDiagnosticRequest,
    BrowserDiagnosticResult,
    DaemonClient,
    GoalRunner,
    HarnessError,
    KubernetesHarness,
    KubernetesJanitor,
    ProjectPolicy,
)
from aiwb.harness import HarnessRequest  # noqa: E402


class RecordingKubernetesBrowserDiagnosticAdapter:
    def __init__(self, root: Path) -> None:
        self._root = root

    def diagnose(self, request: BrowserDiagnosticRequest) -> BrowserDiagnosticResult:
        assert (self._root / "cluster-resource").exists()
        with (self._root / "events.log").open("a", encoding="utf-8") as events:
            events.write("diagnose\n")
        artifact = request.artifact_dir / "cluster-browser-snapshot.json"
        artifact.write_text('{"page":"reachable"}\n', encoding="utf-8")
        return BrowserDiagnosticResult(
            adapter=request.profile.adapter,
            summary="diagnosed live non-production target",
            artifacts=(str(artifact),),
        )


def test_non_production_kubernetes_harness_is_isolated_and_always_cleaned() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root)
        policy = _write_policy(repository, commands)
        profile = policy.authorize(
            repository,
            commands["gate"],
            "dev-cluster",
        )
        assert profile is not None

        result = KubernetesHarness(root / "state").execute(
            HarnessRequest(
                profile=profile,
                command=commands["gate"],
                cwd=repository,
                timeout_seconds=30,
                run_id="run-123",
                execution_id="T-1:verified",
                artifact_dir=root / "evidence",
            )
        )

        events = (root / "events.log").read_text(encoding="utf-8").splitlines()
        assert result.returncode == 0
        assert result.stdout.strip() == "gate passed"
        assert result.base_url.startswith("https://aiwb-run-123-")
        assert result.environment.startswith("non-production/dev-context/aiwb-run-123-")
        assert events == ["provision", "collect", "cleanup"]
        assert not (root / "cluster-resource").exists()
        assert any(Path(path).name == "cluster-evidence.log" for path in result.artifacts)
        assert not list((root / "state" / "kubernetes-leases").glob("*.json"))


def test_failed_kubernetes_browser_gate_is_diagnosed_before_collect_and_cleanup() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root)
        (repository / "gate.py").write_text("raise SystemExit(19)\n", encoding="utf-8")
        policy = _write_policy(repository, commands)
        profile = policy.authorize(repository, commands["gate"], "dev-cluster")
        assert profile is not None
        profile = replace(
            profile,
            browser_gate="playwright",
            browser_diagnostic=BrowserDiagnosticProfile(
                adapter="chrome-devtools-mcp",
                command=(sys.executable, "fake-mcp.py"),
                timeout_seconds=30,
            ),
        )

        result = KubernetesHarness(
            root / "state",
            browser_diagnostics=RecordingKubernetesBrowserDiagnosticAdapter(root),
        ).execute(
            HarnessRequest(
                profile=profile,
                command=commands["gate"],
                cwd=repository,
                timeout_seconds=30,
                run_id="run-123",
                execution_id="T-1:verify",
                artifact_dir=root / "evidence",
                stage="verify",
            )
        )

        assert result.returncode == 19
        assert result.browser_diagnostic is not None
        assert result.browser_diagnostic.adapter == "chrome-devtools-mcp"
        assert (root / "events.log").read_text(encoding="utf-8").splitlines() == [
            "provision",
            "diagnose",
            "collect",
            "cleanup",
        ]
        assert not (root / "cluster-resource").exists()


def test_kubernetes_policy_loads_approved_browser_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root)
        commands["gate"] = (sys.executable, "playwright-gate.py")
        commands["browser_diagnostic"] = (
            sys.executable,
            "chrome-devtools-mcp.py",
        )
        _write_policy(repository, commands)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        profile_data = data["harness"]["profiles"]["dev-cluster"]
        profile_data["browser_gate"] = "playwright"
        profile_data["browser_diagnostic"] = {
            "adapter": "chrome-devtools-mcp",
            "command": list(commands["browser_diagnostic"]),
            "timeout_seconds": 120,
        }
        workflow.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        profile = ProjectPolicy.load(workflow).authorize(
            repository,
            commands["gate"],
            "dev-cluster",
        )

        assert profile is not None
        assert profile.browser_diagnostic == BrowserDiagnosticProfile(
            adapter="chrome-devtools-mcp",
            command=commands["browser_diagnostic"],
            timeout_seconds=120,
        )


class KubernetesFeatureAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_version.py").write_text(
                "from version import version\n\n"
                "def test_version():\n"
                "    assert version() == 'v2'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "version.py").write_text(
                "def version():\n"
                "    return 'v2'\n",
                encoding="utf-8",
            )
        return AgentResult(
            session_id=f"{request.role}-session",
            final_output="completed",
        )


class FailIfCalledAgent:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError(f"Agent must not run during Janitor sweep: {request.role}")


def test_goal_runner_uses_kubernetes_harness_for_every_candidate_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "AI Workbench Test")
        _git(repository, "config", "user.email", "aiwb@example.test")
        (repository / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n.pytest_cache/\n",
            encoding="utf-8",
        )
        (repository / "version.py").write_text(
            "def version():\n"
            "    return 'v1'\n",
            encoding="utf-8",
        )
        commands = _write_fixture_commands(repository, root)
        commands["gate"] = (sys.executable, "-m", "pytest", "-q")
        _write_policy(repository, commands)
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Initial fixture")
        contract = _write_contract(root, repository, commands["gate"])

        report = GoalRunner(
            state_dir=root / "state",
            agent=KubernetesFeatureAgent(),
        ).run(contract)

        assert report.status == "merge_ready"
        assert report.evidence
        assert all(item.harness_profile == "dev-cluster" for item in report.evidence)
        assert all("/dev-context/aiwb-" in item.environment for item in report.evidence)
        assert all(item.base_url.startswith("https://aiwb-") for item in report.evidence)
        assert len({item.environment for item in report.evidence}) == len(report.evidence)
        events = (root / "events.log").read_text(encoding="utf-8").splitlines()
        assert events == ["provision", "collect", "cleanup"] * 3
        assert not (root / "cluster-resource").exists()
        assert not list((root / "state" / "kubernetes-leases").glob("*.json"))


def test_janitor_retries_a_persisted_cleanup_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root, fail_cleanup_once=True)
        policy = _write_policy(repository, commands)
        profile = policy.authorize(repository, commands["gate"], "dev-cluster")
        assert profile is not None
        state_dir = root / "state"

        with pytest.raises(HarnessError, match="cleanup failed with code 17"):
            KubernetesHarness(state_dir).execute(
                HarnessRequest(
                    profile=profile,
                    command=commands["gate"],
                    cwd=repository,
                    timeout_seconds=30,
                    run_id="run-123",
                    execution_id="T-1:verified",
                    artifact_dir=root / "evidence",
                )
            )

        assert (root / "cluster-resource").exists()
        assert len(list((state_dir / "kubernetes-leases").glob("*.json"))) == 1

        report = KubernetesJanitor(state_dir).sweep()

        assert report.scanned == 1
        assert report.cleaned == 1
        assert report.failed == 0
        assert not (root / "cluster-resource").exists()
        assert not list((state_dir / "kubernetes-leases").glob("*.json"))
        assert (root / "events.log").read_text(encoding="utf-8").splitlines() == [
            "provision",
            "collect",
            "cleanup",
            "cleanup",
        ]


def test_janitor_reclaims_an_expired_lease_after_process_death() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root)
        slow_gate = repository / "slow_gate.py"
        slow_gate.write_text(
            "import time\n"
            "while True:\n"
            "    time.sleep(1)\n",
            encoding="utf-8",
        )
        commands["gate"] = (sys.executable, "slow_gate.py")
        policy = _write_policy(repository, commands)
        driver = root / "run_harness.py"
        driver.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "from aiwb import KubernetesHarness, ProjectPolicy\n"
            "from aiwb.harness import HarnessRequest\n\n"
            "root = Path(sys.argv[1])\n"
            "repository = root / 'project'\n"
            "policy = ProjectPolicy.load(repository / '.ai-workbench' / 'workflow.yaml')\n"
            "command = (sys.executable, 'slow_gate.py')\n"
            "profile = policy.authorize(repository, command, 'dev-cluster')\n"
            "KubernetesHarness(root / 'state').execute(HarnessRequest(\n"
            "    profile=profile, command=command, cwd=repository,\n"
            "    timeout_seconds=300, run_id='orphan-run',\n"
            "    execution_id='T-1:verified', artifact_dir=root / 'evidence',\n"
            "))\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        process = subprocess.Popen(
            [sys.executable, str(driver), str(root)],
            cwd=str(repository),
            env=environment,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for(lambda: (root / "cluster-resource").exists())
            _wait_for(
                lambda: bool(list((root / "state" / "kubernetes-leases").glob("*.json")))
            )
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

        assert (root / "cluster-resource").exists()
        report = KubernetesJanitor(
            root / "state",
            clock=lambda: time.time() + 4000,
        ).sweep()

        assert report.cleaned == 1
        assert report.failed == 0
        assert not (root / "cluster-resource").exists()
        assert not list((root / "state" / "kubernetes-leases").glob("*.json"))
        assert (root / "events.log").read_text(encoding="utf-8").splitlines() == [
            "provision",
            "cleanup",
        ]


def test_running_daemon_periodically_sweeps_cleanup_pending_leases() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        commands = _write_fixture_commands(repository, root, fail_cleanup_once=True)
        policy = _write_policy(repository, commands)
        profile = policy.authorize(repository, commands["gate"], "dev-cluster")
        assert profile is not None
        state_dir = root / "state"
        socket_path = state_dir / "run" / "daemon.sock"
        daemon = AgentDaemon(
            state_dir=state_dir,
            agent=FailIfCalledAgent(),
            socket_path=socket_path,
            janitor_interval_seconds=0.05,
        )
        thread = threading.Thread(target=daemon.serve_forever, daemon=True)
        thread.start()
        try:
            _wait_for(lambda: DaemonClient(socket_path).ping())
            with pytest.raises(HarnessError, match="cleanup failed with code 17"):
                KubernetesHarness(state_dir).execute(
                    HarnessRequest(
                        profile=profile,
                        command=commands["gate"],
                        cwd=repository,
                        timeout_seconds=30,
                        run_id="run-123",
                        execution_id="T-1:verified",
                        artifact_dir=root / "evidence",
                    )
                )
            _wait_for(lambda: not (root / "cluster-resource").exists())
            _wait_for(
                lambda: not list(
                    (state_dir / "kubernetes-leases").glob("*.json")
                )
            )
        finally:
            daemon.shutdown()
            thread.join(timeout=5)

        assert not thread.is_alive()
        assert (root / "events.log").read_text(encoding="utf-8").splitlines() == [
            "provision",
            "collect",
            "cleanup",
            "cleanup",
        ]


def _write_fixture_commands(
    repository: Path,
    root: Path,
    fail_cleanup_once: bool = False,
):
    harness_script = repository / "kube_harness.py"
    harness_script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n\n"
        f"root = Path({str(root)!r})\n"
        f"fail_cleanup_once = {fail_cleanup_once!r}\n"
        "mode = sys.argv[1]\n"
        "with (root / 'events.log').open('a') as events:\n"
        "    events.write(mode + '\\n')\n"
        "namespace = os.environ['AIWB_K8S_NAMESPACE']\n"
        "assert os.environ['AIWB_K8S_CONTEXT'] == 'dev-context'\n"
        "assert namespace.startswith('aiwb-')\n"
        "labels = json.loads(os.environ['AIWB_K8S_LABELS'])\n"
        "assert labels['ai-workbench.dev/managed-by'] == 'agent-orchestrator'\n"
        "assert labels['ai-workbench.dev/run-id'] == os.environ['AIWB_RUN_ID']\n"
        "if mode == 'provision':\n"
        "    (root / 'cluster-resource').write_text(namespace)\n"
        "    print(json.dumps({'base_url': f'https://{namespace}.example.test'}))\n"
        "elif mode == 'collect':\n"
        "    artifact = Path(os.environ['AIWB_ARTIFACT_DIR']) / 'cluster-evidence.log'\n"
        "    artifact.write_text('collected')\n"
        "    print(json.dumps({'artifacts': [str(artifact)]}))\n"
        "elif mode == 'cleanup':\n"
        "    failed_once = root / 'cleanup-failed-once'\n"
        "    if fail_cleanup_once and not failed_once.exists():\n"
        "        failed_once.write_text('yes')\n"
        "        print('simulated cleanup failure', file=sys.stderr)\n"
        "        raise SystemExit(17)\n"
        "    marker = root / 'cluster-resource'\n"
        "    if marker.exists():\n"
        "        marker.unlink()\n"
        "    print(json.dumps({'status': 'clean'}))\n",
        encoding="utf-8",
    )
    gate_script = repository / "gate.py"
    gate_script.write_text(
        "import os\n"
        "assert os.environ['AIWB_BASE_URL'].startswith('https://aiwb-run-123-')\n"
        "assert os.environ['AIWB_K8S_NAMESPACE'].startswith('aiwb-run-123-')\n"
        "assert int(os.environ['AIWB_K8S_TTL_SECONDS']) == 3600\n"
        "print('gate passed')\n",
        encoding="utf-8",
    )
    return {
        "provision": (sys.executable, "kube_harness.py", "provision"),
        "collect": (sys.executable, "kube_harness.py", "collect"),
        "cleanup": (sys.executable, "kube_harness.py", "cleanup"),
        "gate": (sys.executable, "gate.py"),
    }


def _write_policy(repository: Path, commands) -> ProjectPolicy:
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
                        name: {"argv": list(command), "approved": True}
                        for name, command in commands.items()
                    },
                    "skills": {},
                },
                "harness": {
                    "allowed_kubernetes_contexts": ["dev-context"],
                    "profiles": {
                        "dev-cluster": {
                            "kind": "kubernetes",
                            "environment": "non-production",
                            "context": "dev-context",
                            "namespace_prefix": "aiwb",
                            "ttl_seconds": 3600,
                            "provision": {"command": list(commands["provision"])},
                            "collect": {"command": list(commands["collect"])},
                            "cleanup": {"command": list(commands["cleanup"])},
                        }
                    },
                },
                "images": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return ProjectPolicy.load(workflow)


def _write_contract(root: Path, repository: Path, gate_command) -> Path:
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "kubernetes-goal",
                    "title": "Verify the Candidate in a development cluster",
                    "requirement": "The integrated behavior passes in isolation.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Version reports v2."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Update version"},
                "test": {
                    "command": list(gate_command),
                    "allowed_paths": ["tests/test_version.py"],
                    "timeout_seconds": 60,
                    "harness": "dev-cluster",
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


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")
