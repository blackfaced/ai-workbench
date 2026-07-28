from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import GoalHandoffBridge, GoalIntake  # noqa: E402
from aiwb.cli import main as cli_main  # noqa: E402
from aiwb.mcp_server import McpServer  # noqa: E402


def test_small_single_todo_task_stays_in_the_installed_matt_flow() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        contract = _write_contract(root, repository, todo_count=1)
        before = _tree(root)

        result = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert _tree(root) == before
        assert result.readiness == "interactive"
        assert result.cheapest_viable_path == "interactive_matt"
        assert result.blockers == ()
        assert result.next_action == "invoke_ask_matt"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 4
        assert result.execution_envelope["deterministic"]["harness_executions"] == 5


def test_durable_draft_is_ready_for_one_explicit_approval() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Complete two independent Todos overnight with recovery.",
        )

        result = GoalIntake(daemon_probe=lambda: True).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert result.readiness == "ready_for_approval"
        assert result.cheapest_viable_path == "ai_workbench_unattended"
        assert result.blockers == ()
        assert result.daemon_status == "ok"
        assert result.approval_required is True
        assert result.submission_required is True
        assert result.next_action == "approve_contract"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 7
        assert result.execution_envelope["deterministic"]["harness_executions"] == 10


def test_durable_intake_returns_all_actionable_readiness_blockers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root, approved=False)
        contract = root / "blocked.contract.yaml"
        contract.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "goal": {
                        "id": "blocked-goal",
                        "title": "Blocked overnight work",
                        "requirement": "Run multiple Todos overnight.",
                        "acceptance": [],
                    },
                    "approval": {"status": "draft"},
                    "project": {"repo": str(repository), "base_ref": "main"},
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "First",
                            "test_ids": [],
                            "test": {},
                        },
                        {
                            "id": "T-2",
                            "title": "Second",
                            "depends_on": ["missing"],
                            "test_ids": [],
                            "test": {
                                "command": ["missing-test"],
                                "allowed_paths": [],
                                "harness": "production",
                            },
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )

        codes = {blocker.code for blocker in result.blockers}
        assert result.readiness == "blocked"
        assert codes >= {
            "acceptance_boundary",
            "todo_dependencies",
            "harness_configuration",
            "permissions",
            "provider_selection",
            "resource_policy",
            "non_production",
        }
        assert result.next_action == "resolve_blockers"
        assert result.execution_envelope["deterministic"]["agent_attempts"] == 7


def test_approved_contract_requires_daemon_then_explicit_submission() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Run unattended overnight.",
        )
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

        unavailable = GoalIntake(daemon_probe=lambda: False).inspect(
            repository=repository,
            contract_path=contract,
        )
        available = GoalIntake(daemon_probe=lambda: True).inspect(
            repository=repository,
            contract_path=contract,
        )

        assert unavailable.readiness == "blocked"
        assert [item.code for item in unavailable.blockers] == ["daemon_state"]
        assert unavailable.next_action == "start_daemon"
        assert available.readiness == "ready_to_submit"
        assert available.blockers == ()
        assert available.approval_required is False
        assert available.submission_required is True
        assert available.next_action == "submit_contract"


def test_accepted_tickets_choose_interactive_or_contract_handoff_by_shape() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        small = _write_tickets(root / "small.md", ["Fix typo"])
        durable = _write_tickets(
            root / "durable.md",
            ["Add API", "Add browser E2E"],
        )
        intake = GoalIntake(daemon_probe=lambda: True)

        small_result = intake.inspect(
            repository=repository,
            tickets_path=small,
        )
        durable_result = intake.inspect(
            repository=repository,
            tickets_path=durable,
        )

        assert small_result.readiness == "interactive"
        assert small_result.next_action == "invoke_ask_matt"
        assert durable_result.readiness == "blocked"
        assert durable_result.cheapest_viable_path == "ai_workbench_unattended"
        assert durable_result.next_action == "create_contract_draft"
        assert {item.code for item in durable_result.blockers} == {
            "contract_draft"
        }
        assert durable_result.execution_envelope["deterministic"][
            "agent_attempts"
        ] == 7


def test_multi_todo_planning_handoff_preserves_source_and_planning_boundaries() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {
                        "system": "github",
                        "repository": "blackfaced/ai-workbench",
                        "issue": 14,
                    },
                    "goal": {
                        "id": "goal-14",
                        "title": "Accept generic planning handoffs",
                        "requirement": "Preserve a reviewed planning handoff.",
                        "acceptance": [
                            {
                                "id": "AC-1",
                                "statement": "The source provenance is preserved.",
                            },
                            {
                                "id": "AC-2",
                                "statement": "Todo dependencies are preserved.",
                            },
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Normalize the handoff",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                        },
                        {
                            "id": "T-2",
                            "title": "Expose intake semantics",
                            "depends_on": ["T-1"],
                            "acceptance_ids": ["AC-2"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        before = _tree(root)

        result = GoalIntake(
            daemon_probe=lambda: (_ for _ in ()).throw(
                AssertionError("planning handoff intake must not require a daemon")
            )
        ).inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert _tree(root) == before
        assert result.source == "handoff"
        assert result.readiness == "blocked"
        assert result.cheapest_viable_path == "ai_workbench_unattended"
        assert result.next_action == "create_contract_draft"
        assert result.daemon_status == "not_required"
        assert result.planning_handoff == {
            "schema_version": 1,
            "kind": "aiwb.planning-handoff",
            "format": "versioned",
            "provenance": {
                "system": "github",
                "repository": "blackfaced/ai-workbench",
                "issue": 14,
            },
            "goal": {
                "id": "goal-14",
                "title": "Accept generic planning handoffs",
                "requirement": "Preserve a reviewed planning handoff.",
            },
            "acceptance": [
                {
                    "id": "AC-1",
                    "statement": "The source provenance is preserved.",
                },
                {
                    "id": "AC-2",
                    "statement": "Todo dependencies are preserved.",
                },
            ],
            "todos": [
                {
                    "id": "T-1",
                    "title": "Normalize the handoff",
                    "depends_on": [],
                    "acceptance_ids": ["AC-1"],
                },
                {
                    "id": "T-2",
                    "title": "Expose intake semantics",
                    "depends_on": ["T-1"],
                    "acceptance_ids": ["AC-2"],
                },
            ],
        }
        assert result.warnings == ()
        assert {item.code for item in result.blockers} == {"contract_draft"}
        assert result.execution_envelope["layers"] == [["T-1"], ["T-2"]]


def test_handoff_bridge_writes_an_unapproved_preflighted_contract_outside_repo() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {
                        "system": "github",
                        "repository": "blackfaced/ai-workbench",
                        "issue": 16,
                    },
                    "goal": {
                        "id": "goal-16",
                        "title": "Bridge planning handoffs",
                        "requirement": "Create a safe next artifact.",
                        "acceptance": [
                            {
                                "id": "AC-1",
                                "statement": "The Contract remains unapproved.",
                            }
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Create the bridge",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                            "command_name": "unit",
                            "allowed_paths": ["tests/test_bridge.py"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "reviewed-policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = root / "artifacts" / "goal-16.contract.yaml"
        before = _tree(repository)

        result = GoalHandoffBridge().create(
            repository=repository,
            handoff_path=handoff,
            policy_path=policy,
            output_path=output,
        )

        assert result.readiness == "ready_for_contract_approval"
        assert result.artifact_kind == "contract"
        assert result.artifact_path == str(output.resolve())
        assert result.blockers == ()
        assert result.warnings == ()
        contract = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert contract["approval"] == {
            "status": "draft",
            "approved_by": "",
            "approved_at": "",
        }
        assert contract["todos"][0]["test"] == {
            "command": [sys.executable, "-m", "pytest", "-q"],
            "allowed_paths": ["tests/test_bridge.py"],
            "timeout_seconds": 600,
        }
        assert contract["draft"]["source_provenance"]["issue"] == 16
        assert result.preflight["readiness"] == "ready"
        assert result.preflight["approval_status"] == "draft"
        assert _tree(repository) == before


def test_handoff_bridge_blocks_without_command_or_paths_and_writes_policy_draft() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {
                        "system": "github",
                        "repository": "blackfaced/ai-workbench",
                        "issue": 16,
                    },
                    "goal": {
                        "id": "goal-16",
                        "title": "Bridge planning handoffs",
                        "requirement": "Create a safe next artifact.",
                        "acceptance": [
                            {
                                "id": "AC-1",
                                "statement": "Missing execution data blocks.",
                            }
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Create the bridge",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "reviewed-policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = root / "artifacts" / "workflow-draft.yaml"
        before = _tree(repository)

        result = GoalHandoffBridge().create(
            repository=repository,
            handoff_path=handoff,
            policy_path=policy,
            output_path=output,
        )

        assert result.readiness == "blocked"
        assert result.artifact_kind == "policy_draft"
        assert result.preflight == {}
        assert {blocker.code for blocker in result.blockers} == {
            "approved_command_missing",
            "allowed_paths_missing",
        }
        assert result.warnings == (
            "Todo T-1 needs reviewed allowed_paths before execution.",
        )
        draft = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert draft["kind"] == "aiwb.workflow-policy-draft"
        assert draft["status"] == "draft"
        assert draft["executable"] is False
        assert draft["project"]["trusted"] is False
        assert draft["source"]["handoff_provenance"]["issue"] == 16
        assert len(draft["review_actions"]) == 2
        serialized = output.read_text(encoding="utf-8")
        assert "REPLACE_WITH" not in serialized
        assert "todos:" not in serialized
        assert _tree(repository) == before


def test_handoff_bridge_turns_unapproved_policy_into_actionable_draft() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "test", "id": "unapproved-policy"},
                    "goal": {
                        "id": "policy-goal",
                        "title": "Review policy",
                        "requirement": "Keep policy review explicit.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "Policy stays unapproved."}
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Review",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                            "command_name": "unit",
                            "allowed_paths": ["tests/test_policy.py"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "draft-policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "draft",
                    "project": {"root": str(repository), "trusted": False},
                    "suggestions": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "reason": "pytest detected",
                            }
                        }
                    },
                    "capabilities": {"commands": {}, "skills": {}},
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = root / "policy-review.yaml"

        result = GoalHandoffBridge().create(
            repository=repository,
            handoff_path=handoff,
            policy_path=policy,
            output_path=output,
        )

        assert result.readiness == "blocked"
        assert result.artifact_kind == "policy_draft"
        assert {blocker.code for blocker in result.blockers} == {
            "policy_not_approved",
            "approved_command_missing",
        }
        draft = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert draft["candidate_commands"] == {
            "unit": {
                "argv": [sys.executable, "-m", "pytest", "-q"],
                "reason": "pytest detected",
            }
        }
        assert "candidate_policy" not in draft
        assert draft["executable"] is False


def test_handoff_bridge_writes_validation_failures_to_the_requested_artifact() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "unsupported-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "kind": "aiwb.planning-handoff",
                    "goal": {},
                }
            ),
            encoding="utf-8",
        )
        policy = root / "policy.yaml"
        policy.write_text("not: inspected\n", encoding="utf-8")
        output = root / "validation-result.yaml"

        result = GoalHandoffBridge().create(
            repository=repository,
            handoff_path=handoff,
            policy_path=policy,
            output_path=output,
        )

        assert result.readiness == "blocked"
        assert result.artifact_kind == "policy_draft"
        assert result.artifact_path == str(output.resolve())
        assert [blocker.code for blocker in result.blockers] == [
            "unsupported_handoff_schema"
        ]
        draft = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert draft["kind"] == "aiwb.workflow-policy-draft"
        assert draft["executable"] is False
        assert draft["source"]["input_policy"] == str(policy.resolve())
        assert draft["blockers"][0]["code"] == "unsupported_handoff_schema"


def test_handoff_bridge_preserves_handoff_validation_blockers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "incomplete-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {},
                    "goal": {
                        "id": "incomplete",
                        "title": "Incomplete",
                        "requirement": "Do not create an executable Contract.",
                        "acceptance": [],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Incomplete",
                            "depends_on": ["missing"],
                            "acceptance_ids": [],
                            "command_name": "unit",
                            "allowed_paths": ["tests/test_incomplete.py"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = root / "incomplete-result.yaml"

        result = GoalHandoffBridge().create(
            repository=repository,
            handoff_path=handoff,
            policy_path=policy,
            output_path=output,
        )

        assert result.artifact_kind == "policy_draft"
        assert {blocker.code for blocker in result.blockers} >= {
            "handoff_provenance",
            "todo_dependencies",
            "acceptance_boundary",
        }
        assert yaml.safe_load(output.read_text(encoding="utf-8"))["executable"] is False


def test_handoff_bridge_rejects_output_inside_repository_before_writing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text("{}", encoding="utf-8")
        policy = root / "policy.yaml"
        policy.write_text("{}", encoding="utf-8")
        output = repository / "bridge.yaml"

        with pytest.raises(ValueError, match="outside"):
            GoalHandoffBridge().create(
                repository=repository,
                handoff_path=handoff,
                policy_path=policy,
                output_path=output,
            )

        assert not output.exists()


def test_handoff_bridge_leaves_no_contract_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "test", "id": "atomic"},
                    "goal": {
                        "id": "atomic-goal",
                        "title": "Atomic bridge",
                        "requirement": "Do not leave partial artifacts.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "No partial artifact."}
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Bridge",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                            "command_name": "unit",
                            "allowed_paths": ["tests/test_bridge.py"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = root / "contract.yaml"

        monkeypatch.setattr(
            "aiwb.handoff_bridge.preview_execution",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("simulated preflight failure")
            ),
        )

        with pytest.raises(RuntimeError, match="simulated preflight"):
            GoalHandoffBridge().create(
                repository=repository,
                handoff_path=handoff,
                policy_path=policy,
                output_path=output,
            )

        assert not output.exists()
        assert not list(root.glob(".contract.yaml.*.tmp"))


def test_cli_mcp_and_skill_share_handoff_bridge_semantics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {
                        "system": "github",
                        "repository": "blackfaced/ai-workbench",
                        "issue": 16,
                    },
                    "goal": {
                        "id": "goal-16",
                        "title": "Bridge planning handoffs",
                        "requirement": "Create a safe next artifact.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "The bridge is safe."}
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Create the bridge",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = root / "reviewed-policy.yaml"
        policy.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [sys.executable, "-m", "pytest", "-q"],
                                "approved": True,
                            }
                        },
                        "skills": {},
                    },
                    "harness": {"profiles": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        cli_output = root / "cli-policy-draft.yaml"
        mcp_output = root / "mcp-policy-draft.yaml"

        returncode = cli_main(
            [
                "goal",
                "bridge",
                "--repo",
                str(repository),
                "--handoff",
                str(handoff),
                "--policy",
                str(policy),
                "--output",
                str(cli_output),
            ]
        )
        cli_value = json.loads(capsys.readouterr().out)
        mcp_result = McpServer(root / "missing.sock")._call_tool(
            "aiwb_handoff_bridge",
            {
                "repository": str(repository),
                "handoff_path": str(handoff),
                "policy_path": str(policy),
                "output_path": str(mcp_output),
            },
        )
        mcp_value = json.loads(mcp_result["content"][0]["text"])

        assert returncode == 0
        assert mcp_result["isError"] is False
        assert cli_value["artifact_path"] == str(cli_output.resolve())
        assert mcp_value["artifact_path"] == str(mcp_output.resolve())
        assert {
            key: value
            for key, value in cli_value.items()
            if key != "artifact_path"
        } == {
            key: value
            for key, value in mcp_value.items()
            if key != "artifact_path"
        }
        skill = (
            TOOL_ROOT / "skills" / "intake-aiwb-goal" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "aiwb goal bridge" in skill
        assert "aiwb_handoff_bridge" in skill
        assert "Do not invent" in skill


def test_bare_issue_json_is_normalized_without_inventing_planning_details() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        issue = root / "issue.json"
        issue.write_text(
            json.dumps(
                {
                    "number": 14,
                    "title": "Accept generic planning handoffs at Goal intake",
                    "body": "Preserve this issue as planning source material.",
                    "html_url": (
                        "https://github.com/blackfaced/ai-workbench/issues/14"
                    ),
                    "repository_url": (
                        "https://api.github.com/repos/blackfaced/ai-workbench"
                    ),
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=issue,
        )

        assert result.planning_handoff == {
            "schema_version": 1,
            "kind": "aiwb.planning-handoff",
            "format": "bare_issue",
            "provenance": {
                "system": "github",
                "repository": "blackfaced/ai-workbench",
                "issue": 14,
                "url": "https://github.com/blackfaced/ai-workbench/issues/14",
            },
            "goal": {
                "id": "github:blackfaced/ai-workbench#14",
                "title": "Accept generic planning handoffs at Goal intake",
                "requirement": "Preserve this issue as planning source material.",
            },
            "acceptance": [],
            "todos": [],
        }
        assert {item.code for item in result.blockers} == {
            "acceptance_boundary",
            "contract_draft",
        }
        assert result.execution_envelope["layers"] == [["T-1"]]


def test_gh_cli_issue_json_preserves_repository_provenance_from_url() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        issue = root / "gh-issue.json"
        issue.write_text(
            json.dumps(
                {
                    "number": 15,
                    "title": "Use an explicit reviewed policy",
                    "body": "Preflight against a reviewed policy artifact.",
                    "url": "https://github.com/blackfaced/ai-workbench/issues/15",
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=issue,
        )

        assert result.planning_handoff["provenance"] == {
            "system": "github",
            "repository": "blackfaced/ai-workbench",
            "issue": 15,
            "url": "https://github.com/blackfaced/ai-workbench/issues/15",
        }
        assert result.planning_handoff["goal"]["id"] == (
            "github:blackfaced/ai-workbench#15"
        )


def test_small_planning_handoff_stays_in_the_installed_matt_flow() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        handoff = root / "small-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "local", "reference": "note-1"},
                    "goal": {
                        "id": "small-goal",
                        "title": "Correct one label",
                        "requirement": "Correct one label in the CLI output.",
                        "acceptance": [
                            {
                                "id": "AC-1",
                                "statement": "The corrected label is shown.",
                            }
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Correct the label",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake(
            daemon_probe=lambda: (_ for _ in ()).throw(
                AssertionError("interactive handoff intake must not require a daemon")
            )
        ).inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "interactive"
        assert result.cheapest_viable_path == "interactive_matt"
        assert result.blockers == ()
        assert result.next_action == "invoke_ask_matt"
        assert result.daemon_status == "not_required"
        assert result.approval_required is False
        assert result.submission_required is False
        assert result.planning_handoff["goal"]["id"] == "small-goal"


def test_small_planning_handoff_can_omit_todo_structure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        handoff = root / "small-goal-only-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "local", "reference": "note-2"},
                    "goal": {
                        "id": "small-goal-only",
                        "title": "Correct one label",
                        "requirement": "Correct one label in the CLI output.",
                        "acceptance": [
                            {
                                "id": "AC-1",
                                "statement": "The corrected label is shown.",
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "interactive"
        assert result.next_action == "invoke_ask_matt"
        assert result.blockers == ()
        assert result.planning_handoff["todos"] == []


def test_unsupported_planning_handoff_schema_returns_an_actionable_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "future-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "planner", "reference": "future-1"},
                    "goal": {
                        "id": "future-goal",
                        "title": "Use a future handoff",
                        "requirement": "Exercise a future schema.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "The handoff is accepted."}
                        ],
                    },
                    "todos": [],
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "use_supported_handoff_schema"
        assert result.planning_handoff == {}
        assert result.warnings == ()
        assert [item.code for item in result.blockers] == [
            "unsupported_handoff_schema"
        ]
        assert result.blockers[0].action == (
            "Provide aiwb.planning-handoff schema_version 1 or a bare issue JSON document."
        )


def test_incomplete_planning_handoff_returns_readiness_blockers_and_warnings() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "incomplete-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "goal": {
                        "id": "incomplete-goal",
                        "title": "Incomplete planning handoff",
                        "requirement": "Retain the known planning facts.",
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Known Todo",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "resolve_handoff_blockers"
        assert {item.code for item in result.blockers} == {
            "acceptance_boundary",
            "contract_draft",
            "handoff_provenance",
            "todo_dependencies",
        }
        assert result.warnings == (
            "Todo T-1 has no acceptance_ids mapping.",
        )
        assert result.planning_handoff["goal"]["id"] == "incomplete-goal"
        assert result.planning_handoff["acceptance"] == []
        assert result.planning_handoff["todos"] == [
            {"id": "T-1", "title": "Known Todo"}
        ]


def test_invalid_small_handoff_does_not_bypass_readiness_for_interactive_path() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        _install_ask_matt(repository)
        handoff = root / "invalid-small-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "goal": {
                        "id": "small-invalid",
                        "title": "Small but incomplete",
                        "requirement": "Make one small change.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "The change works."}
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "Make the change",
                            "acceptance_ids": ["AC-1"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "resolve_handoff_blockers"
        assert {item.code for item in result.blockers} >= {
            "handoff_provenance",
            "todo_dependencies",
        }


def test_cyclic_handoff_returns_a_dependency_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "cyclic-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "planner", "reference": "cycle"},
                    "goal": {
                        "id": "cyclic-goal",
                        "title": "Cyclic planning handoff",
                        "requirement": "Run two planned Todos unattended.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "First behavior works."},
                            {"id": "AC-2", "statement": "Second behavior works."},
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "First",
                            "depends_on": ["T-2"],
                            "acceptance_ids": ["AC-1"],
                        },
                        {
                            "id": "T-2",
                            "title": "Second",
                            "depends_on": ["T-1"],
                            "acceptance_ids": ["AC-2"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "resolve_handoff_blockers"
        assert {item.code for item in result.blockers} >= {
            "todo_dependencies"
        }


def test_malformed_handoff_returns_an_actionable_validation_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "malformed-handoff.json"
        handoff.write_text(
            json.dumps({"unexpected": True}),
            encoding="utf-8",
        )

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "resolve_handoff_blockers"
        assert result.planning_handoff == {}
        assert result.execution_envelope == {}
        assert [item.code for item in result.blockers] == [
            "handoff_validation"
        ]
        assert result.blockers[0].action == (
            "Provide aiwb.planning-handoff schema_version 1 or a bare issue "
            "JSON document with number, title, and body."
        )


def test_invalid_json_handoff_returns_an_actionable_validation_blocker() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "invalid.json"
        handoff.write_text('{"schema_version": 1,', encoding="utf-8")

        result = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        )

        assert result.readiness == "blocked"
        assert result.next_action == "resolve_handoff_blockers"
        assert [item.code for item in result.blockers] == [
            "handoff_validation"
        ]
        assert "cannot read planning handoff" in result.blockers[0].message


def test_cli_mcp_and_skill_share_planning_handoff_intake_semantics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "aiwb.planning-handoff",
                    "provenance": {"system": "planner", "reference": "plan-14"},
                    "goal": {
                        "id": "goal-14",
                        "title": "Accept a planning handoff",
                        "requirement": "Run two planned Todos unattended.",
                        "acceptance": [
                            {"id": "AC-1", "statement": "First behavior works."},
                            {"id": "AC-2", "statement": "Second behavior works."},
                        ],
                    },
                    "todos": [
                        {
                            "id": "T-1",
                            "title": "First behavior",
                            "depends_on": [],
                            "acceptance_ids": ["AC-1"],
                        },
                        {
                            "id": "T-2",
                            "title": "Second behavior",
                            "depends_on": ["T-1"],
                            "acceptance_ids": ["AC-2"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        expected = GoalIntake().inspect(
            repository=repository,
            handoff_path=handoff,
        ).to_dict()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        missing_socket = root / "missing-daemon.sock"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "goal",
                "intake",
                "--repo",
                str(repository),
                "--handoff",
                str(handoff),
                "--socket",
                str(missing_socket),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        cli_value = json.loads(completed.stdout)

        result = McpServer(missing_socket)._call_tool(
            "aiwb_goal_intake",
            {
                "repository": str(repository),
                "handoff_path": str(handoff),
            },
        )
        assert result["isError"] is False
        mcp_value = json.loads(result["content"][0]["text"])

        skill_text = (
            TOOL_ROOT / "skills" / "intake-aiwb-goal" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert cli_value == expected
        assert mcp_value == expected
        assert "--handoff" in skill_text
        assert "handoff_path" in skill_text
        assert "reimplement" in skill_text


def test_cli_and_mcp_share_the_same_intake_result() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _create_repository(root)
        contract = _write_contract(
            root,
            repository,
            todo_count=2,
            requirement="Run unattended overnight.",
        )
        missing_socket = root / "missing-daemon.sock"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "goal",
                "intake",
                "--repo",
                str(repository),
                "--contract",
                str(contract),
                "--socket",
                str(missing_socket),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        cli_value = json.loads(completed.stdout)

        server = McpServer(missing_socket)
        result = server._call_tool(
            "aiwb_goal_intake",
            {
                "repository": str(repository),
                "contract_path": str(contract),
            },
        )
        assert result["isError"] is False
        mcp_value = json.loads(result["content"][0]["text"])

        assert cli_value == mcp_value
        assert cli_value["readiness"] == "ready_for_approval"
        assert cli_value["daemon_status"] == "unavailable"
        assert cli_value["next_action"] == "approve_contract"


def _create_repository(root: Path, approved: bool = True) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    command = [sys.executable, "-m", "pytest", "-q"]
    workflow = repository / ".ai-workbench" / "workflow.yaml"
    workflow.parent.mkdir()
    workflow.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "approved" if approved else "draft",
                "project": {
                    "root": str(repository),
                    "trusted": approved,
                },
                "capabilities": {
                    "commands": {
                        "unit": {"argv": command, "approved": approved},
                    },
                    "skills": {},
                },
                "harness": {
                    "allowed_kubernetes_contexts": [],
                    "profiles": (
                        {}
                        if approved
                        else {
                            "production": {
                                "kind": "kubernetes",
                                "environment": "production",
                                "context": "production",
                            }
                        }
                    ),
                },
                "images": {"profiles": {}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _write_contract(
    root: Path,
    repository: Path,
    todo_count: int,
    requirement: str = "Make one small local change.",
) -> Path:
    command = [sys.executable, "-m", "pytest", "-q"]
    acceptance = [
        {"id": f"AC-{index}", "statement": f"Behavior {index} works."}
        for index in range(1, todo_count + 1)
    ]
    todos = [
        {
            "id": f"T-{index}",
            "title": f"Implement behavior {index}",
            "depends_on": [],
            "test_ids": [f"AC-{index}"],
            "test": {
                "command": command,
                "allowed_paths": [f"tests/test_behavior_{index}.py"],
            },
        }
        for index in range(1, todo_count + 1)
    ]
    contract = root / f"{todo_count}-todo.contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "goal": {
                    "id": f"intake-{todo_count}-todo",
                    "title": "Inspect task readiness",
                    "requirement": requirement,
                    "acceptance": acceptance,
                },
                "approval": {"status": "draft"},
                "agent": {"provider": "codex"},
                "resources": {},
                "project": {"repo": str(repository), "base_ref": "main"},
                "todos": todos,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return contract


def _install_ask_matt(repository: Path) -> None:
    skill = repository / ".codex" / "skills" / "ask-matt" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: ask-matt\n"
        "description: Route general engineering work to an upstream Skill.\n"
        "---\n",
        encoding="utf-8",
    )


def _write_tickets(path: Path, titles: list[str]) -> Path:
    lines = ["# Tickets: Intake fixture", "Accepted engineering work.", ""]
    for index, title in enumerate(titles):
        lines.extend(
            [
                f"## {title}",
                f"**What to build:** Implement {title.lower()}.",
                "**Blocked by:** None",
                f"- [ ] {title} is accepted.",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tree(root: Path) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (str(path.relative_to(root)), path.stat().st_size)
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
