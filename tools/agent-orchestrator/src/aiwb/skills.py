from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import yaml


_STOP_TERMS = frozenset({"a", "an", "and", "for", "its", "the", "to", "with"})


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str
    source: str
    path: str


@dataclass(frozen=True)
class SkillRecommendation:
    name: str
    description: str
    source: str
    path: str
    reason: str


@dataclass(frozen=True)
class SkillRecommendationResult:
    recommendations: Tuple[SkillRecommendation, ...]


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    skills: Tuple[SkillDescriptor, ...]
    warnings: Tuple[str, ...]


class SkillCatalog:
    """Discover optional Skills and return bounded, advisory recommendations."""

    _BUNDLED = (
        SkillDescriptor(
            name="run-approved-goal",
            description="Submit and observe an approved unattended Goal with Evidence.",
            source="bundled",
            path="skills/run-approved-goal/SKILL.md",
        ),
        SkillDescriptor(
            name="setup-ai-workbench",
            description="Inspect a repository and explicitly configure AI Workbench.",
            source="bundled",
            path="skills/setup-ai-workbench/SKILL.md",
        ),
        SkillDescriptor(
            name="ask-ai-workbench",
            description="Recommend optional Skills for a task without taking action.",
            source="bundled",
            path="skills/ask-ai-workbench/SKILL.md",
        ),
    )

    def recommend(
        self,
        repository: Path,
        task: str,
        limit: int = 2,
    ) -> SkillRecommendationResult:
        repository = Path(repository).expanduser().resolve()
        if not repository.is_dir():
            raise ValueError(f"repository is not a directory: {repository}")
        if not task.strip():
            return SkillRecommendationResult(recommendations=())
        if limit < 1:
            raise ValueError("limit must be positive")

        task_terms = _terms(task)
        ranked = []
        for skill in self.inspect(repository).skills:
            matches = sorted(task_terms & _terms(f"{skill.name} {skill.description}"))
            if len(matches) >= 2:
                ranked.append((len(matches), skill, matches))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return SkillRecommendationResult(
            recommendations=tuple(
                SkillRecommendation(
                    name=skill.name,
                    description=skill.description,
                    source=skill.source,
                    path=skill.path,
                    reason="matched: " + ", ".join(matches),
                )
                for _, skill, matches in ranked[:limit]
            )
        )

    def inspect(self, repository: Path) -> SkillCatalogSnapshot:
        repository = Path(repository).expanduser().resolve()
        if not repository.is_dir():
            raise ValueError(f"repository is not a directory: {repository}")
        skills = list(self._BUNDLED)
        indexes_by_name = {skill.name: index for index, skill in enumerate(skills)}
        warnings = []
        seen_paths = set()
        for root_name in (".agents/skills", ".claude/skills", ".codex/skills", "skills"):
            root = repository / root_name
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("SKILL.md")):
                descriptor = self._project_skill(repository, path)
                relative = path.relative_to(repository).as_posix()
                if descriptor is None:
                    warnings.append(f"ignored invalid Skill: {relative}")
                elif descriptor.path not in seen_paths:
                    seen_paths.add(descriptor.path)
                    existing_index = indexes_by_name.get(descriptor.name)
                    if existing_index is None:
                        indexes_by_name[descriptor.name] = len(skills)
                        skills.append(descriptor)
                    elif skills[existing_index].source == "bundled":
                        skills[existing_index] = descriptor
                    else:
                        warnings.append(f"ignored duplicate Skill name: {relative}")
        return SkillCatalogSnapshot(skills=tuple(skills), warnings=tuple(warnings))

    def bundled_source(self, name: str) -> Path:
        skill = next((item for item in self._BUNDLED if item.name == name), None)
        if skill is None:
            raise ValueError(f"unknown bundled Skill: {name}")
        source = Path(__file__).resolve().parents[2] / skill.path
        if not source.is_file():
            raise ValueError(f"bundled Skill is unavailable: {name}")
        return source

    @staticmethod
    def _project_skill(
        repository: Path,
        path: Path,
    ) -> Optional[SkillDescriptor]:
        try:
            path.resolve().relative_to(repository)
            content = path.read_text(encoding="utf-8")
            metadata = _metadata(content)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            return None
        relative = path.relative_to(repository).as_posix()
        if metadata is None:
            return SkillDescriptor(
                name=path.parent.name,
                description="Project-local optional Skill.",
                source="project",
                path=relative,
            )
        name = metadata.get("name")
        description = metadata.get("description")
        if not isinstance(name, str) or not name or not isinstance(description, str) or not description:
            return None
        return SkillDescriptor(
            name=name,
            description=description,
            source="project",
            path=relative,
        )


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+", value.lower())
        if term not in _STOP_TERMS
    }


def _metadata(content: str) -> Optional[dict[str, object]]:
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated Skill metadata")
    parsed = yaml.safe_load(content[4:end])
    if not isinstance(parsed, dict):
        raise ValueError("Skill metadata must be a mapping")
    return parsed
