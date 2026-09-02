from __future__ import annotations

import tempfile
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb.skills import SkillCatalog  # noqa: E402


def test_catalog_recommends_a_bundled_skill_without_mutating_the_repository() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        marker = repository / "keep.txt"
        marker.write_text("unchanged\n", encoding="utf-8")

        result = SkillCatalog().recommend(
            repository,
            "submit an approved unattended goal and inspect its evidence",
        )

        assert [item.name for item in result.recommendations] == [
            "run-approved-goal",
        ]
        assert marker.read_text(encoding="utf-8") == "unchanged\n"
        assert list(repository.iterdir()) == [marker]


def test_catalog_distinguishes_project_local_skills_and_ignores_invalid_entries() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        valid = repository / ".agents" / "skills" / "release-notes" / "SKILL.md"
        valid.parent.mkdir(parents=True)
        valid.write_text(
            "---\nname: release-notes\ndescription: Draft concise release notes.\n---\n",
            encoding="utf-8",
        )
        invalid = repository / "skills" / "broken" / "SKILL.md"
        invalid.parent.mkdir(parents=True)
        invalid.write_text("---\nname: [not valid\n", encoding="utf-8")

        snapshot = SkillCatalog().inspect(repository)

        local = next(item for item in snapshot.skills if item.name == "release-notes")
        assert local.source == "project"
        assert local.path == ".agents/skills/release-notes/SKILL.md"
        assert snapshot.warnings == ("ignored invalid Skill: skills/broken/SKILL.md",)


def test_catalog_prefers_a_project_copy_of_a_bundled_skill() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        copied = repository / ".codex" / "skills" / "ask-ai-workbench" / "SKILL.md"
        copied.parent.mkdir(parents=True)
        copied.write_text(
            "---\n"
            "name: ask-ai-workbench\n"
            "description: Recommend optional Skills for a task without action.\n"
            "---\n",
            encoding="utf-8",
        )

        snapshot = SkillCatalog().inspect(repository)
        result = SkillCatalog().recommend(
            repository,
            "recommend optional skills for this workbench task",
        )

        matching = [skill for skill in snapshot.skills if skill.name == "ask-ai-workbench"]
        assert [(skill.source, skill.path) for skill in matching] == [
            ("project", ".codex/skills/ask-ai-workbench/SKILL.md"),
        ]
        assert [item.name for item in result.recommendations] == ["ask-ai-workbench"]


def test_catalog_routes_draft_readiness_to_goal_intake() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()

        result = SkillCatalog().recommend(
            repository,
            "inspect draft contract readiness and cheapest handoff",
        )

        assert result.recommendations[0].name == "intake-aiwb-goal"


def test_catalog_recommends_installed_ask_matt_before_recreating_its_router() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        router = repository / ".codex" / "skills" / "ask-matt" / "SKILL.md"
        router.parent.mkdir(parents=True)
        router.write_text(
            "---\n"
            "name: ask-matt\n"
            "description: Ask which skill or flow fits your situation.\n"
            "---\n",
            encoding="utf-8",
        )

        result = SkillCatalog().recommend(
            repository,
            "design and implement a multi-session engineering feature",
        )

        assert [item.name for item in result.recommendations] == ["ask-matt"]
        assert result.recommendations[0].reason == "installed upstream engineering router"


def test_project_local_skill_mirrors_match_the_bundled_sources() -> None:
    repository = TOOL_ROOT.parents[1]
    for name in (
        "ask-ai-workbench",
        "setup-ai-workbench",
        "intake-aiwb-goal",
    ):
        bundled = TOOL_ROOT / "skills" / name / "SKILL.md"
        mirrored = repository / ".codex" / "skills" / name / "SKILL.md"
        assert mirrored.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8")


def test_intake_skill_does_not_route_to_removed_ticket_or_handoff_commands() -> None:
    content = (
        TOOL_ROOT / "skills" / "intake-aiwb-goal" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "--tickets" not in content
    assert "--handoff" not in content
    assert "goal bridge" not in content


def test_setup_skill_install_example_names_the_agent_target() -> None:
    repository = TOOL_ROOT.parents[1]
    expected = (
        "aiwb setup --repo /path/to/repository --agent-target codex --apply \\\n"
        "  --install-skill ask-ai-workbench"
    )
    for path in (
        TOOL_ROOT / "skills" / "setup-ai-workbench" / "SKILL.md",
        repository / ".codex" / "skills" / "setup-ai-workbench" / "SKILL.md",
    ):
        assert expected in path.read_text(encoding="utf-8")


def test_setup_skill_documents_fail_closed_non_skill_extension_install() -> None:
    repository = TOOL_ROOT.parents[1]
    for path in (
        TOOL_ROOT / "skills" / "setup-ai-workbench" / "SKILL.md",
        repository / ".codex" / "skills" / "setup-ai-workbench" / "SKILL.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert "--install-extension" in content
        assert "configuration.harness_probe" in content
        assert "without a shell and with a bounded timeout" in content
        assert "Setup fails before writing" in content
