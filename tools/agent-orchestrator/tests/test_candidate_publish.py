from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentRequest, AgentResult, GateError, GoalRunner  # noqa: E402
from aiwb.publish import (  # noqa: E402
    CandidatePublishError,
    CandidatePublishRequest,
    CandidatePublisher,
)


class GreetingAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.roles.append(request.role)
        worktree = Path(request.worktree)
        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting():\n"
                "    assert greeting() == 'hello'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            (worktree / "greeting.py").write_text(
                "def greeting():\n"
                "    return 'hello'\n",
                encoding="utf-8",
            )
        elif request.role not in {"verifier", "candidate_verifier"}:
            raise AssertionError(f"unexpected role: {request.role}")
        return AgentResult(
            session_id=f"{request.role}-session",
            final_output=f"{request.role} completed",
        )


class MutatingFinalPublishAgent(GreetingAgent):
    def run(self, request: AgentRequest) -> AgentResult:
        if request.role == "candidate_verifier":
            (Path(request.worktree) / "greeting.py").write_text(
                "def greeting():\n"
                "    return 'mutated'\n",
                encoding="utf-8",
            )
            return AgentResult(
                session_id="mutating-final-verifier",
                final_output="completed",
            )
        return super().run(request)


def test_candidate_branch_is_not_published_before_final_acceptance() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _, remote, contract = _fixture(root)
        runner = GoalRunner(
            state_dir=root / "state",
            agent=MutatingFinalPublishAgent(),
        )
        prepared = runner.prepare(contract)

        try:
            runner.run(contract)
        except GateError as error:
            assert "mutated the immutable Candidate" in str(error)
        else:
            raise AssertionError("publication must wait for final acceptance")

        remote_ref = f"refs/heads/{prepared.branch}"
        result = subprocess.run(
            [
                "git",
                "--git-dir",
                str(remote),
                "show-ref",
                "--verify",
                "--quiet",
                remote_ref,
            ],
            check=False,
        )
        assert result.returncode != 0


def test_merge_ready_candidate_is_pushed_to_the_policy_approved_namespace() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _, remote, contract = _fixture(root)

        report = GoalRunner(state_dir=root / "state", agent=GreetingAgent()).run(contract)

        assert report.status == "merge_ready"
        assert report.published_remote == "origin"
        assert report.published_ref == f"refs/heads/{report.branch}"
        assert report.published_commit == _git(
            Path(report.worktree), "rev-parse", "HEAD"
        ).stdout.strip()
        assert report.published_commit == report.candidate_commit
        assert _git(
            root,
            "--git-dir",
            str(remote),
            "rev-parse",
            report.published_ref,
        ).stdout.strip() == report.published_commit


def test_resume_is_idempotent_after_push_succeeds_before_sqlite_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository, remote, contract = _fixture(root)
        agent = GreetingAgent()
        runner = GoalRunner(state_dir=root / "state", agent=agent)
        runner._candidate_publisher = CrashAfterPushPublisher()  # type: ignore[attr-defined]

        try:
            runner.run(contract)
        except SimulatedHostCrash:
            pass
        else:
            raise AssertionError("expected a simulated crash after Git push")

        prepared = runner.prepare(contract)
        remote_ref = f"refs/heads/{prepared.branch}"
        pushed_commit = _git(
            root, "--git-dir", str(remote), "rev-parse", remote_ref
        ).stdout.strip()
        assert prepared.status == "merge_ready"
        assert prepared.published_commit == ""

        resumed = GoalRunner(state_dir=root / "state", agent=agent).run(contract)

        assert resumed.status == "merge_ready"
        assert resumed.published_commit == pushed_commit
        assert resumed.published_ref == remote_ref
        assert agent.roles == [
            "test_designer",
            "implementer",
            "verifier",
            "candidate_verifier",
        ]


def test_diverged_remote_candidate_is_rejected_without_force_push() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository, remote, contract = _fixture(root)
        runner = GoalRunner(state_dir=root / "state", agent=GreetingAgent())
        prepared = runner.prepare(contract)
        remote_ref = f"refs/heads/{prepared.branch}"
        intruder = root / "intruder"
        intruder.mkdir()
        _git(intruder, "init", "-b", "main")
        _git(intruder, "config", "user.name", "Other Writer")
        _git(intruder, "config", "user.email", "other@example.test")
        (intruder / "other.txt").write_text("diverged\n", encoding="utf-8")
        _git(intruder, "add", ".")
        _git(intruder, "commit", "-m", "Diverged remote history")
        divergent_commit = _git(intruder, "rev-parse", "HEAD").stdout.strip()
        _git(intruder, "remote", "add", "origin", str(remote))
        _git(intruder, "push", "origin", f"HEAD:{remote_ref}")

        try:
            runner.run(contract)
        except CandidatePublishError as error:
            assert "[rejected]" in str(error)
        else:
            raise AssertionError("expected divergent remote publication to fail")

        assert _git(
            root, "--git-dir", str(remote), "rev-parse", remote_ref
        ).stdout.strip() == divergent_commit
        report = runner.prepare(contract)
        assert report.status == "merge_ready"
        assert report.published_commit == ""


class SimulatedHostCrash(RuntimeError):
    pass


class CrashAfterPushPublisher:
    def publish(self, request: CandidatePublishRequest):
        CandidatePublisher().publish(request)
        raise SimulatedHostCrash("push completed before SQLite checkpoint")


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    repository = root / "project"
    remote = root / "remote.git"
    repository.mkdir()
    test_command = [sys.executable, "-m", "pytest", "-q"]
    _git(root, "init", "--bare", str(remote))
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    _git(repository, "remote", "add", "origin", str(remote))
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    (repository / "README.md").write_text("# Fixture project\n", encoding="utf-8")
    _write_policy(repository, test_command)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "published-greeting",
                    "title": "Publish a greeting",
                    "requirement": "Expose a greeting function.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "Greeting returns hello."}
                    ],
                },
                "approval": {
                    "status": "approved",
                    "approved_by": "owner",
                    "approved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
                },
                "project": {"repo": str(repository), "base_ref": "main"},
                "todo": {"id": "T-1", "title": "Implement greeting"},
                "test": {
                    "command": test_command,
                    "allowed_paths": ["tests/**"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return repository, remote, contract


def _write_policy(repository: Path, command: list[str]) -> None:
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "project": {"root": str(repository), "trusted": True},
                "capabilities": {
                    "commands": {"unit": {"argv": command, "approved": True}},
                    "skills": {},
                },
                "publishing": {
                    "candidate": {
                        "approved": True,
                        "remote": "origin",
                        "branch_prefix": "aiwb/",
                    }
                },
                "harness": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
