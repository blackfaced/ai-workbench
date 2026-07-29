from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class Recipe:
    name: str
    version: int
    official_sources: Tuple[str, ...]
    reviewed_at: date
    applicability: Tuple[str, ...]
    alternatives: Tuple[str, ...]
    cost: str
    migration_risk: str
    report_formats: Tuple[str, ...]
    verification_state: str
    tool_versions: Mapping[str, str]

    @property
    def effective_state(self) -> str:
        return (
            "verified"
            if self.verification_state == "verified"
            else "plan_only"
        )

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "official_sources": list(self.official_sources),
            "reviewed_at": self.reviewed_at.isoformat(),
            "applicability": list(self.applicability),
            "alternatives": list(self.alternatives),
            "cost": self.cost,
            "migration_risk": self.migration_risk,
            "report_formats": list(self.report_formats),
            "verification_state": self.verification_state,
            "effective_state": self.effective_state,
            "tool_versions": dict(self.tool_versions),
        }


@dataclass(frozen=True)
class RecipeResolution:
    recipe: Recipe
    source: str
    catalog_path: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "recipe": self.recipe.to_dict(),
            "source": self.source,
            "catalog_path": self.catalog_path,
        }


@dataclass(frozen=True)
class RecipeFinding:
    code: str
    recipe: str
    message: str
    action: str

    def to_dict(self) -> Mapping[str, str]:
        return {
            "code": self.code,
            "recipe": self.recipe,
            "message": self.message,
            "action": self.action,
        }


@dataclass(frozen=True)
class RecipeAudit:
    status: str
    catalog_path: str
    catalog_digest: str
    recipes: Tuple[Recipe, ...]
    findings: Tuple[RecipeFinding, ...]

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "catalog_path": self.catalog_path,
            "catalog_digest": self.catalog_digest,
            "recipes": [recipe.to_dict() for recipe in self.recipes],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class RecipeRefreshPreview:
    status: str
    current_catalog_digest: str
    proposed_catalog_digest: str
    changes: Tuple[Mapping[str, object], ...]
    upgrade_plan: Tuple[Mapping[str, object], ...]
    validation: RecipeAudit
    output_path: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "current_catalog_digest": self.current_catalog_digest,
            "proposed_catalog_digest": self.proposed_catalog_digest,
            "changes": [dict(item) for item in self.changes],
            "upgrade_plan": [dict(item) for item in self.upgrade_plan],
            "validation": self.validation.to_dict(),
            "output_path": self.output_path,
        }

    def artifact_dict(self) -> Mapping[str, object]:
        validation = dict(self.validation.to_dict())
        validation.pop("catalog_path", None)
        return {
            "status": self.status,
            "current_catalog_digest": self.current_catalog_digest,
            "proposed_catalog_digest": self.proposed_catalog_digest,
            "changes": [dict(item) for item in self.changes],
            "upgrade_plan": [dict(item) for item in self.upgrade_plan],
            "validation": validation,
        }


class RecipeCatalog:
    """Resolve layered versioned Recipes and preview source-backed refreshes."""

    def __init__(
        self,
        *,
        private_catalogs: Sequence[Path] = (),
        bundled_path: Optional[Path] = None,
    ) -> None:
        self._private_catalogs = tuple(
            Path(path).expanduser().resolve() for path in private_catalogs
        )
        self._bundled_path = (
            Path(bundled_path).expanduser().resolve()
            if bundled_path is not None
            else Path(__file__).resolve().parent / "recipes" / "public.yaml"
        )

    @property
    def bundled_path(self) -> Path:
        return self._bundled_path

    def resolve(
        self,
        name: str,
        *,
        project_catalog: Optional[Path] = None,
    ) -> RecipeResolution:
        if not name:
            raise ValueError("Recipe name is required")
        if project_catalog is not None:
            path = Path(project_catalog).expanduser().resolve()
            match = _recipe_by_name(_load_catalog(path), name)
            if match is not None:
                _require_valid_version(match)
                return RecipeResolution(match, "project", str(path))
        private_matches = []
        for path in self._private_catalogs:
            match = _recipe_by_name(_load_catalog(path), name)
            if match is not None:
                private_matches.append((path, match))
        if len(private_matches) > 1:
            raise ValueError(f"private Catalog conflict for Recipe: {name}")
        if private_matches:
            path, match = private_matches[0]
            _require_valid_version(match)
            return RecipeResolution(match, "private", str(path))
        match = _recipe_by_name(_load_catalog(self._bundled_path), name)
        if match is None:
            raise ValueError(f"unknown Recipe: {name}")
        _require_valid_version(match)
        return RecipeResolution(match, "bundled", str(self._bundled_path))

    @staticmethod
    def require_verified(resolution: RecipeResolution) -> Recipe:
        if resolution.recipe.verification_state != "verified":
            raise ValueError(
                f"Recipe {resolution.recipe.name!r} cannot authorize formal gates: "
                f"{resolution.recipe.verification_state}"
            )
        return resolution.recipe

    def audit(
        self,
        *,
        catalog_path: Optional[Path] = None,
        today: Optional[date] = None,
    ) -> RecipeAudit:
        path = (
            Path(catalog_path).expanduser().resolve()
            if catalog_path is not None
            else self._bundled_path
        )
        raw = path.read_bytes()
        recipes = _load_catalog(path)
        today = today or date.today()
        findings = []
        for recipe in recipes:
            if recipe.version <= 0:
                findings.append(
                    RecipeFinding(
                        code="recipe_version_invalid",
                        recipe=recipe.name,
                        message="Recipe version must be a positive integer.",
                        action="Assign a positive version before review.",
                    )
                )
            for source in recipe.official_sources:
                parsed = urlparse(source)
                if parsed.scheme != "https" or not parsed.netloc:
                    findings.append(
                        RecipeFinding(
                            code="official_source_invalid",
                            recipe=recipe.name,
                            message=f"Official source is not an HTTPS URL: {source}",
                            action="Replace it with a reviewed official HTTPS source.",
                        )
                    )
            if (today - recipe.reviewed_at).days > 365:
                findings.append(
                    RecipeFinding(
                        code="recipe_stale",
                        recipe=recipe.name,
                        message=(
                            f"Recipe review is stale: {recipe.reviewed_at.isoformat()}."
                        ),
                        action="Review official sources and propose a new Recipe version.",
                    )
                )
        return RecipeAudit(
            status="ok" if not findings else "failed",
            catalog_path=str(path),
            catalog_digest=hashlib.sha256(raw).hexdigest(),
            recipes=recipes,
            findings=tuple(findings),
        )

    def refresh_preview(
        self,
        *,
        proposed_catalog: Path,
        output_path: Path,
        today: Optional[date] = None,
    ) -> RecipeRefreshPreview:
        proposed_catalog = Path(proposed_catalog).expanduser().resolve()
        output_path = Path(output_path).expanduser().resolve()
        if output_path.exists():
            raise ValueError(f"refresh preview output already exists: {output_path}")
        current = self.audit(today=today)
        proposed = self.audit(catalog_path=proposed_catalog, today=today)
        current_by_name = {recipe.name: recipe for recipe in current.recipes}
        proposed_by_name = {recipe.name: recipe for recipe in proposed.recipes}
        changes = []
        upgrades = []
        refresh_findings = list(proposed.findings)
        for name in sorted(set(current_by_name) | set(proposed_by_name)):
            old = current_by_name.get(name)
            new = proposed_by_name.get(name)
            if old is None and new is not None:
                changes.append(
                    {
                        "name": name,
                        "change": "added",
                        "from_version": None,
                        "to_version": new.version,
                    }
                )
                continue
            if new is None and old is not None:
                changes.append(
                    {
                        "name": name,
                        "change": "removed",
                        "from_version": old.version,
                        "to_version": None,
                    }
                )
                refresh_findings.append(
                    RecipeFinding(
                        code="recipe_removed",
                        recipe=name,
                        message="A bundled public Recipe was removed.",
                        action=(
                            "Keep the Recipe and mark it unsupported in a new "
                            "version instead of removing its audit history."
                        ),
                    )
                )
                continue
            assert old is not None and new is not None
            if old.to_dict() == new.to_dict():
                continue
            change = (
                "version_update"
                if old.version != new.version
                else "metadata_changed_without_version"
            )
            if new.version == old.version:
                refresh_findings.append(
                    RecipeFinding(
                        code="recipe_version_not_incremented",
                        recipe=name,
                        message="Recipe metadata changed without a version increment.",
                        action="Increment the Recipe version and review the upgrade plan.",
                    )
                )
            elif new.version < old.version:
                refresh_findings.append(
                    RecipeFinding(
                        code="recipe_version_regressed",
                        recipe=name,
                        message=(
                            f"Recipe version regressed from {old.version} to {new.version}."
                        ),
                        action="Use a version greater than the current bundled Recipe.",
                    )
                )
            changes.append(
                {
                    "name": name,
                    "change": change,
                    "from_version": old.version,
                    "to_version": new.version,
                }
            )
            if new.version > old.version:
                tools = {
                    tool: {"from": old.tool_versions.get(tool), "to": version}
                    for tool, version in sorted(new.tool_versions.items())
                    if old.tool_versions.get(tool) != version
                }
                upgrades.append(
                    {
                        "recipe": name,
                        "from_version": old.version,
                        "to_version": new.version,
                        "tools": tools,
                    }
                )
        proposed = RecipeAudit(
            status="ok" if not refresh_findings else "failed",
            catalog_path=proposed.catalog_path,
            catalog_digest=proposed.catalog_digest,
            recipes=proposed.recipes,
            findings=tuple(refresh_findings),
        )
        result = RecipeRefreshPreview(
            status=(
                "review_required"
                if proposed.status == "ok" and changes
                else "invalid"
                if proposed.status != "ok"
                else "unchanged"
            ),
            current_catalog_digest=current.catalog_digest,
            proposed_catalog_digest=proposed.catalog_digest,
            changes=tuple(changes),
            upgrade_plan=tuple(upgrades),
            validation=proposed,
            output_path=str(output_path),
        )
        _write_json_atomically(output_path, result.artifact_dict())
        return result


def _load_catalog(path: Path) -> Tuple[Recipe, ...]:
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read Recipe Catalog {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("Recipe Catalog must be a mapping")
    if value.get("schema_version") != 1:
        raise ValueError("Recipe Catalog schema_version must be 1")
    if value.get("kind") != "aiwb.recipe-catalog":
        raise ValueError("Recipe Catalog kind must be aiwb.recipe-catalog")
    items = value.get("recipes")
    if not isinstance(items, list):
        raise ValueError("Recipe Catalog recipes must be a list")
    recipes = tuple(_parse_recipe(item) for item in items)
    names = [recipe.name for recipe in recipes]
    if len(names) != len(set(names)):
        raise ValueError("Recipe Catalog contains duplicate Recipe names")
    return recipes


def _parse_recipe(value: object) -> Recipe:
    if not isinstance(value, dict):
        raise ValueError("Recipe must be a mapping")
    name = _text(value, "name")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"Recipe {name!r} version must be an integer")
    reviewed_at = _text(value, "reviewed_at")
    try:
        reviewed_date = date.fromisoformat(reviewed_at)
    except ValueError as error:
        raise ValueError(f"Recipe {name!r} reviewed_at must be an ISO date") from error
    verification_state = _text(value, "verification_state")
    if verification_state not in {"verified", "plan_only", "unsupported"}:
        raise ValueError(
            f"Recipe {name!r} verification_state is unsupported: {verification_state}"
        )
    tool_versions = value.get("tool_versions")
    if not isinstance(tool_versions, dict) or not all(
        isinstance(key, str)
        and key
        and isinstance(item, str)
        and item
        for key, item in tool_versions.items()
    ):
        raise ValueError(f"Recipe {name!r} tool_versions must be a string mapping")
    return Recipe(
        name=name,
        version=version,
        official_sources=_strings(value, "official_sources"),
        reviewed_at=reviewed_date,
        applicability=_strings(value, "applicability"),
        alternatives=_strings(value, "alternatives"),
        cost=_text(value, "cost"),
        migration_risk=_text(value, "migration_risk"),
        report_formats=_strings(value, "report_formats"),
        verification_state=verification_state,
        tool_versions={str(key): str(item) for key, item in tool_versions.items()},
    )


def _recipe_by_name(
    recipes: Sequence[Recipe],
    name: str,
) -> Optional[Recipe]:
    return next((recipe for recipe in recipes if recipe.name == name), None)


def _require_valid_version(recipe: Recipe) -> None:
    if recipe.version <= 0:
        raise ValueError(
            f"Recipe {recipe.name!r} version must be a positive integer"
        )


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Recipe {key} must be a non-empty string")
    return item


def _strings(value: Mapping[str, object], key: str) -> Tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not items or not all(
        isinstance(item, str) and item for item in items
    ):
        raise ValueError(f"Recipe {key} must be a non-empty string list")
    return tuple(items)


def _write_json_atomically(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
