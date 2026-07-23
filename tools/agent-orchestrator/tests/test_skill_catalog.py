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
