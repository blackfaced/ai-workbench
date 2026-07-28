from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import HarnessSetup, HarnessSetupRequest, RecipeCatalog  # noqa: E402
from aiwb.cli import main as cli_main  # noqa: E402


def test_recipe_resolution_prefers_project_then_private_then_bundled() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        private = _write_catalog(
            root / "private.yaml",
            [_recipe(version=2, source="https://docs.pytest.org/en/stable/")],
        )
        project = _write_catalog(
            root / "project.yaml",
            [_recipe(version=3, source="https://docs.pytest.org/en/stable/")],
        )

        catalog = RecipeCatalog(private_catalogs=(private,))

        project_result = catalog.resolve(
            "python-l0-baseline",
            project_catalog=project,
        )
        private_result = catalog.resolve("python-l0-baseline")
        bundled_result = RecipeCatalog().resolve("python-l0-baseline")

        assert (project_result.source, project_result.recipe.version) == (
            "project",
            3,
        )
        assert (private_result.source, private_result.recipe.version) == (
            "private",
            2,
        )
        assert (bundled_result.source, bundled_result.recipe.version) == (
            "bundled",
            1,
        )


def test_same_layer_recipe_conflict_is_explicit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = _write_catalog(root / "first.yaml", [_recipe(version=2)])
        second = _write_catalog(root / "second.yaml", [_recipe(version=3)])

        with pytest.raises(ValueError, match="private Catalog conflict"):
            RecipeCatalog(private_catalogs=(first, second)).resolve(
                "python-l0-baseline"
            )


def test_plan_only_recipe_cannot_authorize_formal_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        project = _write_catalog(
            root / "project.yaml",
            [
                _recipe(
                    version=4,
                    verification_state="plan_only",
                )
            ],
        )
        catalog = RecipeCatalog()

        result = catalog.resolve(
            "python-l0-baseline",
            project_catalog=project,
        )

        assert result.recipe.verification_state == "plan_only"
        with pytest.raises(ValueError, match="cannot authorize formal gates"):
            catalog.require_verified(result)

        unsupported = _write_catalog(
            root / "unsupported.yaml",
            [
                _recipe(
                    version=5,
                    verification_state="unsupported",
                )
            ],
        )
        unsupported_result = catalog.resolve(
            "python-l0-baseline",
            project_catalog=unsupported,
        )
        assert unsupported_result.recipe.verification_state == "unsupported"
        assert unsupported_result.recipe.effective_state == "plan_only"
        assert unsupported_result.recipe.to_dict()["effective_state"] == "plan_only"
        with pytest.raises(ValueError, match="cannot authorize formal gates"):
            catalog.require_verified(unsupported_result)


def test_harness_plan_rejects_project_plan_only_recipe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        project = _write_catalog(
            root / "project.yaml",
            [_recipe(version=2, verification_state="plan_only")],
        )
        setup = HarnessSetup(
            recipe_catalog=RecipeCatalog(),
            project_recipe_catalog=project,
        )

        with pytest.raises(ValueError, match="cannot authorize formal gates"):
            setup.plan(
                HarnessSetupRequest(
                    repository=repository,
                    planning_mode="python-l0",
                )
            )


def test_recipe_audit_reports_stale_and_invalid_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = _write_catalog(
            Path(directory) / "stale.yaml",
            [
                _recipe(
                    version=2,
                    reviewed_at="2024-01-01",
                    source="not-a-url",
                )
            ],
        )

        report = RecipeCatalog().audit(
            catalog_path=path,
            today=date(2026, 7, 28),
        )

        assert report.status == "failed"
        assert {item.code for item in report.findings} == {
            "official_source_invalid",
            "recipe_stale",
        }
        assert report.catalog_digest


def test_refresh_preview_is_reviewable_and_never_mutates_bundled_or_project() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        project_policy = repository / ".ai-workbench" / "workflow.yaml"
        project_policy.parent.mkdir()
        project_policy.write_text("status: approved\n", encoding="utf-8")
        proposed = _write_catalog(
            root / "proposed-public.yaml",
            [
                _recipe(
                    version=2,
                    reviewed_at="2026-07-28",
                    tool_versions={"pytest": "9.1.1", "ruff": "0.12.4"},
                )
            ],
        )
        output = root / "refresh-preview.json"
        before_policy = project_policy.read_bytes()
        bundled = RecipeCatalog().bundled_path
        before_bundled = bundled.read_bytes()

        result = RecipeCatalog().refresh_preview(
            proposed_catalog=proposed,
            output_path=output,
            today=date(2026, 7, 28),
        )

        assert result.status == "review_required"
        assert result.changes == (
            {
                "name": "python-l0-baseline",
                "change": "version_update",
                "from_version": 1,
                "to_version": 2,
            },
        )
        assert result.upgrade_plan == (
            {
                "recipe": "python-l0-baseline",
                "from_version": 1,
                "to_version": 2,
                "tools": {
                    "pytest": {"from": "9.0", "to": "9.1.1"},
                    "ruff": {"from": "0.12.0", "to": "0.12.4"},
                },
            },
        )
        assert json.loads(output.read_text(encoding="utf-8")) == result.to_dict()
        assert bundled.read_bytes() == before_bundled
        assert project_policy.read_bytes() == before_policy
        payload = output.read_text(encoding="utf-8")
        assert str(repository) not in payload
        assert "private" not in payload.lower()


@pytest.mark.parametrize(
    ("version", "expected_code"),
    [
        (1, "recipe_version_not_incremented"),
        (0, "recipe_version_invalid"),
    ],
)
def test_refresh_rejects_unversioned_or_regressive_changes(
    version: int,
    expected_code: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        proposed_recipe = _recipe(
            version=max(version, 1),
            reviewed_at="2026-07-28",
            tool_versions={"pytest": "9.1.1", "ruff": "0.12.0"},
        )
        if version == 0:
            proposed_recipe["version"] = 0
        proposed = _write_catalog(root / "proposed.yaml", [proposed_recipe])
        output = root / "refresh.json"

        result = RecipeCatalog().refresh_preview(
            proposed_catalog=proposed,
            output_path=output,
            today=date(2026, 7, 28),
        )

        assert result.status == "invalid"
        assert expected_code in {
            finding.code for finding in result.validation.findings
        }
        assert result.upgrade_plan == ()


def test_refresh_rejects_removing_a_bundled_recipe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        proposed = _write_catalog(root / "proposed.yaml", [])
        output = root / "refresh.json"

        result = RecipeCatalog().refresh_preview(
            proposed_catalog=proposed,
            output_path=output,
            today=date(2026, 7, 28),
        )

        assert result.status == "invalid"
        assert "recipe_removed" in {
            finding.code for finding in result.validation.findings
        }


def test_recipe_requires_complete_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        recipe = _recipe(version=1)
        recipe["report_formats"] = []
        path = _write_catalog(Path(directory) / "incomplete.yaml", [recipe])

        with pytest.raises(ValueError, match="report_formats"):
            RecipeCatalog().audit(catalog_path=path)


def test_approved_harness_plan_keeps_pinned_recipe_after_refresh() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        setup = HarnessSetup(recipe_catalog=RecipeCatalog())
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        proposed = _write_catalog(
            root / "proposed.yaml",
            [_recipe(version=2, reviewed_at="2026-07-28")],
        )

        RecipeCatalog().refresh_preview(
            proposed_catalog=proposed,
            output_path=root / "refresh.json",
            today=date(2026, 7, 28),
        )

        assert approved.recipe_versions == (("python-l0-baseline", 1),)
        assert json.loads(
            (root / "approved-plan.json").read_text(encoding="utf-8")
        )["recipe_versions"] == [
            {"name": "python-l0-baseline", "version": 1}
        ]


def test_cli_audit_and_refresh_match_catalog_results(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        proposed = _write_catalog(
            root / "proposed.yaml",
            [_recipe(version=2, reviewed_at="2026-07-28")],
        )
        output = root / "refresh.json"

        audit_code = cli_main(["recipes", "audit"])
        audit = json.loads(capsys.readouterr().out)
        refresh_code = cli_main(
            [
                "recipes",
                "refresh",
                "--proposed",
                str(proposed),
                "--output",
                str(output),
            ]
        )
        refresh = json.loads(capsys.readouterr().out)

        assert audit_code == 0
        assert audit["status"] == "ok"
        assert refresh_code == 0
        assert refresh["status"] == "review_required"
        assert refresh == json.loads(output.read_text(encoding="utf-8"))


def test_refresh_skill_routes_to_public_preview_without_private_data() -> None:
    bundled = (
        TOOL_ROOT / "skills" / "refresh-harness-recipes" / "SKILL.md"
    ).read_text(encoding="utf-8")
    project = (
        TOOL_ROOT.parent.parent
        / ".codex"
        / "skills"
        / "refresh-harness-recipes"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert bundled == project
    assert "aiwb recipes audit" in bundled
    assert "aiwb recipes refresh" in bundled
    assert "official sources" in bundled
    assert "private repository" in bundled
    assert "does not mutate" in bundled


def _recipe(
    *,
    version: int,
    reviewed_at: str = "2026-07-01",
    source: str = "https://docs.pytest.org/en/stable/",
    verification_state: str = "verified",
    tool_versions=None,
):
    return {
        "name": "python-l0-baseline",
        "version": version,
        "official_sources": [source],
        "reviewed_at": reviewed_at,
        "applicability": ["language:python", "tier:l0"],
        "alternatives": ["preserve-project-tools"],
        "cost": "low",
        "migration_risk": "low",
        "report_formats": ["junit-xml", "coverage-xml"],
        "verification_state": verification_state,
        "tool_versions": tool_versions
        or {"pytest": "9.0", "ruff": "0.12.0"},
    }


def _write_catalog(path: Path, recipes) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "aiwb.recipe-catalog",
                "recipes": recipes,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _python_repository(root: Path) -> Path:
    repository = root / "project"
    (repository / "tests").mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        "testpaths = ['tests']\n",
        encoding="utf-8",
    )
    return repository
