from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import EvidenceStore, HarnessSetup, HarnessSetupRequest  # noqa: E402
from aiwb.cli import main as cli_main  # noqa: E402


def test_approved_python_l0_apply_configures_isolated_candidate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        primary_branch = _git(repository, "branch", "--show-current").stdout.strip()
        dirty = repository / "owner-notes.txt"
        dirty.write_text("keep me\n", encoding="utf-8")
        primary_before = _git(repository, "status", "--porcelain").stdout
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            approved_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            artifact_path=root / "approved-plan.json",
        )

        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )

        assert preview.state == "awaiting_apply_approval"
        assert preview.base_commit == base_commit
        assert preview.dependencies == ()
        assert preview.commands[0].name == "unit"
        assert preview.commands[0].argv == (
            "bash",
            ".ai-workbench/commands/unit.sh",
        )
        assert {
            projection.path for projection in preview.files
        } >= {
            ".ai-workbench/workflow.yaml",
            ".ai-workbench/commands/unit.sh",
            ".github/workflows/aiwb-harness.yml",
            ".codex/skills/project-harness/SKILL.md",
            ".claude/skills/project-harness/SKILL.md",
            "docs/engineering/harness.md",
            "tests/aiwb/test_harness_projection.py",
        }
        assert "create candidate branch" in " ".join(preview.side_effects)

        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            approved_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            artifact_path=root / "approved-apply.json",
        )
        result = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )

        assert result.status == "configured_local"
        assert result.changed is True
        assert result.base_commit == base_commit
        assert result.candidate_commit
        assert result.candidate_commit != base_commit
        assert result.branch.startswith("aiwb/harness-setup/")
        worktree = Path(result.worktree)
        assert worktree.is_dir()
        assert all(evidence.returncode == 0 for evidence in result.evidence)
        assert result.consumption["probe_executions"] == 1
        assert result.consumption["probe_seconds"] >= 0
        assert result.report_path
        report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
        assert report["status"] == "configured_local"
        assert report["candidate_commit"] == result.candidate_commit

        workflow = yaml.safe_load(
            (worktree / ".ai-workbench" / "workflow.yaml").read_text(
                encoding="utf-8"
            )
        )
        canonical = ["bash", ".ai-workbench/commands/unit.sh"]
        assert workflow["capabilities"]["commands"]["unit"]["argv"] == canonical
        pipeline = (
            worktree / ".github" / "workflows" / "aiwb-harness.yml"
        ).read_text(encoding="utf-8")
        assert "bash .ai-workbench/commands/unit.sh" in pipeline
        assert (
            "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
            in pipeline
        )
        assert "actions/checkout@v4" not in pipeline
        guide = (worktree / "docs" / "engineering" / "harness.md").read_text(
            encoding="utf-8"
        )
        codex_skill = (
            worktree / ".codex" / "skills" / "project-harness" / "SKILL.md"
        ).read_text(encoding="utf-8")
        claude_skill = (
            worktree / ".claude" / "skills" / "project-harness" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "bash .ai-workbench/commands/unit.sh" in guide
        assert codex_skill == claude_skill
        assert "bash .ai-workbench/commands/unit.sh" in codex_skill
        generated = _git(
            worktree,
            "status",
            "--porcelain",
        ).stdout
        assert generated == ""
        self_test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/aiwb/test_harness_projection.py"],
            cwd=str(worktree),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self_test.returncode == 0, self_test.stderr or self_test.stdout

        assert _git(repository, "branch", "--show-current").stdout.strip() == (
            primary_branch
        )
        assert _git(repository, "rev-parse", "HEAD").stdout.strip() == base_commit
        assert _git(repository, "status", "--porcelain").stdout == primary_before
        assert dirty.read_text(encoding="utf-8") == "keep me\n"
        assert _git(
            repository,
            "merge-base",
            "--is-ancestor",
            result.candidate_commit,
            primary_branch,
            check=False,
        ).returncode != 0


def test_apply_rejects_missing_or_modified_exact_approval_before_worktree() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )

        with pytest.raises(ValueError, match="exact Apply Approval"):
            setup.apply_approved(
                approved_plan,
                replace(
                    setup.approve_apply(
                        preview,
                        approved_by="owner",
                        artifact_path=root / "apply.json",
                    ),
                    status="draft",
                ),
                state_dir=state_dir,
            )

        modified_preview = replace(
            preview,
            side_effects=preview.side_effects + ("push an image",),
        )
        with pytest.raises(ValueError, match="digest"):
            setup.approve_apply(
                modified_preview,
                approved_by="owner",
                artifact_path=root / "modified-apply.json",
            )

        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "valid-apply.json",
        )
        with pytest.raises(ValueError, match="state directory"):
            setup.apply_approved(
                approved_plan,
                approval,
                state_dir=root / "other-state",
            )

        unapproved_plan = replace(
            approved_plan,
            approval=replace(approved_plan.approval, status="unapproved"),
        )
        with pytest.raises(ValueError, match="approved Harness Plan"):
            setup.apply_approved(
                unapproved_plan,
                approval,
                state_dir=state_dir,
            )

        assert not Path(preview.worktree).exists()
        assert _git(repository, "worktree", "list", "--porcelain").stdout.count(
            "worktree "
        ) == 1


def test_failed_probe_preserves_candidate_first_failure_and_report() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root, failing=True)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )

        result = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )

        assert result.status == "failed_local"
        assert Path(result.worktree).is_dir()
        assert result.candidate_commit
        assert len(result.evidence) == 1
        failure = result.evidence[0]
        assert failure.returncode == 1
        assert "expected failure" in failure.stdout
        assert "assert False" in failure.stdout
        assert result.cleanup_status == "not_required"
        report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
        assert report["status"] == "failed_local"
        assert report["evidence"][0]["returncode"] == 1
        assert _git(
            repository,
            "show-ref",
            "--verify",
            f"refs/heads/{result.branch}",
        ).returncode == 0
        assert _git(repository, "rev-parse", "main").stdout.strip() == base_commit


def test_reapplying_the_same_approval_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )

        first = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )
        second = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )

        assert first.status == second.status == "configured_local"
        assert second.changed is False
        assert second.candidate_commit == first.candidate_commit
        assert _git(
            Path(first.worktree),
            "rev-list",
            "--count",
            f"{base_commit}..HEAD",
        ).stdout.strip() == "1"


def test_python_l0_apply_runs_approved_quality_and_report_probes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root, full_l0=True)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("lint", "format", "typecheck", "unit", "coverage"),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )

        result = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )

        assert result.status == "configured_local"
        assert [item.name for item in result.evidence] == [
            "lint",
            "format",
            "typecheck",
            "unit",
            "coverage",
        ]
        assert all(item.returncode == 0 for item in result.evidence)
        assert result.consumption["probe_executions"] == 5
        artifacts = {
            Path(path).name
            for item in result.evidence
            for path in item.artifacts
        }
        assert artifacts >= {"coverage.xml", "junit.xml"}
        worktree = Path(result.worktree)
        assert not (worktree / "coverage.xml").exists()
        assert not (worktree / "junit.xml").exists()
        assert all(Path(path).is_file() for item in result.evidence for path in item.artifacts)


def test_python_l0_cli_preserves_both_approval_boundaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        approved_plan = root / "approved-plan.json"
        approved_apply = root / "approved-apply.json"
        state_dir = root / "state"

        assert cli_main(
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
                str(approved_plan),
            ]
        ) == 0
        capsys.readouterr()

        assert cli_main(
            [
                "setup",
                "--repo",
                str(repository),
                "--planning-mode",
                "python-l0",
                "--approved-plan",
                str(approved_plan),
                "--base-commit",
                base_commit,
                "--state-dir",
                str(state_dir),
                "--apply-command",
                "unit",
                "--preview-apply",
            ]
        ) == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["state"] == "awaiting_apply_approval"
        assert not approved_apply.exists()

        assert cli_main(
            [
                "setup",
                "--repo",
                str(repository),
                "--planning-mode",
                "python-l0",
                "--approved-plan",
                str(approved_plan),
                "--base-commit",
                base_commit,
                "--state-dir",
                str(state_dir),
                "--apply-command",
                "unit",
                "--approve-apply",
                "--approved-by",
                "owner",
                "--apply-artifact",
                str(approved_apply),
            ]
        ) == 0
        approval = json.loads(capsys.readouterr().out)
        assert approval["status"] == "approved"
        assert approved_apply.is_file()

        assert cli_main(
            [
                "setup",
                "--repo",
                str(repository),
                "--planning-mode",
                "python-l0",
                "--approved-plan",
                str(approved_plan),
                "--base-commit",
                base_commit,
                "--state-dir",
                str(state_dir),
                "--apply-command",
                "unit",
                "--execute-apply",
                "--apply-artifact",
                str(approved_apply),
            ]
        ) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "configured_local"
        assert Path(result["worktree"]).is_dir()


def test_apply_preview_records_existing_file_digest_for_exact_review() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        existing = repository / "docs" / "engineering" / "harness.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("# Existing owner guide\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Add owner guide")
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )

        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=root / "state",
            command_names=("unit",),
        )

        guide = next(
            item
            for item in preview.files
            if item.path == "docs/engineering/harness.md"
        )
        assert guide.previous_sha256
        assert guide.previous_sha256 != guide.to_dict()["sha256"]
        workflow = next(
            item
            for item in preview.files
            if item.path == ".ai-workbench/workflow.yaml"
        )
        assert workflow.previous_sha256 == ""


def test_probe_output_is_bounded_and_full_evidence_is_retained() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root, noisy=True)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )

        result = setup.apply_approved(
            approved_plan,
            approval,
            state_dir=state_dir,
        )

        evidence = result.evidence[0]
        assert len(evidence.stdout.encode("utf-8")) <= 4096
        assert "truncated" in evidence.stdout
        assert evidence.stdout_ref is not None
        payload = EvidenceStore(state_dir).read(
            evidence.stdout_ref.artifact_id,
            reference=evidence.stdout_ref,
        )
        assert len(payload.content) > 100_000


def test_apply_rejects_projection_symlink_escape_and_preserves_outside() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        outside = root / "outside"
        outside.mkdir()
        (repository / ".ai-workbench").symlink_to(
            outside,
            target_is_directory=True,
        )
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "Add unsafe projection symlink")
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )

        with pytest.raises(ValueError, match="inside the candidate"):
            setup.apply_approved(
                approved_plan,
                approval,
                state_dir=state_dir,
            )

        assert list(outside.iterdir()) == []


def test_apply_rejects_existing_candidate_at_unapproved_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )
        worktree = Path(preview.worktree)
        _git(
            repository,
            "worktree",
            "add",
            "-b",
            preview.branch,
            str(worktree),
            base_commit,
        )
        unrelated = worktree / "unrelated.txt"
        unrelated.write_text("not approved\n", encoding="utf-8")
        _git(worktree, "add", ".")
        _git(worktree, "commit", "-m", "Unapproved candidate mutation")

        with pytest.raises(ValueError, match="approved base commit"):
            setup.apply_approved(
                approved_plan,
                approval,
                state_dir=state_dir,
            )


def test_apply_rejects_state_directory_inside_primary_repository() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )

        with pytest.raises(ValueError, match="outside the target repository"):
            setup.preview_apply(
                approved_plan,
                base_commit=base_commit,
                state_dir=repository / ".ai-workbench-state",
                command_names=("unit",),
            )

        assert not (repository / ".ai-workbench-state").exists()


def test_apply_rejects_unmounted_candidate_branch_at_unapproved_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = _python_repository(root)
        base_commit = _git(repository, "rev-parse", "HEAD").stdout.strip()
        state_dir = root / "state"
        setup = HarnessSetup()
        plan = setup.plan(
            HarnessSetupRequest(
                repository=repository,
                planning_mode="python-l0",
            )
        )
        approved_plan = setup.approve_plan(
            plan,
            approved_by="owner",
            artifact_path=root / "approved-plan.json",
        )
        preview = setup.preview_apply(
            approved_plan,
            base_commit=base_commit,
            state_dir=state_dir,
            command_names=("unit",),
        )
        approval = setup.approve_apply(
            preview,
            approved_by="owner",
            artifact_path=root / "approved-apply.json",
        )
        _git(repository, "branch", preview.branch, base_commit)
        intruder = root / "intruder"
        _git(repository, "worktree", "add", str(intruder), preview.branch)
        (intruder / "unapproved.txt").write_text("unapproved\n", encoding="utf-8")
        _git(intruder, "add", ".")
        _git(intruder, "commit", "-m", "Unapproved branch mutation")
        _git(repository, "worktree", "remove", str(intruder))

        with pytest.raises(ValueError, match="approved base commit"):
            setup.apply_approved(
                approved_plan,
                approval,
                state_dir=state_dir,
            )

        assert not Path(preview.worktree).exists()


def _python_repository(
    root: Path,
    failing: bool = False,
    full_l0: bool = False,
    noisy: bool = False,
) -> Path:
    repository = root / "project"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "AI Workbench Test")
    _git(repository, "config", "user.email", "aiwb@example.test")
    (repository / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    (repository / "tests").mkdir()
    (repository / "tests" / "test_sample.py").write_text(
        (
            "def test_sample():\n"
            "    print('expected failure')\n"
            "    assert False\n"
            if failing
            else "def test_sample():\n"
            "    print('x' * 120000)\n"
            "    assert True\n"
            if noisy
            else "def test_sample():\n"
            "    assert 1 + 1 == 2\n"
        ),
        encoding="utf-8",
    )
    if full_l0:
        (repository / "ruff.py").write_text(
            "import sys\n"
            "raise SystemExit(0 if sys.argv[1] in {'check', 'format'} else 2)\n",
            encoding="utf-8",
        )
        (repository / "mypy.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        (repository / "conftest.py").write_text(
            "from pathlib import Path\n\n"
            "def pytest_addoption(parser):\n"
            "    parser.addoption('--cov', action='store', nargs='?', const='.')\n"
            "    parser.addoption('--cov-report', action='store')\n\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    if session.config.getoption('--cov') is not None:\n"
            "        Path('coverage.xml').write_text('<coverage/>\\n')\n",
            encoding="utf-8",
        )
    dependencies = (
        "test = ['pytest>=8', 'pytest-cov>=5', 'ruff==0.12.4', 'mypy==1.17']\n\n"
        if full_l0
        else "test = ['pytest>=8']\n\n"
    )
    (repository / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = ['setuptools>=68']\n"
        "build-backend = 'setuptools.build_meta'\n\n"
        "[project]\n"
        "name = 'sample'\n\n"
        "[project.optional-dependencies]\n"
        + dependencies
        +
        "[tool.pytest.ini_options]\n"
        "testpaths = ['tests']\n",
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "Initial fixture")
    return repository


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
