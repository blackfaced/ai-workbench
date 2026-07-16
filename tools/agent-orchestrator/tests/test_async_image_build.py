from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    AgentResult,
    GoalRunner,
    ImageBuildError,
    RunReport,
)


class ImageFeatureAgent:
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


def test_candidate_waits_for_async_image_and_records_immutable_digest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)

        report = GoalRunner(
            state_dir=root / "state",
            agent=ImageFeatureAgent(),
            image_poll_interval_seconds=0.01,
        ).run(contract)

        assert report.status == "merge_ready"
        assert report.image_profile == "pr-image"
        assert report.image_operation_id == "build-123"
        assert report.image_status == "succeeded"
        assert report.image_digest == "sha256:" + "a" * 64
        assert report.image_artifacts
        events = next(
            Path(path)
            for path in report.image_artifacts
            if Path(path).name == "events.log"
        )
        assert events.read_text(encoding="utf-8").splitlines() == [
            "start",
            "status",
            "status",
            "result",
        ]
        assert RunReport.from_dict(report.to_dict()) == report


def test_status_interruption_resumes_the_same_external_image_build() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root, interrupt_status=True)
        contract = _write_contract(root, repository)
        interrupted_runner = GoalRunner(
            state_dir=root / "state",
            agent=ImageFeatureAgent(),
            image_poll_interval_seconds=0.01,
        )
        prepared = interrupted_runner.prepare(contract)

        try:
            interrupted_runner.run(contract)
        except ImageBuildError as error:
            assert "code 17" in str(error)
        else:
            raise AssertionError("the first status request must be interrupted")

        interrupted = interrupted_runner.report(prepared.run_id)
        assert interrupted.status == "waiting_image"
        assert interrupted.image_operation_id == "build-123"
        assert interrupted.image_digest == ""

        resumed = GoalRunner(
            state_dir=root / "state",
            agent=ImageFeatureAgent(),
            image_poll_interval_seconds=0.01,
        ).run(contract)

        events = next(
            Path(path)
            for path in resumed.image_artifacts
            if Path(path).name == "events.log"
        ).read_text(encoding="utf-8").splitlines()
        assert resumed.status == "merge_ready"
        assert events.count("start") == 1
        assert events == ["start", "status", "status", "status", "result"]


def test_mutable_image_reference_cannot_make_candidate_merge_ready() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root, invalid_digest=True)
        contract = _write_contract(root, repository)
        runner = GoalRunner(
            state_dir=root / "state",
            agent=ImageFeatureAgent(),
            image_poll_interval_seconds=0.01,
        )
        prepared = runner.prepare(contract)

        try:
            runner.run(contract)
        except ImageBuildError as error:
            assert "immutable sha256" in str(error)
        else:
            raise AssertionError("a mutable image reference must be rejected")

        report = runner.report(prepared.run_id)
        assert report.status == "waiting_image"
        assert report.image_status == "succeeded"
        assert report.image_digest == ""


def test_todo_dag_builds_image_from_the_integrated_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(root, repository)
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        todo = data.pop("todo")
        test = data.pop("test")
        data["todos"] = [
            {
                **todo,
                "depends_on": [],
                "test_ids": ["AC-1"],
                "test": test,
            }
        ]
        contract.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        report = GoalRunner(
            state_dir=root / "state",
            agent=ImageFeatureAgent(),
            image_poll_interval_seconds=0.01,
        ).run(contract)

        assert report.status == "merge_ready"
        assert [todo.status for todo in report.todos] == ["integrated"]
        assert report.image_digest == "sha256:" + "a" * 64


def _create_repository(
    root: Path,
    interrupt_status: bool = False,
    invalid_digest: bool = False,
) -> Path:
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
    (repository / "image_builder.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n\n"
        "state = Path(os.environ['AIWB_IMAGE_STATE_DIR'])\n"
        "state.mkdir(parents=True, exist_ok=True)\n"
        "mode = sys.argv[1]\n"
        f"interrupt_status = {interrupt_status!r}\n"
        f"invalid_digest = {invalid_digest!r}\n"
        "with (state / 'events.log').open('a') as events:\n"
        "    events.write(mode + '\\n')\n"
        "if mode == 'start':\n"
        "    from version import version\n"
        "    if version() != 'v2':\n"
        "        raise SystemExit('Candidate was not integrated before image start')\n"
        "    print(json.dumps({'operation_id': 'build-123'}))\n"
        "elif mode == 'status':\n"
        "    interrupted = state / 'interrupted'\n"
        "    if interrupt_status and not interrupted.exists():\n"
        "        interrupted.write_text('yes')\n"
        "        print('simulated status transport interruption', file=sys.stderr)\n"
        "        raise SystemExit(17)\n"
        "    count_file = state / 'status-count'\n"
        "    count = int(count_file.read_text()) if count_file.exists() else 0\n"
        "    count_file.write_text(str(count + 1))\n"
        "    print(json.dumps({'status': 'running' if count == 0 else 'succeeded'}))\n"
        "elif mode == 'result':\n"
        "    print(json.dumps({\n"
        "        'digest': 'latest' if invalid_digest else 'sha256:' + 'a' * 64,\n"
        "        'artifacts': [str(state / 'events.log')],\n"
        "    }))\n",
        encoding="utf-8",
    )
    _write_policy(repository)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_policy(repository: Path) -> None:
    test_command = [sys.executable, "-m", "pytest", "-q"]
    start = [sys.executable, "image_builder.py", "start"]
    status = [sys.executable, "image_builder.py", "status"]
    result = [sys.executable, "image_builder.py", "result"]
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
                        "unit": {"argv": test_command, "approved": True},
                        "image_start": {"argv": start, "approved": True},
                        "image_status": {"argv": status, "approved": True},
                        "image_result": {"argv": result, "approved": True},
                    },
                    "skills": {},
                },
                "harness": {"profiles": {}},
                "images": {
                    "profiles": {
                        "pr-image": {
                            "environment": "local",
                            "start": {"command": start},
                            "status": {"command": status},
                            "result": {"command": result},
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
                    "id": "image-goal",
                    "title": "Build the Candidate image",
                    "requirement": "Produce a verified immutable Candidate image.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Version reports v2."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "candidate": {"image_profile": "pr-image"},
                "todo": {"id": "T-1", "title": "Update version"},
                "test": {
                    "command": [sys.executable, "-m", "pytest", "-q"],
                    "allowed_paths": ["tests/test_version.py"],
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
