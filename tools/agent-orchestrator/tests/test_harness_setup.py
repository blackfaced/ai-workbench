from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    HarnessApplyRequest,
    HarnessSetup,
    HarnessSetupRequest,
    HarnessVerifyRequest,
    ProjectInitError,
)


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
        assert candidate.workflow_path == str(workflow)
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
