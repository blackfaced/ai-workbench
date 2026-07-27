from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentRequest, ContractError, GoalRunner, preview_execution  # noqa: E402
from aiwb.mcp_server import McpServer  # noqa: E402


class FailIfCalledAgent:
    def run(self, request: AgentRequest):
        raise AssertionError(f"Agent must not start during preflight: {request.role}")


def test_draft_contract_preflight_is_side_effect_free_and_counts_the_dag() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        before = _tree(root)

        envelope = preview_execution(contract)

        assert _tree(root) == before
        assert envelope.approval_status == "draft"
        assert envelope.provider == "codex"
        assert envelope.model is None
        assert envelope.layers == (("T-1", "T-2"),)
        assert [
            (todo.todo_id, todo.layer, todo.agent_attempts, todo.harness_executions)
            for todo in envelope.todos
        ] == [
            ("T-1", 0, 3, 4),
            ("T-2", 0, 3, 4),
        ]
        value = envelope.to_dict()
        assert value["deterministic"] == {
            "agent_attempts": 7,
            "agent_attempts_by_role": {
                "test_designer": 2,
                "implementer": 2,
                "verifier": 2,
                "candidate_verifier": 1,
            },
            "harness_executions": 10,
            "harness_executions_by_stage": {
                "red": 2,
                "green": 2,
                "verify": 2,
                "integrate": 2,
                "candidate_acceptance": 2,
            },
            "final_candidate_acceptance": {
                "agent_attempts": 1,
                "harness_executions": 2,
            },
        }
        assert {
            item["name"] for item in value["conditional_paths"]
        } >= {
            "conflict_repair",
            "browser_diagnosis",
            "retry",
            "image_build",
            "candidate_publish",
        }
        assert value["provider_usage"] == {
            "status": "unknown",
            "unit": "provider_reported_tokens",
        }
        assert value["monetary_cost"] == {
            "status": "unknown",
            "currency": None,
        }
        assert "does not reduce total consumption" in value[
            "concurrency_explanation"
        ]


def test_cli_and_mcp_return_the_same_preflight_semantics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        expected = preview_execution(contract).to_dict()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "goal",
                "preflight",
                "--contract",
                str(contract),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        cli_value = json.loads(completed.stdout)

        server = McpServer(root / "missing-daemon.sock")
        tools = server._dispatch("tools/list", {})["tools"]
        assert "aiwb_goal_preflight" in {item["name"] for item in tools}
        result = server._call_tool(
            "aiwb_goal_preflight",
            {"contract_path": str(contract)},
        )
        assert result["isError"] is False
        mcp_value = json.loads(result["content"][0]["text"])

        assert cli_value == expected
        assert mcp_value == expected


def test_approved_contract_uses_the_same_preflight_baseline() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        data["approval"] = {
            "status": "approved",
            "approved_by": "owner",
            "approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc),
        }
        contract.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

        envelope = preview_execution(contract)

        assert envelope.approval_status == "approved"
        assert envelope.to_dict()["deterministic"]["agent_attempts"] == 7
        assert envelope.to_dict()["deterministic"]["harness_executions"] == 10


def test_repo_local_preflight_reports_a_production_target_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        data["harness"]["profiles"]["production"] = {
            "kind": "local_process",
            "environment": "production",
            "start": {"command": [sys.executable, "-m", "http.server"]},
            "ready": {"url": "http://127.0.0.1:8000", "timeout_seconds": 5},
        }
        workflow.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(contract).to_dict()

        assert result["readiness"] == "blocked"
        assert result["blockers"] == [
            {
                "code": "production_target",
                "message": "production Harness profile is forbidden: production",
                "action": (
                    f"Review {workflow.resolve()} and use only local or "
                    "non-production Harness and image profiles."
                ),
            }
        ]


def test_preflight_accepts_an_explicit_approved_policy_outside_the_repository() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        local_workflow = repository / ".ai-workbench" / "workflow.yaml"
        external_policy = root / "reviewed-policy.yaml"
        external_policy.write_bytes(local_workflow.read_bytes())
        local_workflow.unlink()
        local_workflow.parent.rmdir()
        contract = _write_draft_contract(root, repository)
        before = _tree(repository)

        envelope = preview_execution(contract, workflow_path=external_policy)

        assert _tree(repository) == before
        assert not local_workflow.exists()
        assert envelope.approval_status == "draft"
        assert envelope.layers == (("T-1", "T-2"),)
        assert envelope.to_dict()["policy"] == {
            "path": str(external_policy.resolve()),
            "source": "explicit",
            "candidate_commands": [],
            "approved_commands": [
                [sys.executable, "-m", "pytest", "-q"],
            ],
        }


def test_cli_and_mcp_accept_equivalent_explicit_policy_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "reviewed-policy.yaml"
        external_policy.write_bytes(
            (repository / ".ai-workbench" / "workflow.yaml").read_bytes()
        )
        expected = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        cli_values = []
        for option in ("--workflow", "--policy"):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aiwb",
                    "goal",
                    "preflight",
                    "--contract",
                    str(contract),
                    option,
                    str(external_policy),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            cli_values.append(json.loads(completed.stdout))

        server = McpServer(root / "missing-daemon.sock")
        mcp_values = []
        for argument in ("workflow_path", "policy_path"):
            result = server._call_tool(
                "aiwb_goal_preflight",
                {
                    "contract_path": str(contract),
                    argument: str(external_policy),
                },
            )
            assert result["isError"] is False
            mcp_values.append(json.loads(result["content"][0]["text"]))

        assert cli_values == [expected, expected]
        assert mcp_values == [expected, expected]


def test_preflight_reports_candidate_and_approved_commands_separately() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "reviewed-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["suggestions"] = {
            "commands": {
                "focused": {
                    "argv": [sys.executable, "-m", "pytest", "tests/test_focused.py"],
                    "reason": "focused test discovered",
                }
            }
        }
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["policy"]["candidate_commands"] == [
            {
                "name": "focused",
                "argv": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_focused.py",
                ],
                "reason": "focused test discovered",
            }
        ]
        assert result["policy"]["approved_commands"] == [
            [sys.executable, "-m", "pytest", "-q"],
        ]


def test_candidate_command_requires_an_exact_approved_mapping() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        contract_data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        candidate_command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_focused.py",
        ]
        for todo in contract_data["todos"]:
            todo["test"]["command"] = candidate_command
        contract.write_text(
            yaml.safe_dump(contract_data, sort_keys=False),
            encoding="utf-8",
        )
        external_policy = root / "reviewed-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["suggestions"] = {
            "commands": {
                "focused": {
                    "argv": candidate_command,
                    "reason": "focused test discovered",
                }
            }
        }
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["policy"]["candidate_commands"][0]["argv"] == candidate_command
        assert result["policy"]["approved_commands"] == [
            [sys.executable, "-m", "pytest", "-q"],
        ]
        assert result["blockers"] == [
            {
                "code": "approved_command_missing",
                "message": (
                    "Contract Todo T-1 test command is not exactly approved by "
                    "the selected policy."
                ),
                "action": (
                    "Review and add the exact command to "
                    f"{external_policy.resolve()} capabilities.commands with "
                    "approved: true."
                ),
            },
            {
                "code": "approved_command_missing",
                "message": (
                    "Contract Todo T-2 test command is not exactly approved by "
                    "the selected policy."
                ),
                "action": (
                    "Review and add the exact command to "
                    f"{external_policy.resolve()} capabilities.commands with "
                    "approved: true."
                ),
            },
        ]


def test_explicit_policy_root_mismatch_is_an_actionable_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        other_repository = root / "other-project"
        other_repository.mkdir()
        contract = _write_draft_contract(root, repository)
        external_policy = root / "wrong-root-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["project"]["root"] = str(other_repository)
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["blockers"] == [
            {
                "code": "policy_root_mismatch",
                "message": (
                    "The selected policy root does not match the Contract repository."
                ),
                "action": (
                    f"Review {external_policy.resolve()} and set project.root to "
                    f"{repository.resolve()}."
                ),
            }
        ]


def test_explicit_policy_production_target_is_an_actionable_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "production-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["harness"]["profiles"]["production"] = {
            "kind": "local_process",
            "environment": "production",
            "start": {"command": [sys.executable, "-m", "http.server"]},
            "ready": {"url": "http://127.0.0.1:8000", "timeout_seconds": 5},
        }
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["blockers"] == [
            {
                "code": "production_target",
                "message": "production Harness profile is forbidden: production",
                "action": (
                    f"Review {external_policy.resolve()} and use only local or "
                    "non-production Harness and image profiles."
                ),
            }
        ]


def test_explicit_policy_production_image_is_an_actionable_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "production-image-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        image_command = [sys.executable, "image-builder.py"]
        policy["capabilities"]["commands"]["image"] = {
            "argv": image_command,
            "approved": True,
        }
        policy["images"] = {
            "profiles": {
                "production": {
                    "environment": "production",
                    "start": {"command": image_command},
                    "status": {"command": image_command},
                    "result": {"command": image_command},
                }
            }
        }
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["blockers"] == [
            {
                "code": "production_target",
                "message": "production image profile is forbidden: production",
                "action": (
                    f"Review {external_policy.resolve()} and use only local or "
                    "non-production Harness and image profiles."
                ),
            }
        ]


def test_explicit_policy_requires_reviewed_approval_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "draft-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["status"] = "draft"
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["blockers"] == [
            {
                "code": "policy_not_approved",
                "message": "project policy status must be approved",
                "action": (
                    f"Review {external_policy.resolve()}, explicitly approve its "
                    "trusted project and capabilities, then rerun preflight."
                ),
            }
        ]


def test_policy_with_only_candidate_commands_stays_unapproved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "candidate-only-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        command = [sys.executable, "-m", "pytest", "-q"]
        policy["suggestions"] = {
            "commands": {
                "unit": {
                    "argv": command,
                    "reason": "pytest configuration detected",
                }
            }
        }
        policy["capabilities"]["commands"] = {}
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["policy"]["candidate_commands"] == [
            {
                "name": "unit",
                "argv": command,
                "reason": "pytest configuration detected",
            }
        ]
        assert result["policy"]["approved_commands"] == []
        assert result["blockers"] == [
            {
                "code": "approved_command_missing",
                "message": "project policy requires an approved command",
                "action": (
                    "Review and add the exact Contract test command to "
                    f"{external_policy.resolve()} capabilities.commands with "
                    "approved: true."
                ),
            }
        ]


def test_policy_command_with_approval_false_stays_unapproved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        external_policy = root / "unapproved-command-policy.yaml"
        policy = yaml.safe_load(
            (repository / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy["capabilities"]["commands"]["unit"]["approved"] = False
        external_policy.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        result = preview_execution(
            contract,
            workflow_path=external_policy,
        ).to_dict()

        assert result["readiness"] == "blocked"
        assert result["policy"]["approved_commands"] == []
        assert result["blockers"] == [
            {
                "code": "approved_command_missing",
                "message": "project command 'unit' must be approved",
                "action": (
                    "Review and add the exact Contract test command to "
                    f"{external_policy.resolve()} capabilities.commands with "
                    "approved: true."
                ),
            }
        ]


def test_candidate_only_policy_remains_rejected_by_strict_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_draft_contract(root, repository)
        contract_data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        contract_data["approval"] = {
            "status": "approved",
            "approved_by": "owner",
            "approved_at": datetime(2026, 7, 27, tzinfo=timezone.utc),
        }
        contract.write_text(
            yaml.safe_dump(contract_data, sort_keys=False),
            encoding="utf-8",
        )
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        policy = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        command = [sys.executable, "-m", "pytest", "-q"]
        policy["suggestions"] = {
            "commands": {
                "unit": {
                    "argv": command,
                    "reason": "pytest configuration detected",
                }
            }
        }
        policy["capabilities"]["commands"] = {}
        workflow.write_text(
            yaml.safe_dump(policy, sort_keys=False),
            encoding="utf-8",
        )

        with pytest.raises(
            ContractError,
            match="project policy requires an approved command",
        ):
            GoalRunner(
                state_dir=root / "state",
                agent=FailIfCalledAgent(),
            ).prepare(contract)


def _create_repository(root: Path) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
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
                    "skills": {},
                },
                "harness": {"profiles": {"local": {"environment": "local"}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_draft_contract(root: Path, repository: Path) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": "preflight-goal",
                    "title": "Preview parallel work",
                    "requirement": "Implement two independent behaviors.",
                    "acceptance": [
                        {"id": "AC-1", "statement": "First behavior works."},
                        {"id": "AC-2", "statement": "Second behavior works."},
                    ],
                },
                "approval": {"status": "draft"},
                "agent": {"provider": "codex"},
                "project": {"repo": str(repository), "base_ref": "main"},
                "todos": [
                    {
                        "id": "T-1",
                        "title": "Implement first behavior",
                        "depends_on": [],
                        "test_ids": ["AC-1"],
                        "test": {
                            "command": command,
                            "allowed_paths": ["tests/test_first.py"],
                        },
                    },
                    {
                        "id": "T-2",
                        "title": "Implement second behavior",
                        "depends_on": [],
                        "test_ids": ["AC-2"],
                        "test": {
                            "command": command,
                            "allowed_paths": ["tests/test_second.py"],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _tree(root: Path) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                str(path.relative_to(root)),
                path.stat().st_size,
            )
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
