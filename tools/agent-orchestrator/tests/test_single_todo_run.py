from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import AgentRequest, AgentResult, GoalRunner, RunReport  # noqa: E402


class PlannedInterruption(RuntimeError):
    pass


class ScriptedAgentAdapter:
    def __init__(self, interrupt_implementer: bool = False) -> None:
        self.interrupt_implementer = interrupt_implementer
        self.roles = []
        self.providers = []
        self.models = []
        self.prompts = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.roles.append(request.role)
        self.providers.append(request.provider)
        self.models.append(request.model)
        self.prompts.append((request.role, request.prompt))
        worktree = Path(request.worktree)

        if request.role == "test_designer":
            tests = worktree / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_greeting.py").write_text(
                "from greeting import greeting\n\n"
                "def test_greeting_includes_the_name():\n"
                "    assert greeting('Ada') == 'Hello, Ada!'\n",
                encoding="utf-8",
            )
        elif request.role == "implementer":
            if self.interrupt_implementer:
                raise PlannedInterruption("simulated host restart")
            (worktree / "greeting.py").write_text(
                "def greeting(name):\n"
                "    return f'Hello, {name}!'\n",
                encoding="utf-8",
            )
        elif request.role != "verifier":
            raise AssertionError(f"unexpected role: {request.role}")

        return AgentResult(
            session_id=f"{request.role}-session",
            final_output=f"{request.role} completed",
            usage={"input_tokens": 5} if request.role == "verifier" else {},
        )


class SingleTodoRunTest(unittest.TestCase):
    def test_run_recovers_from_red_checkpoint_and_becomes_merge_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "project"
            state_dir = root / "state"
            repository.mkdir()
            test_command = [sys.executable, "-m", "pytest", "-q"]
            self._git(repository, "init", "-b", "main")
            self._git(repository, "config", "user.name", "AI Workbench Test")
            self._git(repository, "config", "user.email", "aiwb@example.test")
            (repository / ".gitignore").write_text(
                "__pycache__/\n*.pyc\n.pytest_cache/\n",
                encoding="utf-8",
            )
            (repository / "README.md").write_text("# Fixture project\n", encoding="utf-8")
            skill = repository / ".agents" / "skills" / "focused" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "# Focused work\n\nPrefer the smallest accepted change.\n",
                encoding="utf-8",
            )
            self._write_policy(
                repository,
                test_command,
                {"implementer": [".agents/skills/focused/SKILL.md"]},
            )
            self._git(repository, "add", ".")
            self._git(repository, "commit", "-m", "Initial fixture")

            contract_path = root / "contract.yaml"
            contract_path.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "goal": {
                            "id": "greeting-goal",
                            "title": "Add a greeting",
                            "requirement": "Expose a greeting function for a supplied name.",
                            "acceptance": [
                                {
                                    "id": "AC-1",
                                    "statement": "Greeting includes the supplied name.",
                                }
                            ],
                        },
                        "approval": {
                            "status": "approved",
                            "approved_by": "owner",
                            "approved_at": datetime(
                                2026,
                                7,
                                15,
                                tzinfo=timezone.utc,
                            ),
                        },
                        "agent": {
                            "provider": "claude-code",
                            "model": "sonnet",
                        },
                        "project": {
                            "repo": str(repository),
                            "base_ref": "main",
                        },
                        "todo": {
                            "id": "T-1",
                            "title": "Implement the greeting behavior",
                        },
                        "test": {
                            "command": test_command,
                            "allowed_paths": ["tests/**"],
                        },
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            interrupted_adapter = ScriptedAgentAdapter(interrupt_implementer=True)
            with self.assertRaisesRegex(PlannedInterruption, "simulated host restart"):
                GoalRunner(state_dir=state_dir, agent=interrupted_adapter).run(contract_path)

            self.assertEqual(
                interrupted_adapter.roles,
                ["test_designer", "implementer"],
            )
            self.assertEqual(
                interrupted_adapter.providers,
                ["claude-code", "claude-code"],
            )
            self.assertEqual(interrupted_adapter.models, ["sonnet", "sonnet"])

            resumed_adapter = ScriptedAgentAdapter()
            report = GoalRunner(state_dir=state_dir, agent=resumed_adapter).run(contract_path)

            self.assertEqual(report.status, "merge_ready")
            self.assertEqual(report.goal_id, "greeting-goal")
            self.assertEqual(resumed_adapter.roles, ["implementer", "verifier"])
            self.assertEqual(
                resumed_adapter.providers,
                ["claude-code", "claude-code"],
            )
            self.assertEqual(resumed_adapter.models, ["sonnet", "sonnet"])
            self.assertIn(
                "Prefer the smallest accepted change.",
                resumed_adapter.prompts[0][1],
            )
            self.assertNotIn(
                "Prefer the smallest accepted change.",
                resumed_adapter.prompts[1][1],
            )
            self.assertNotEqual(report.red_commit, report.code_commit)
            self.assertEqual(len(report.todos), 1)
            self.assertEqual(report.todos[0].todo_id, "T-1")
            self.assertEqual(report.todos[0].status, "integrated")
            self.assertEqual(report.todos[0].red_commit, report.red_commit)
            self.assertEqual(report.todos[0].code_commit, report.code_commit)
            self.assertEqual(
                [(item.role, item.status) for item in report.attempts],
                [
                    ("test_designer", "succeeded"),
                    ("implementer", "failed"),
                    ("implementer", "succeeded"),
                    ("verifier", "succeeded"),
                ],
            )
            self.assertTrue(all(item.todo_id == "T-1" for item in report.attempts))
            self.assertTrue(
                all(item.provider == "claude-code" for item in report.attempts)
            )
            self.assertTrue(all(item.model == "sonnet" for item in report.attempts))
            self.assertTrue(all(item.elapsed_seconds >= 0 for item in report.attempts))
            self.assertEqual(report.attempts[1].session_id, "")
            self.assertIn("simulated host restart", report.attempts[1].error)
            self.assertTrue(report.evidence)
            self.assertTrue(
                all(item.duration_seconds >= 0 for item in report.evidence)
            )
            self.assertIsNone(report.attempts[0].usage)
            consumption = report.to_dict()["consumption"]
            self.assertEqual(
                [
                    (item["todo_id"], item["role"], item["attempt_count"])
                    for item in consumption["agents"]
                ],
                [
                    ("T-1", "implementer", 2),
                    ("T-1", "test_designer", 1),
                    ("T-1", "verifier", 1),
                ],
            )
            self.assertEqual(
                {
                    item["role"]: item["usage"]
                    for item in consumption["agents"]
                },
                {
                    "implementer": None,
                    "test_designer": None,
                    "verifier": {"input_tokens": 5},
                },
            )
            self.assertEqual(
                consumption["harnesses"],
                [
                    {
                        "todo_id": "T-1",
                        "profile": "direct-command",
                        "environment": "local",
                        "execution_count": len(report.todos[0].evidence),
                        "duration_seconds": sum(
                            item.duration_seconds
                            for item in report.todos[0].evidence
                        ),
                    }
                ],
            )
            self.assertEqual(
                self._git(repository, "show", f"{report.branch}:greeting.py").stdout,
                "def greeting(name):\n    return f'Hello, {name}!'\n",
            )

            skill.write_text(
                "# Focused work\n\nPrefer a documented, small accepted change.\n",
                encoding="utf-8",
            )
            changed_guidance_adapter = ScriptedAgentAdapter()
            changed_guidance_report = GoalRunner(
                state_dir=state_dir,
                agent=changed_guidance_adapter,
            ).run(contract_path)

            self.assertNotEqual(changed_guidance_report.run_id, report.run_id)
            self.assertIn(
                "Prefer a documented, small accepted change.",
                changed_guidance_adapter.prompts[1][1],
            )

    def test_old_report_without_consumption_fields_remains_readable(self) -> None:
        report = RunReport.from_dict(
            {
                "run_id": "legacy-run",
                "goal_id": "legacy-goal",
                "status": "merge_ready",
                "branch": "aiwb/legacy",
                "worktree": "/tmp/legacy",
                "contract_hash": "abc123",
            }
        )

        self.assertEqual(report.attempts, ())
        self.assertEqual(report.evidence, ())
        self.assertEqual(
            report.to_dict()["consumption"],
            {"agents": [], "harnesses": []},
        )

    @staticmethod
    def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=str(repository),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def _write_policy(repository: Path, command, skills: dict[str, object]) -> None:
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
                            "unit": {"argv": command, "approved": True}
                        },
                        "skills": skills,
                    },
                    "harness": {"profiles": {"local": {"environment": "local"}}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
