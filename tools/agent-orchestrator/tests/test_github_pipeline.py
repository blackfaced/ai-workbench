from __future__ import annotations

import sys
import json
import tempfile
import os
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    GitHubActionsAdapter,
    GhApiGitHubSource,
    GitHubPipelineRequest,
    HarnessSetup,
    HarnessApplyResult,
)
from aiwb.cli import main as cli_main  # noqa: E402


COMMIT = "a" * 40


class FixtureSource:
    def __init__(self, *, runs=(), jobs=(), checks=(), artifacts=()) -> None:
        self.runs = tuple(runs)
        self.jobs = tuple(jobs)
        self.checks = tuple(checks)
        self.artifacts = tuple(artifacts)
        self.calls = []

    def workflow_runs(self, request):
        self.calls.append(("runs", request.commit))
        return self.runs

    def run_jobs(self, request, run_id):
        self.calls.append(("jobs", run_id))
        return tuple(item for item in self.jobs if item["run_id"] == run_id)

    def check_runs(self, request):
        self.calls.append(("checks", request.commit))
        return self.checks

    def artifacts_for_run(self, request, run_id):
        self.calls.append(("artifacts", run_id))
        return tuple(
            item for item in self.artifacts if item["workflow_run"]["id"] == run_id
        )


def test_pending_exact_commit_transitions_configured_local_to_pipeline_pending() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="in_progress", conclusion=None),
        ),
        jobs=(
            _job(10, 100, status="in_progress", conclusion=None),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="in_progress", conclusion=None),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "pipeline_pending"
    assert result.candidate_commit == COMMIT
    assert result.provider == "github-actions"
    assert {item.kind for item in result.evidence} >= {"run", "job", "check"}
    assert all(item.commit == COMMIT for item in result.evidence)


def test_only_successful_required_exact_commit_checks_can_verify() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion="success"),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="completed", conclusion="success"),
        ),
        artifacts=(
            _artifact(10, "harness-evidence", expired=False),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verified"
    assert result.blockers == ()
    assert any(
        item.kind == "artifact" and item.name == "harness-evidence"
        for item in result.evidence
    )
    assert source.calls == [
        ("runs", COMMIT),
        ("checks", COMMIT),
        ("jobs", 10),
        ("artifacts", 10),
    ]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_terminal_failures_remain_explicitly_non_verified(conclusion: str) -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion=conclusion),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion=conclusion),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="completed", conclusion=conclusion),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verification_failed"
    assert {blocker.code for blocker in result.blockers} >= {"required_check_failed"}
    assert any(item.conclusion == conclusion for item in result.evidence)


def test_stale_green_commit_never_verifies_candidate() -> None:
    stale = "b" * 40
    source = FixtureSource(
        runs=(
            _run(9, commit=stale, status="completed", conclusion="success"),
        ),
        checks=(
            _check("harness", commit=stale, status="completed", conclusion="success"),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verification_failed"
    assert [blocker.code for blocker in result.blockers] == ["exact_commit_missing"]
    assert any(item.commit == stale and item.stale for item in result.evidence)


def test_missing_required_artifact_is_non_verified() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion="success"),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="completed", conclusion="success"),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verification_failed"
    assert [blocker.code for blocker in result.blockers] == [
        "required_artifact_missing"
    ]


def test_expired_required_artifact_is_non_verified_and_visible() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion="success"),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="completed", conclusion="success"),
        ),
        artifacts=(
            _artifact(10, "harness-evidence", expired=True),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verification_failed"
    assert [blocker.code for blocker in result.blockers] == [
        "required_artifact_missing"
    ]
    assert any(
        item.kind == "artifact"
        and item.name == "harness-evidence"
        and item.expired
        for item in result.evidence
    )


def test_completed_run_with_missing_required_check_is_non_verified() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion="success"),
        ),
        checks=(),
        artifacts=(
            _artifact(10, "harness-evidence", expired=False),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verification_failed"
    assert [blocker.code for blocker in result.blockers] == [
        "required_check_missing"
    ]


def test_in_progress_run_waits_for_required_check_to_appear() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="in_progress", conclusion=None),
        ),
        jobs=(
            _job(10, 100, status="queued", conclusion=None),
        ),
        checks=(),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "pipeline_pending"
    assert result.blockers == ()


def test_flaky_retry_preserves_first_failure_and_successful_retry() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, attempt=1, status="completed", conclusion="failure"),
            _run(11, commit=COMMIT, attempt=2, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, attempt=1, status="completed", conclusion="failure"),
            _job(11, 101, attempt=2, status="completed", conclusion="success"),
        ),
        checks=(
            _check(
                "harness",
                commit=COMMIT,
                status="completed",
                conclusion="success",
            ),
        ),
        artifacts=(
            _artifact(11, "harness-evidence", expired=False),
        ),
    )

    result = GitHubActionsAdapter(source).verify(_request())

    assert result.status == "verified"
    runs = [item for item in result.evidence if item.kind == "run"]
    assert [(item.attempt, item.conclusion) for item in runs] == [
        (1, "failure"),
        (2, "success"),
    ]
    assert result.retry_count == 1
    assert result.flaky is True


def test_adapter_rejects_non_configured_local_input() -> None:
    configured = replace_apply_status("failed_local")
    request = _request(configured=configured)

    with pytest.raises(ValueError, match="configured_local"):
        GitHubActionsAdapter(FixtureSource()).verify(request)


def test_missing_variable_reports_only_name_and_purpose() -> None:
    source = FixtureSource(
        runs=(
            _run(10, commit=COMMIT, status="completed", conclusion="success"),
        ),
        jobs=(
            _job(10, 100, status="completed", conclusion="success"),
        ),
        checks=(
            _check("harness", commit=COMMIT, status="completed", conclusion="success"),
        ),
        artifacts=(
            _artifact(10, "harness-evidence", expired=False),
        ),
    )
    request = GitHubPipelineRequest(
        owner="blackfaced",
        repository="ai-workbench",
        candidate=replace_apply_status("configured_local"),
        required_checks=("harness",),
        required_artifacts=("harness-evidence",),
        missing_variables=(("PACKAGE_TOKEN", "read private test dependency"),),
    )

    result = GitHubActionsAdapter(source).verify(request)

    assert result.status == "verification_failed"
    assert [blocker.code for blocker in result.blockers] == [
        "required_variable_missing"
    ]
    payload = json.dumps(result.to_dict())
    assert "PACKAGE_TOKEN" in payload
    assert "read private test dependency" in payload
    assert not _contains_key(result.to_dict(), {"value", "secret_value"})


def test_harness_setup_persists_pipeline_observations_without_losing_failures() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        request = _request()
        failed_source = FixtureSource(
            runs=(
                _run(10, commit=COMMIT, status="completed", conclusion="failure"),
            ),
            jobs=(
                _job(10, 100, status="completed", conclusion="failure"),
            ),
            checks=(
                _check(
                    "harness",
                    commit=COMMIT,
                    status="completed",
                    conclusion="failure",
                ),
            ),
        )
        success_source = FixtureSource(
            runs=(
                _run(
                    10,
                    commit=COMMIT,
                    attempt=1,
                    status="completed",
                    conclusion="failure",
                ),
                _run(
                    11,
                    commit=COMMIT,
                    attempt=2,
                    status="completed",
                    conclusion="success",
                ),
            ),
            jobs=(
                _job(10, 100, attempt=1, status="completed", conclusion="failure"),
                _job(11, 101, attempt=2, status="completed", conclusion="success"),
            ),
            checks=(
                _check(
                    "harness",
                    commit=COMMIT,
                    status="completed",
                    conclusion="success",
                ),
            ),
            artifacts=(_artifact(11, "harness-evidence", expired=False),),
        )

        first = HarnessSetup().verify_pipeline(
            request,
            adapter=GitHubActionsAdapter(failed_source),
            state_dir=root / "state",
        )
        second = HarnessSetup().verify_pipeline(
            request,
            adapter=GitHubActionsAdapter(success_source),
            state_dir=root / "state",
        )

        assert first.status == "verification_failed"
        assert second.status == "verified"
        report = root / "state" / "reports" / "pipeline" / COMMIT / "report.json"
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert [item["status"] for item in payload["observations"]] == [
            "verification_failed",
            "verified",
        ]
        assert any(
            evidence["conclusion"] == "failure"
            for observation in payload["observations"]
            for evidence in observation["evidence"]
        )


def test_gh_source_uses_only_side_effect_free_get_requests() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        log = root / "commands.jsonl"
        executable = root / "gh"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "with Path(os.environ['GH_FIXTURE_LOG']).open('a') as stream:\n"
            "    stream.write(json.dumps(args) + '\\n')\n"
            "endpoint = args[args.index('GET') + 1]\n"
            "if endpoint.endswith('/actions/runs'):\n"
            "    value = {'workflow_runs': []}\n"
            "elif endpoint.endswith('/check-runs'):\n"
            "    value = {'check_runs': []}\n"
            "elif endpoint.endswith('/jobs'):\n"
            "    value = {'jobs': []}\n"
            "elif endpoint.endswith('/artifacts'):\n"
            "    value = {'artifacts': []}\n"
            "else:\n"
            "    raise SystemExit(2)\n"
            "print(json.dumps(value))\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        source = GhApiGitHubSource(
            executable=str(executable),
            environment={"GH_FIXTURE_LOG": str(log)},
        )
        request = _request()

        assert source.workflow_runs(request) == ()
        assert source.check_runs(request) == ()
        assert source.run_jobs(request, 10) == ()
        assert source.artifacts_for_run(request, 10) == ()

        calls = [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
        ]
        assert len(calls) == 4
        assert all(call[:3] == ["api", "-X", "GET"] for call in calls)
        runs_call = calls[0]
        assert "branch=aiwb/harness-setup/candidate" in runs_call
        assert all(not part.startswith("head_sha=") for part in runs_call)
        serialized = json.dumps(calls)
        assert "workflow_dispatch" not in serialized
        assert "dispatches" not in serialized
        assert "/actions/secrets" not in serialized
        assert "/branches/" not in serialized


def test_pipeline_cli_reads_candidate_report_and_returns_pending(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate_report = root / "candidate.json"
        candidate_report.write_text(
            json.dumps(replace_apply_status("configured_local").to_dict()),
            encoding="utf-8",
        )
        executable = root / "gh"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "endpoint = args[args.index('GET') + 1]\n"
            f"commit = {COMMIT!r}\n"
            "if endpoint.endswith('/actions/runs'):\n"
            "    value = {'workflow_runs': [{\n"
            "        'id': 10, 'head_sha': commit, 'status': 'in_progress',\n"
            "        'conclusion': None, 'run_attempt': 1,\n"
            "        'html_url': 'https://github.test/runs/10',\n"
            "        'name': 'AI Workbench Harness', 'event': 'push'}]}\n"
            "elif endpoint.endswith('/check-runs'):\n"
            "    value = {'check_runs': [{\n"
            "        'id': 1000, 'name': 'harness', 'head_sha': commit,\n"
            "        'status': 'in_progress', 'conclusion': None,\n"
            "        'html_url': 'https://github.test/checks/1000'}]}\n"
            "elif endpoint.endswith('/jobs'):\n"
            "    value = {'jobs': [{\n"
            "        'id': 100, 'name': 'harness', 'status': 'in_progress',\n"
            "        'conclusion': None, 'run_attempt': 1,\n"
            "        'html_url': 'https://github.test/jobs/100'}]}\n"
            "elif endpoint.endswith('/artifacts'):\n"
            "    value = {'artifacts': []}\n"
            "else:\n"
            "    raise SystemExit(2)\n"
            "print(json.dumps(value))\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        monkeypatch.setenv("AIWB_GH_BIN", str(executable))

        returncode = cli_main(
            [
                "pipeline",
                "verify",
                "--candidate-report",
                str(candidate_report),
                "--owner",
                "blackfaced",
                "--repository",
                "ai-workbench",
                "--required-check",
                "harness",
                "--required-artifact",
                "harness-evidence",
                "--state-dir",
                str(root / "state"),
            ]
        )
        value = json.loads(capsys.readouterr().out)

        assert returncode == 0
        assert value["status"] == "pipeline_pending"
        report = root / "state" / "reports" / "pipeline" / COMMIT / "report.json"
        assert report.is_file()


def test_repository_github_workflow_has_stable_gate_and_pinned_actions() -> None:
    workflow = (
        TOOL_ROOT.parent.parent / ".github" / "workflows" / "aiwb-harness.yml"
    ).read_text(encoding="utf-8")

    assert "name: AI Workbench Harness" in workflow
    assert "  harness:\n    name: harness" in workflow
    assert "name: harness-evidence" in workflow
    assert "PYTHONPYCACHEPREFIX:" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert "actions/upload-artifact@65c4c4a1ddee5b72f698fdd19549f0f0fb45cf08" in workflow
    assert "workflow_dispatch" not in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow


def _request(configured=None) -> GitHubPipelineRequest:
    return GitHubPipelineRequest(
        owner="blackfaced",
        repository="ai-workbench",
        candidate=configured or replace_apply_status("configured_local"),
        required_checks=("harness",),
        required_artifacts=("harness-evidence",),
    )


def replace_apply_status(status: str) -> HarnessApplyResult:
    return HarnessApplyResult(
        status=status,
        changed=True,
        repository="/tmp/project",
        branch="aiwb/harness-setup/candidate",
        worktree="/tmp/worktree",
        base_commit="c" * 40,
        candidate_commit=COMMIT,
        evidence=(),
        consumption={},
        report_path="/tmp/report.json",
        cleanup_status="not_required",
    )


def _run(
    run_id: int,
    *,
    commit: str,
    status: str,
    conclusion,
    attempt: int = 1,
):
    return {
        "id": run_id,
        "head_sha": commit,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "html_url": f"https://github.test/runs/{run_id}",
        "name": "AI Workbench Harness",
        "event": "push",
    }


def _job(run_id: int, job_id: int, *, status: str, conclusion, attempt: int = 1):
    return {
        "id": job_id,
        "run_id": run_id,
        "name": "harness",
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "html_url": f"https://github.test/jobs/{job_id}",
    }


def _check(name: str, *, commit: str, status: str, conclusion):
    return {
        "id": 1000,
        "name": name,
        "head_sha": commit,
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.test/checks/1000",
    }


def _artifact(run_id: int, name: str, *, expired: bool):
    return {
        "id": 2000,
        "name": name,
        "expired": expired,
        "archive_download_url": "https://api.github.test/artifacts/2000/zip",
        "workflow_run": {"id": run_id, "head_sha": COMMIT},
    }


def _contains_key(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in forbidden or _contains_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, forbidden) for item in value)
    return False
