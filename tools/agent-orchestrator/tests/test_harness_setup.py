from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import json
import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    HarnessApplyRequest,
    CodeStructureEvidence,
    ExternalAnalysisEvidence,
    HarnessSetup,
    HarnessSetupRequest,
    HarnessVerifyRequest,
    ProjectInitError,
)
from aiwb.cli import main as cli_main  # noqa: E402
from aiwb.mcp_server import McpServer  # noqa: E402


def test_harness_setup_inspect_and_plan_are_read_only() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        marker = root / "script-was-executed"
        (repository / "tests").mkdir(parents=True)
        scripts = repository / "scripts"
        scripts.mkdir()
        script = scripts / "e2e-local.sh"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        script.chmod(0o755)

        setup = HarnessSetup()
        request = HarnessSetupRequest(
            repository=repository,
            agent_targets=("codex",),
        )

        assessment = setup.inspect(request)
        plan = setup.plan(request)

        assert assessment.state == "assessed"
        assert assessment.repository == str(repository.resolve())
        assert assessment.workflow_action == "create_draft"
        assert assessment.suggestions == 2
        assert plan.state == "planned"
        assert plan.assessment == assessment
        assert plan.request == request
        assert not marker.exists()
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_harness_setup_plans_a_python_l0_profile_from_repository_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        (repository / "src" / "sample").mkdir(parents=True)
        (repository / "tests").mkdir()
        (repository / ".github" / "workflows").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[build-system]\n"
            "requires = ['setuptools>=68']\n"
            "build-backend = 'setuptools.build_meta'\n\n"
            "[project]\n"
            "name = 'sample'\n"
            "dependencies = []\n\n"
            "[project.optional-dependencies]\n"
            "test = ['pytest>=8', 'pytest-cov>=5', 'ruff==0.12.4']\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n\n"
            "[tool.ruff]\n"
            "line-length = 88\n",
            encoding="utf-8",
        )
        (repository / ".github" / "workflows" / "test.yml").write_text(
            "name: test\non: [push]\n",
            encoding="utf-8",
        )
        marker = root / "command-was-executed"
        script = repository / "test.sh"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        script.chmod(0o755)
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(repository),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=str(repository),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=AIWB",
                "-c",
                "user.email=aiwb@example.test",
                "commit",
                "-m",
                "Initial fixture",
            ],
            cwd=str(repository),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        before = _tree(repository)
        setup = HarnessSetup()
        request = HarnessSetupRequest(
            repository=repository,
            planning_mode="python-l0",
        )

        assessment = setup.inspect(request)
        plan = setup.plan(request)

        profile = assessment.project_profile
        assert profile is not None
        assert profile.targets[0].language == "python"
        assert set(profile.targets[0].purpose_tags) == {"library", "test"}
        capabilities = {
            capability.name: capability
            for capability in profile.targets[0].capabilities
        }
        assert capabilities["unit"].disposition == "keep"
        assert capabilities["lint"].disposition == "keep"
        assert capabilities["coverage"].disposition == "augment"
        assert capabilities["typecheck"].disposition == "adopt"
        assert capabilities["unit"].confidence == "high"
        assert profile.build_system == "setuptools.build_meta"
        assert profile.pipeline_files == (".github/workflows/test.yml",)
        assert {item.name for item in profile.unavailable_evidence} == {
            "code_graph",
            "remote_review_history",
        }
        assert profile.code_structure.provider == "filesystem"
        assert profile.code_structure.confidence == "medium"
        assert plan.command_candidates
        assert plan.recipe_versions == (("python-l0-baseline", 1),)
        assert plan.coverage_decision == "measure_baseline_before_threshold"
        assert plan.owner_decisions
        assert "business tests" in " ".join(plan.non_goals).lower()
        assert plan.approval.status == "unapproved"
        assert _tree(repository) == before
        assert not marker.exists()


def test_python_l0_prefers_available_code_graph_and_review_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        (repository / "src" / "sample").mkdir(parents=True)
        (repository / "tests").mkdir()
        (repository / "pyproject.toml").write_text(
            "[build-system]\n"
            "requires = ['setuptools>=68']\n"
            "build-backend = 'setuptools.build_meta'\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
            encoding="utf-8",
        )

        calls = []

        def analyze(path: Path) -> ExternalAnalysisEvidence:
            calls.append(path)
            return ExternalAnalysisEvidence(
                code_structure=CodeStructureEvidence(
                    provider="codebase-memory",
                    confidence="high",
                    source_roots=("src/sample",),
                    test_roots=("tests",),
                ),
                remote_review_history=("PR #7: preserve pytest",),
            )

        profile = HarnessSetup(analysis_provider=analyze).inspect(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        ).project_profile

        assert profile is not None
        assert calls == [repository.resolve()]
        assert profile.code_structure.provider == "codebase-memory"
        assert profile.code_structure.confidence == "high"
        assert profile.remote_review_history == ("PR #7: preserve pytest",)
        assert {
            item.name for item in profile.unavailable_evidence
        } == {"local_git_history"}


def test_python_l0_reports_analysis_provider_failure_and_falls_back() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            encoding="utf-8",
        )

        def unavailable(_: Path) -> ExternalAnalysisEvidence:
            raise RuntimeError("analysis provider unavailable")

        profile = HarnessSetup(analysis_provider=unavailable).inspect(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        ).project_profile

        assert profile is not None
        assert profile.code_structure.provider == "filesystem"
        assert profile.code_structure.confidence == "medium"
        code_graph = next(
            item
            for item in profile.unavailable_evidence
            if item.name == "code_graph"
        )
        assert code_graph.status == "unavailable"
        assert "analysis provider unavailable" in code_graph.detail


def test_python_l0_preserves_existing_tools_and_defers_migration() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[project]\n"
            "name = 'sample'\n\n"
            "[project.optional-dependencies]\n"
            "test = ['pytest>=8', 'ruff==0.12.4', 'black==25.1', 'flake8==7.3']\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
            encoding="utf-8",
        )

        profile = HarnessSetup().inspect(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        ).project_profile

        assert profile is not None
        capabilities = {
            capability.name: capability
            for capability in profile.targets[0].capabilities
        }
        assert capabilities["lint"].disposition == "keep"
        assert capabilities["lint"].command[-2:] == ("flake8", ".")
        assert capabilities["format"].disposition == "keep"
        assert capabilities["format"].command[-3:] == ("black", "--check", ".")
        assert capabilities["ruff_lint_migration"].disposition == "migrate_later"
        assert capabilities["ruff_format_migration"].disposition == "migrate_later"


def test_python_l0_command_candidates_include_nested_target_working_directory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "repository"
        target = repository / "tools" / "python-app"
        (target / "tests").mkdir(parents=True)
        (target / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            encoding="utf-8",
        )

        plan = HarnessSetup().plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )

        unit = next(
            candidate
            for candidate in plan.command_candidates
            if candidate.name == "tools/python-app:unit"
        )
        assert unit.working_directory == "tools/python-app"
        assert unit.to_dict()["working_directory"] == "tools/python-app"


def test_python_l0_ignores_generated_and_dependency_directories() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "repository"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            encoding="utf-8",
        )
        for generated in (".venv", "venv", "node_modules", "build", "dist"):
            target = repository / generated / "dependency"
            target.mkdir(parents=True)
            (target / "pyproject.toml").write_text(
                "[project]\nname = 'dependency'\n",
                encoding="utf-8",
            )

        profile = HarnessSetup().inspect(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        ).project_profile

        assert profile is not None
        assert tuple(target.path for target in profile.targets) == (".",)


def test_python_l0_plan_approval_is_durable_but_does_not_authorize_apply() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[build-system]\n"
            "requires = ['setuptools>=68']\n"
            "build-backend = 'setuptools.build_meta'\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
            encoding="utf-8",
        )
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        artifact = root / "artifacts" / "approved-plan.json"

        approved = setup.approve_plan(
            plan,
            approved_by="owner",
            approved_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            artifact_path=artifact,
        )

        assert approved.approval.status == "approved"
        assert approved.approval.approved_by == "owner"
        assert approved.approval.artifact_path == str(artifact.resolve())
        stored = json.loads(artifact.read_text(encoding="utf-8"))
        assert stored == approved.to_dict()
        with pytest.raises(ValueError, match="does not authorize Apply"):
            setup.apply(HarnessApplyRequest(plan=approved, confirmed=True))

        inside_repository = repository / "approved-plan.json"
        with pytest.raises(ValueError, match="outside the target repository"):
            setup.approve_plan(
                plan,
                approved_by="owner",
                artifact_path=inside_repository,
            )
        assert not inside_repository.exists()


def test_python_l0_cli_and_mcp_return_the_same_unapproved_plan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[build-system]\n"
            "requires = ['setuptools>=68']\n"
            "build-backend = 'setuptools.build_meta'\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
            encoding="utf-8",
        )

        returncode = cli_main(
            [
                "setup",
                "--repo",
                str(repository),
                "--planning-mode",
                "python-l0",
            ]
        )
        cli_value = json.loads(capsys.readouterr().out)
        mcp_result = McpServer(Path(directory) / "missing.sock")._call_tool(
            "aiwb_harness_plan",
            {
                "repository": str(repository),
                "planning_mode": "python-l0",
            },
        )
        mcp_value = json.loads(mcp_result["content"][0]["text"])

        assert returncode == 0
        assert mcp_result["isError"] is False
        assert cli_value == mcp_value
        assert cli_value["approval"]["status"] == "unapproved"
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_python_l0_cli_records_explicit_plan_approval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        (repository / "tests").mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            "[build-system]\n"
            "requires = ['setuptools>=68']\n"
            "build-backend = 'setuptools.build_meta'\n\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
            encoding="utf-8",
        )
        artifact = root / "approved-plan.json"

        returncode = cli_main(
            [
                "setup",
                "--repo",
                str(repository),
                "--planning-mode",
                "python-l0",
                "--approve-plan",
                "--approved-by",
                "owner",
                "--plan-artifact",
                str(artifact),
            ]
        )
        value = json.loads(capsys.readouterr().out)

        assert returncode == 0
        assert value["approval"]["status"] == "approved"
        assert value["approval"]["approved_by"] == "owner"
        assert value["approval"]["artifact_path"] == str(artifact.resolve())
        assert json.loads(artifact.read_text(encoding="utf-8")) == value
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_harness_setup_apply_requires_a_planned_explicitly_confirmed_request() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        setup = HarnessSetup()
        plan = setup.plan(HarnessSetupRequest(repository=repository))

        with pytest.raises(ValueError, match="planned Harness Plan"):
            setup.apply(
                HarnessApplyRequest(
                    plan=replace(plan, state="draft"),
                    confirmed=True,
                )
            )
        with pytest.raises(ValueError, match="explicit confirmation"):
            setup.apply(HarnessApplyRequest(plan=plan, confirmed=False))

        candidate = setup.apply(HarnessApplyRequest(plan=plan, confirmed=True))

        workflow = repository / ".ai-workbench" / "workflow.yaml"
        assert candidate.state == "candidate"
        assert Path(candidate.workflow_path) == workflow.resolve()
        assert candidate.workflow_action == "created"
        assert candidate.changed is True
        assert workflow.is_file()


def test_harness_setup_initialization_preserves_output_and_force_semantics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        output = repository / "config" / "workflow.yaml"
        setup = HarnessSetup()
        request = HarnessSetupRequest(
            repository=repository,
            operation="initialize",
            output_path=output,
        )

        plan = setup.plan(request)
        candidate = setup.apply(
            HarnessApplyRequest(plan=plan, confirmed=True)
        )

        assert plan.assessment.workflow_path == str(output.resolve())
        assert candidate.state == "candidate"
        assert candidate.status == "draft"
        assert candidate.suggestions == 0
        assert candidate.workflow_action == "created"
        with pytest.raises(ValueError, match="stale"):
            setup.apply(HarnessApplyRequest(plan=plan, confirmed=True))

        new_output = repository / "config" / "forced-new-workflow.yaml"
        forced_new_plan = setup.plan(
            replace(request, output_path=new_output)
        )
        forced_new = setup.apply(
            HarnessApplyRequest(plan=forced_new_plan, confirmed=True, force=True)
        )
        assert forced_new.workflow_action == "created"

        existing_plan = setup.plan(request)
        with pytest.raises(ProjectInitError, match="already exists"):
            setup.apply(HarnessApplyRequest(plan=existing_plan, confirmed=True))

        replacement_plan = setup.plan(request)
        replaced = setup.apply(
            HarnessApplyRequest(plan=replacement_plan, confirmed=True, force=True)
        )
        assert replaced.workflow_action == "replaced"
        assert replaced.changed is True


def test_harness_setup_rejects_a_tampered_or_stale_assessment_before_writing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        setup = HarnessSetup()
        plan = setup.plan(HarnessSetupRequest(repository=repository))
        outside = root / "outside" / "workflow.yaml"
        tampered = replace(
            plan,
            assessment=replace(
                plan.assessment,
                workflow_path=str(outside),
                suggestions=plan.assessment.suggestions + 1,
            ),
        )

        with pytest.raises(ValueError, match="assessment"):
            setup.apply(HarnessApplyRequest(plan=tampered, confirmed=True))

        assert not outside.exists()
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_harness_setup_verify_returns_structured_non_executing_result() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = root / "project"
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(repository),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        marker = root / "command-was-executed"
        command = repository / "verify.sh"
        command.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        command.chmod(0o755)
        workflow = repository / "workflow.yaml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "project": {"root": str(repository), "trusted": True},
                    "capabilities": {
                        "commands": {
                            "unit": {
                                "argv": [str(command)],
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

        result = HarnessSetup().verify(
            HarnessVerifyRequest(
                config_path=workflow,
                codex_bin=sys.executable,
            )
        )

        assert result.state == "verified"
        assert result.config_path == str(workflow.resolve())
        assert result.report.status == "ok"
        assert not marker.exists()


def test_harness_setup_verify_preserves_a_failed_doctor_report() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        workflow = repository / "workflow.yaml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "status": "draft",
                    "project": {"root": str(repository), "trusted": False},
                    "capabilities": {"commands": {}, "skills": {}},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = HarnessSetup().verify(
            HarnessVerifyRequest(
                config_path=workflow,
                codex_bin=sys.executable,
            )
        )

        assert result.state == "verification_failed"
        assert result.report.status == "failed"
        assert any(check.status == "fail" for check in result.report.checks)


def _tree(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(path.relative_to(root))
            for path in root.rglob("*")
        )
    )
