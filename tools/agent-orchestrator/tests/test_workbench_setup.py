from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb.setup import WorkbenchSetup  # noqa: E402


def test_setup_inspects_a_repository_without_creating_a_workflow() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        (repository / "tests").mkdir()
        (repository / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\n",
            encoding="utf-8",
        )

        result = WorkbenchSetup().inspect(
            repository,
            agent_targets=("codex", "claude-code"),
        )

        assert result.workflow_action == "create_draft"
        assert result.agent_targets == ("codex", "claude-code")
        assert result.suggestions == 1
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_setup_requires_confirmation_and_idempotently_configures_role_guidance() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        skill = repository / ".agents" / "skills" / "focused" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# Focused\n", encoding="utf-8")
        setup = WorkbenchSetup()

        with pytest.raises(ValueError, match="explicit confirmation"):
            setup.apply(
                repository,
                confirmed=False,
                role_skills={"implementer": (".agents/skills/focused/SKILL.md",)},
            )
        workflow = repository / ".ai-workbench" / "workflow.yaml"
        assert not workflow.exists()

        first = setup.apply(
            repository,
            confirmed=True,
            role_skills={"implementer": (".agents/skills/focused/SKILL.md",)},
        )
        first_document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        second = setup.apply(
            repository,
            confirmed=True,
            role_skills={"implementer": (".agents/skills/focused/SKILL.md",)},
        )

        assert first.changed is True
        assert second.changed is False
        assert first_document["capabilities"]["skills"] == {
            "implementer": [".agents/skills/focused/SKILL.md"],
        }


def test_setup_installs_an_explicit_bundled_skill_into_a_selected_project_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        setup = WorkbenchSetup()

        first = setup.apply(
            repository,
            confirmed=True,
            agent_targets=("codex",),
            install_skills=("ask-ai-workbench",),
        )
        installed = repository / ".codex" / "skills" / "ask-ai-workbench" / "SKILL.md"
        second = setup.apply(
            repository,
            confirmed=True,
            agent_targets=("codex",),
            install_skills=("ask-ai-workbench",),
        )

        assert installed.is_file()
        assert "Ask AI Workbench" in installed.read_text(encoding="utf-8")
        assert first.changed is True
        assert second.changed is False


def test_setup_rejects_a_skill_target_that_escapes_the_repository() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        outside = root / "outside"
        outside.mkdir()
        (repository / ".codex").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="must remain inside the repository"):
            WorkbenchSetup().apply(
                repository,
                confirmed=True,
                agent_targets=("codex",),
                install_skills=("ask-ai-workbench",),
            )

        assert list(outside.iterdir()) == []


def test_setup_installs_selected_matt_skills_with_a_project_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        calls = []

        def run(command: tuple[str, ...], cwd: Path) -> None:
            calls.append((command, cwd))

        result = WorkbenchSetup(command_runner=run).apply(
            repository,
            confirmed=True,
            agent_targets=("codex",),
            pack_skills={
                "matt": ("ask-matt", "setup-matt-pocock-skills"),
            },
        )

        assert result.installed_packs == ("matt",)
        assert result.next_actions == ("$setup-matt-pocock-skills",)
        assert calls == [
            (
                (
                    "npx",
                    "--yes",
                    "skills@1.5.9",
                    "add",
                    "https://github.com/mattpocock/skills/tree/d574778f94cf620fcc8ce741584093bc650a61d3",
                    "--copy",
                    "--yes",
                    "--agent",
                    "codex",
                    "--skill",
                    "ask-matt",
                    "--skill",
                    "setup-matt-pocock-skills",
                ),
                repository.resolve(),
            )
        ]


def test_setup_installs_the_reviewed_matt_engineering_profile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        calls = []

        result = WorkbenchSetup(command_runner=lambda command, cwd: calls.append((command, cwd))).apply(
            repository,
            confirmed=True,
            agent_targets=("codex",),
            pack_profiles={"matt": ("engineering",)},
        )

        command, cwd = calls[0]
        selected = tuple(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "--skill"
        )
        assert result.installed_packs == ("matt",)
        assert cwd == repository.resolve()
        assert command[4] == "https://github.com/mattpocock/skills/tree/d574778f94cf620fcc8ce741584093bc650a61d3"
        assert selected[:4] == (
            "setup-matt-pocock-skills",
            "ask-matt",
            "grill-with-docs",
            "grill-me",
        )
        assert "to-spec" in selected
        assert "to-tickets" in selected
        assert "tdd" in selected
        assert "improve-codebase-architecture" in selected


def test_setup_keeps_reference_only_packs_uninstallable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        calls = []

        with pytest.raises(ValueError, match="reference-only: anthropic"):
            WorkbenchSetup(command_runner=lambda command, cwd: calls.append(command)).apply(
                repository,
                confirmed=True,
                agent_targets=("codex",),
                pack_skills={"anthropic": ("anything",)},
            )

        assert calls == []
