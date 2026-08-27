from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

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


@dataclass(frozen=True)
class SkillPackDescriptor:
    name: str
    description: str
    source: str
    revision: str
    installable: bool
    setup_action: str = ""
    profiles: Tuple["SkillPackProfileDescriptor", ...] = ()


@dataclass(frozen=True)
class SkillPackProfileDescriptor:
    """A reviewed, named selection from an optional upstream Skill pack."""

    name: str
    description: str
    skills: Tuple[str, ...]


@dataclass(frozen=True)
class SkillPackInstallPlan:
    name: str
    command: Tuple[str, ...]
    setup_action: str = ""


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
            name="draft-aiwb-contract",
            description="Create an unapproved Contract draft from approved local tickets.",
            source="bundled",
            path="skills/draft-aiwb-contract/SKILL.md",
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
        SkillDescriptor(
            name="intake-aiwb-goal",
            description=(
                "Inspect ticket or draft handoff readiness and the cheapest viable path."
            ),
            source="bundled",
            path="skills/intake-aiwb-goal/SKILL.md",
        ),
        SkillDescriptor(
            name="refresh-harness-recipes",
            description=(
                "Audit and preview source-backed public Harness Recipe refreshes."
            ),
            source="bundled",
            path="skills/refresh-harness-recipes/SKILL.md",
        ),
        SkillDescriptor(
            name="engineering-principles",
            description=(
                "Apply simple, surgical, verifiable engineering principles and "
                "stop when the requested work is complete."
            ),
            source="bundled",
            path="skills/engineering-principles/SKILL.md",
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

        snapshot = self.inspect(repository)
        task_terms = _terms(task)
        ranked = []
        for skill in snapshot.skills:
            if skill.name == "intake-aiwb-goal" and not _is_intake_task(task_terms):
                continue
            matches = sorted(task_terms & _terms(f"{skill.name} {skill.description}"))
            if len(matches) >= 2:
                ranked.append((len(matches), skill, matches))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        router = next(
            (skill for skill in snapshot.skills if skill.name == "ask-matt"),
            None,
        )
        recommendations = []
        if router is not None and not _is_aiwb_task(task_terms):
            recommendations.append(
                SkillRecommendation(
                    name=router.name,
                    description=router.description,
                    source=router.source,
                    path=router.path,
                    reason="installed upstream engineering router",
                )
            )
        recommendations.extend(
            SkillRecommendation(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                path=skill.path,
                reason="matched: " + ", ".join(matches),
            )
            for _, skill, matches in ranked
            if skill.name != "ask-matt"
        )
        return SkillRecommendationResult(
            recommendations=tuple(recommendations[:limit])
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


def _is_aiwb_task(task_terms: set[str]) -> bool:
    return bool(
        task_terms
        & {
            "aiwb",
            "approved",
            "candidate",
            "contract",
            "daemon",
            "evidence",
            "goal",
            "harness",
            "unattended",
        }
    )


def _is_intake_task(task_terms: set[str]) -> bool:
    return bool(
        task_terms
        & {
            "cheapest",
            "draft",
            "handoff",
            "intake",
            "readiness",
            "tickets",
        }
    )


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


class SkillPackCatalog:
    """Describe vetted optional packs and render their project-local install commands."""

    _PACKS = (
        SkillPackDescriptor(
            name="matt",
            description="Selected small engineering Skills from mattpocock/skills.",
            source=(
                "https://github.com/mattpocock/skills/tree/"
                "v1.2.3"
            ),
            revision=(
                "v1.2.3 (resolved 6acc160e4e0cd062dbbbd7a1b26ae92855edf07e)"
            ),
            installable=True,
            setup_action="$setup-matt-pocock-skills",
            profiles=(
                SkillPackProfileDescriptor(
                    name="engineering",
                    description=(
                        "Dependency-complete ask-matt engineering flow; excludes "
                        "deprecated, in-progress, personal, and unrelated upstream Skills."
                    ),
                    skills=(
                        "setup-matt-pocock-skills",
                        "ask-matt",
                        "grill-with-docs",
                        "grill-me",
                        "grilling",
                        "handoff",
                        "prototype",
                        "to-spec",
                        "to-tickets",
                        "implement",
                        "tdd",
                        "code-review",
                        "codebase-design",
                        "domain-modeling",
                        "improve-codebase-architecture",
                        "triage",
                        "diagnosing-bugs",
                        "wayfinder",
                        "research",
                        "resolving-merge-conflicts",
                        "teach",
                        "to-questionnaire",
                        "wizard",
                        "wait-what",
                        "writing-for-agents",
                    ),
                ),
            ),
        ),
        SkillPackDescriptor(
            name="ponytail",
            description="On-demand review for unnecessary implementation complexity.",
            source=(
                "https://github.com/DietrichGebert/ponytail/tree/"
                "v4.9.0"
            ),
            revision=(
                "v4.9.0 (resolved 0a4dd63ad4541f4f655c4108a295916f3c1d8fda)"
            ),
            installable=True,
            profiles=(
                SkillPackProfileDescriptor(
                    name="review",
                    description=(
                        "Review-only delete list for over-engineering; excludes the "
                        "always-on Ponytail mode and Caveman."
                    ),
                    skills=("ponytail-review",),
                ),
            ),
        ),
        SkillPackDescriptor(
            name="anthropic",
            description="Reference-only Skill design collection; not installable yet.",
            source="https://github.com/anthropics/skills",
            revision="",
            installable=False,
        ),
    )

    def inspect(self) -> Tuple[SkillPackDescriptor, ...]:
        return self._PACKS

    def plans(
        self,
        selections: Mapping[str, Sequence[str]],
        agent_targets: Tuple[str, ...],
        profiles: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> Tuple[SkillPackInstallPlan, ...]:
        plans = []
        descriptors = {pack.name: pack for pack in self._PACKS}
        profile_selections = profiles or {}
        pack_names = tuple(dict.fromkeys((*selections.keys(), *profile_selections.keys())))
        for name in pack_names:
            pack = descriptors.get(name)
            if pack is None:
                raise ValueError(f"unknown Skill pack: {name}")
            if not pack.installable:
                raise ValueError(f"Skill pack is reference-only: {name}")
            profiles_by_name = {profile.name: profile for profile in pack.profiles}
            profile_skills = []
            for profile_name in profile_selections.get(name, ()):
                profile = profiles_by_name.get(profile_name)
                if profile is None:
                    raise ValueError(f"unknown Skill pack profile: {name}={profile_name}")
                profile_skills.extend(profile.skills)
            skills = tuple(
                dict.fromkeys((*profile_skills, *selections.get(name, ())))
            )
            if not skills:
                raise ValueError(f"Skill pack requires selected Skills: {name}")
            if any(not re.fullmatch(r"[a-z0-9-]+", skill) for skill in skills):
                raise ValueError(f"invalid Skill name for pack {name}")
            for target in agent_targets:
                plans.append(
                    SkillPackInstallPlan(
                        name=name,
                        command=(
                            "npx",
                            "--yes",
                            "skills@1.5.9",
                            "add",
                            pack.source,
                            "--copy",
                            "--yes",
                            "--agent",
                            target,
                            *(argument for skill in skills for argument in ("--skill", skill)),
                        ),
                        setup_action=pack.setup_action,
                    )
                )
        return tuple(plans)
