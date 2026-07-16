from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    AgentRequest,
    ContractError,
    GoalRunner,
    ProjectConfigError,
    ProjectPolicy,
)


class FailIfCalledAgent:
    def run(self, request: AgentRequest):
        raise AssertionError(f"Agent must not start for untrusted project: {request.role}")


def test_runner_rejects_an_untrusted_project_before_starting_an_agent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        (repository / "README.md").write_text("# Untrusted fixture\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(
            repository,
            "-c",
            "user.name=AIWB",
            "-c",
            "user.email=aiwb@example.test",
            "commit",
            "-m",
            "Initial fixture",
        )

        workflow = repository / ".ai-workbench" / "workflow.yaml"
        workflow.parent.mkdir()
        workflow.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": False},
                    "capabilities": {"commands": {}, "skills": {}},
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        test_command = [sys.executable, "-m", "pytest", "-q"]
        contract = root / "contract.yaml"
        contract.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "goal": {
                        "id": "untrusted-goal",
                        "title": "Do not run",
                        "requirement": "This Goal must be rejected.",
                        "acceptance": [{"id": "AC-1", "statement": "No Agent starts."}],
                    },
                    "approval": {
                        "status": "approved",
                        "approved_by": "owner",
                        "approved_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                    },
                    "project": {"repo": str(repository), "base_ref": "main"},
                    "todo": {"id": "T-1", "title": "Rejected Todo"},
                    "test": {
                        "command": test_command,
                        "allowed_paths": ["tests/**"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ContractError, match="trusted"):
            GoalRunner(state_dir=root / "state", agent=FailIfCalledAgent()).run(contract)


def test_project_policy_rejects_a_production_image_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        command = [sys.executable, "image_builder.py"]
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
                            "image": {"argv": command, "approved": True},
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                    "images": {
                        "profiles": {
                            "forbidden": {
                                "environment": "production",
                                "start": {"command": command},
                                "status": {"command": command},
                                "result": {"command": command},
                            }
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigError, match="production image profile"):
            ProjectPolicy.load(workflow)


def test_project_policy_loads_explicit_local_role_skills() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        skill = repository / ".agents" / "skills" / "focused-implementation" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "# Focused implementation\n\nKeep the production change small.\n",
            encoding="utf-8",
        )
        command = [sys.executable, "-m", "pytest", "-q"]
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
                            "unit": {"argv": command, "approved": True},
                        },
                        "skills": {
                            "implementer": [
                                ".agents/skills/focused-implementation/SKILL.md",
                            ],
                        },
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        policy = ProjectPolicy.load(workflow)

        assert policy.role_skill_texts == {
            "implementer": (
                (
                    ".agents/skills/focused-implementation/SKILL.md",
                    "# Focused implementation\n\nKeep the production change small.\n",
                ),
            ),
        }


@pytest.mark.parametrize(
    ("skills", "message"),
    [
        ({"planner": ["skills/plan/SKILL.md"]}, "unsupported role"),
        ({"implementer": ["../outside/SKILL.md"]}, "local SKILL.md"),
        ({"implementer": ["skills/missing/SKILL.md"]}, "does not exist"),
    ],
)
def test_project_policy_rejects_unsafe_or_unknown_role_skills(
    skills: dict[str, object],
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        command = [sys.executable, "-m", "pytest", "-q"]
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
                            "unit": {"argv": command, "approved": True},
                        },
                        "skills": skills,
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigError, match=message):
            ProjectPolicy.load(workflow)


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            {"approved": False, "remote": "origin", "branch_prefix": "aiwb/"},
            "explicitly approved",
        ),
        (
            {"approved": True, "remote": "-unsafe", "branch_prefix": "aiwb/"},
            "safe Git remote",
        ),
        (
            {"approved": True, "remote": "origin", "branch_prefix": "main"},
            "safe namespace",
        ),
    ],
)
def test_candidate_publish_policy_requires_explicit_safe_namespace(
    candidate: dict[str, object],
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        command = [sys.executable, "-m", "pytest", "-q"]
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
                            "unit": {"argv": command, "approved": True},
                        },
                        "skills": {},
                    },
                    "publishing": {"candidate": candidate},
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigError, match=message):
            ProjectPolicy.load(workflow)


def test_candidate_publish_policy_rejects_an_unconfigured_remote_before_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        command = [sys.executable, "-m", "pytest", "-q"]
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
                            "unit": {"argv": command, "approved": True},
                        },
                        "skills": {},
                    },
                    "publishing": {
                        "candidate": {
                            "approved": True,
                            "remote": "missing",
                            "branch_prefix": "aiwb/",
                        }
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        policy = ProjectPolicy.load(workflow)
        with pytest.raises(ProjectConfigError, match="remote is not configured"):
            policy.authorize_publish(repository)


@pytest.mark.parametrize(
    ("environment", "context", "message"),
    [
        ("production", "dev-context", "production Harness profile"),
        ("non-production", "other-context", "context is not allowlisted"),
    ],
)
def test_kubernetes_harness_requires_non_production_allowlisted_context(
    environment: str,
    context: str,
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        command = [sys.executable, "kube_harness.py"]
        gate = [sys.executable, "-m", "pytest", "-q"]
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
                            "kubernetes": {"argv": command, "approved": True},
                            "gate": {"argv": gate, "approved": True},
                        },
                        "skills": {},
                    },
                    "harness": {
                        "allowed_kubernetes_contexts": ["dev-context"],
                        "profiles": {
                            "cluster": {
                                "kind": "kubernetes",
                                "environment": environment,
                                "context": context,
                                "namespace_prefix": "aiwb",
                                "ttl_seconds": 3600,
                                "provision": {"command": command},
                                "collect": {"command": command},
                                "cleanup": {"command": command},
                            }
                        },
                    },
                    "images": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectConfigError, match=message):
            ProjectPolicy.load(workflow)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
