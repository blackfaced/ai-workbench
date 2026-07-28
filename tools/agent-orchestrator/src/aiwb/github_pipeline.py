from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, Tuple

from ._harness_apply import HarnessApplyResult
from .intake import IntakeBlocker


@dataclass(frozen=True)
class GitHubPipelineRequest:
    owner: str
    repository: str
    candidate: HarnessApplyResult
    required_checks: Tuple[str, ...]
    required_artifacts: Tuple[str, ...] = ()
    missing_variables: Tuple[Tuple[str, str], ...] = ()

    @property
    def commit(self) -> str:
        return self.candidate.candidate_commit


@dataclass(frozen=True)
class PipelineEvidence:
    kind: str
    name: str
    identifier: str
    commit: str
    status: str
    conclusion: str
    attempt: int
    url: str
    stale: bool = False
    expired: bool = False

    def to_dict(self) -> Mapping[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "identifier": self.identifier,
            "commit": self.commit,
            "status": self.status,
            "conclusion": self.conclusion,
            "attempt": self.attempt,
            "url": self.url,
            "stale": self.stale,
            "expired": self.expired,
        }


@dataclass(frozen=True)
class PipelineVerification:
    status: str
    provider: str
    repository: str
    candidate_commit: str
    evidence: Tuple[PipelineEvidence, ...]
    blockers: Tuple[IntakeBlocker, ...]
    retry_count: int
    flaky: bool

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "repository": self.repository,
            "candidate_commit": self.candidate_commit,
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": [
                {
                    "code": item.code,
                    "message": item.message,
                    "action": item.action,
                }
                for item in self.blockers
            ],
            "retry_count": self.retry_count,
            "flaky": self.flaky,
        }


class GitHubReadSource(Protocol):
    def workflow_runs(
        self,
        request: GitHubPipelineRequest,
    ) -> Sequence[Mapping[str, object]]:
        ...

    def run_jobs(
        self,
        request: GitHubPipelineRequest,
        run_id: int,
    ) -> Sequence[Mapping[str, object]]:
        ...

    def check_runs(
        self,
        request: GitHubPipelineRequest,
    ) -> Sequence[Mapping[str, object]]:
        ...

    def artifacts_for_run(
        self,
        request: GitHubPipelineRequest,
        run_id: int,
    ) -> Sequence[Mapping[str, object]]:
        ...


class GitHubActionsAdapter:
    """Map side-effect-free GitHub Actions reads into Harness verification."""

    def __init__(self, source: GitHubReadSource) -> None:
        self._source = source

    def verify(self, request: GitHubPipelineRequest) -> PipelineVerification:
        _validate_request(request)
        raw_runs = tuple(self._source.workflow_runs(request))
        raw_checks = tuple(self._source.check_runs(request))
        exact_runs = tuple(
            run for run in raw_runs if str(run.get("head_sha", "")) == request.commit
        )
        evidence = [
            _run_evidence(run, request.commit)
            for run in raw_runs
        ]
        evidence.extend(
            _check_evidence(check, request.commit)
            for check in raw_checks
        )
        blockers = []
        for name, purpose in request.missing_variables:
            blockers.append(
                IntakeBlocker(
                    code="required_variable_missing",
                    message=(
                        f"Required pipeline variable is missing: {name} "
                        f"(purpose: {purpose})."
                    ),
                    action=(
                        "Ask the repository owner to configure the named variable; "
                        "do not provide or persist its value in AI Workbench."
                    ),
                )
            )
        if not exact_runs:
            blockers.append(
                IntakeBlocker(
                    code="exact_commit_missing",
                    message=(
                        "No GitHub Actions run exists for the exact candidate commit."
                    ),
                    action=(
                        "Publish the exact candidate commit through the approved "
                        "repository flow and wait for its configured workflow."
                    ),
                )
            )
            return _result(request, evidence, blockers)

        exact_runs = tuple(sorted(exact_runs, key=_attempt_key))
        for run in exact_runs:
            run_id = _integer(run.get("id"), "workflow run id")
            jobs = tuple(self._source.run_jobs(request, run_id))
            evidence.extend(
                _job_evidence(job, request.commit, run)
                for job in jobs
            )
            artifacts = tuple(self._source.artifacts_for_run(request, run_id))
            evidence.extend(
                _artifact_evidence(artifact, request.commit, run)
                for artifact in artifacts
            )

        exact_checks = tuple(
            check
            for check in raw_checks
            if str(check.get("head_sha", "")) == request.commit
        )
        latest_run = exact_runs[-1]
        latest_run_id = _integer(latest_run.get("id"), "workflow run id")
        run_status = str(latest_run.get("status", ""))
        run_conclusion = str(latest_run.get("conclusion") or "")
        pending = run_status != "completed"
        check_by_name = {
            str(check.get("name", "")): check
            for check in exact_checks
        }
        for required in request.required_checks:
            check = check_by_name.get(required)
            if check is None:
                if not pending:
                    blockers.append(
                        IntakeBlocker(
                            code="required_check_missing",
                            message=f"Required check is missing: {required}.",
                            action=(
                                "Confirm the workflow check name and wait for the exact "
                                "candidate commit check to appear."
                            ),
                        )
                    )
                continue
            status = str(check.get("status", ""))
            conclusion = str(check.get("conclusion") or "")
            if status != "completed":
                pending = True
            elif conclusion != "success":
                blockers.append(
                    IntakeBlocker(
                        code="required_check_failed",
                        message=(
                            f"Required check {required!r} concluded {conclusion or 'unknown'}."
                        ),
                        action=(
                            "Inspect the first failing run and job Evidence; fix the "
                            "candidate without weakening or quarantining the gate."
                        ),
                    )
                )

        if run_status == "completed" and run_conclusion != "success":
            blockers.append(
                IntakeBlocker(
                    code="required_check_failed",
                    message=(
                        f"Latest exact-commit workflow concluded "
                        f"{run_conclusion or 'unknown'}."
                    ),
                    action="Inspect the retained run and job Evidence before retrying.",
                )
            )
        latest_artifacts = tuple(
            item
            for item in evidence
            if item.kind == "artifact"
            and item.identifier.startswith(f"{latest_run_id}:")
            and not item.expired
        )
        artifact_names = {item.name for item in latest_artifacts}
        if not pending and not blockers:
            for required in request.required_artifacts:
                if required not in artifact_names:
                    blockers.append(
                        IntakeBlocker(
                            code="required_artifact_missing",
                            message=f"Required pipeline artifact is missing: {required}.",
                            action=(
                                "Upload the required artifact from the exact successful "
                                "candidate run and retain its GitHub reference."
                            ),
                        )
                    )
        return _result(request, evidence, blockers, pending=pending)


class GhApiGitHubSource:
    """Read GitHub Actions facts through authenticated `gh api -X GET` calls."""

    def __init__(
        self,
        executable: str = "/usr/bin/gh",
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._executable = executable
        self._environment = (
            dict(environment)
            if environment is not None
            else dict(os.environ)
        )

    def workflow_runs(
        self,
        request: GitHubPipelineRequest,
    ) -> Sequence[Mapping[str, object]]:
        value = self._get(
            f"repos/{request.owner}/{request.repository}/actions/runs",
            {
                "branch": request.candidate.branch,
                "per_page": "100",
            },
        )
        return _mapping_list(value, "workflow_runs")

    def run_jobs(
        self,
        request: GitHubPipelineRequest,
        run_id: int,
    ) -> Sequence[Mapping[str, object]]:
        value = self._get(
            f"repos/{request.owner}/{request.repository}/actions/runs/{run_id}/jobs",
            {"filter": "all", "per_page": "100"},
        )
        jobs = []
        for job in _mapping_list(value, "jobs"):
            jobs.append({**job, "run_id": run_id})
        return tuple(jobs)

    def check_runs(
        self,
        request: GitHubPipelineRequest,
    ) -> Sequence[Mapping[str, object]]:
        value = self._get(
            f"repos/{request.owner}/{request.repository}/commits/{request.commit}/check-runs",
            {"filter": "all", "per_page": "100"},
            accept="application/vnd.github+json",
        )
        return _mapping_list(value, "check_runs")

    def artifacts_for_run(
        self,
        request: GitHubPipelineRequest,
        run_id: int,
    ) -> Sequence[Mapping[str, object]]:
        value = self._get(
            f"repos/{request.owner}/{request.repository}/actions/runs/{run_id}/artifacts",
            {"per_page": "100"},
        )
        artifacts = []
        for artifact in _mapping_list(value, "artifacts"):
            workflow_run = artifact.get("workflow_run")
            workflow_run = workflow_run if isinstance(workflow_run, dict) else {}
            artifacts.append(
                {
                    **artifact,
                    "workflow_run": {
                        **workflow_run,
                        "id": run_id,
                        "head_sha": request.commit,
                    },
                }
            )
        return tuple(artifacts)

    def _get(
        self,
        endpoint: str,
        fields: Mapping[str, str],
        *,
        accept: str = "",
    ) -> Mapping[str, object]:
        command = [self._executable, "api", "-X", "GET", endpoint]
        for name, value in fields.items():
            command.extend(["-f", f"{name}={value}"])
        if accept:
            command.extend(["-H", f"Accept: {accept}"])
        completed = subprocess.run(
            command,
            env=self._environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ValueError(
                f"GitHub read failed for {endpoint}: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(f"GitHub returned invalid JSON for {endpoint}") from error
        if not isinstance(value, dict):
            raise ValueError(f"GitHub response must be an object: {endpoint}")
        return value


def append_pipeline_observation(
    request: GitHubPipelineRequest,
    result: PipelineVerification,
    *,
    state_dir,
) -> str:
    state_dir = Path(state_dir).expanduser().resolve()
    repository = Path(request.candidate.repository).expanduser().resolve()
    try:
        state_dir.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError(
            "Pipeline verification state directory must stay outside the target repository"
        )
    path = (
        state_dir
        / "reports"
        / "pipeline"
        / request.commit
        / "report.json"
    )
    observations = []
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read pipeline report: {error}") from error
        if not isinstance(existing, dict):
            raise ValueError("pipeline report must be a JSON object")
        value = existing.get("observations", [])
        if not isinstance(value, list):
            raise ValueError("pipeline report observations must be a list")
        observations.extend(item for item in value if isinstance(item, dict))
    observations.append(result.to_dict())
    payload = {
        "provider": result.provider,
        "repository": result.repository,
        "candidate_commit": result.candidate_commit,
        "status": result.status,
        "observations": observations,
    }
    _write_json_atomically(path, payload)
    return str(path)


def _result(
    request: GitHubPipelineRequest,
    evidence: Sequence[PipelineEvidence],
    blockers: Sequence[IntakeBlocker],
    *,
    pending: bool = False,
) -> PipelineVerification:
    attempts = sorted(
        {
            item.attempt
            for item in evidence
            if item.kind == "run" and not item.stale
        }
    )
    conclusions = {
        item.conclusion
        for item in evidence
        if item.kind == "run" and not item.stale and item.conclusion
    }
    flaky = "failure" in conclusions and "success" in conclusions
    if blockers:
        status = "verification_failed"
    elif pending:
        status = "pipeline_pending"
    else:
        status = "verified"
    return PipelineVerification(
        status=status,
        provider="github-actions",
        repository=f"{request.owner}/{request.repository}",
        candidate_commit=request.commit,
        evidence=tuple(evidence),
        blockers=tuple(_dedupe_blockers(blockers)),
        retry_count=max(0, len(attempts) - 1),
        flaky=flaky,
    )


def _run_evidence(
    run: Mapping[str, object],
    commit: str,
) -> PipelineEvidence:
    observed = str(run.get("head_sha", ""))
    return PipelineEvidence(
        kind="run",
        name=str(run.get("name", "")),
        identifier=str(run.get("id", "")),
        commit=observed,
        status=str(run.get("status", "")),
        conclusion=str(run.get("conclusion") or ""),
        attempt=_integer(run.get("run_attempt", 1), "run attempt"),
        url=str(run.get("html_url", "")),
        stale=observed != commit,
    )


def _job_evidence(
    job: Mapping[str, object],
    commit: str,
    run: Mapping[str, object],
) -> PipelineEvidence:
    observed = str(run.get("head_sha", ""))
    run_id = _integer(run.get("id"), "workflow run id")
    return PipelineEvidence(
        kind="job",
        name=str(job.get("name", "")),
        identifier=f"{run_id}:{job.get('id', '')}",
        commit=observed,
        status=str(job.get("status", "")),
        conclusion=str(job.get("conclusion") or ""),
        attempt=_integer(job.get("run_attempt", run.get("run_attempt", 1)), "job attempt"),
        url=str(job.get("html_url", "")),
        stale=observed != commit,
    )


def _check_evidence(
    check: Mapping[str, object],
    commit: str,
) -> PipelineEvidence:
    observed = str(check.get("head_sha", ""))
    return PipelineEvidence(
        kind="check",
        name=str(check.get("name", "")),
        identifier=str(check.get("id", "")),
        commit=observed,
        status=str(check.get("status", "")),
        conclusion=str(check.get("conclusion") or ""),
        attempt=1,
        url=str(check.get("html_url", "")),
        stale=observed != commit,
    )


def _artifact_evidence(
    artifact: Mapping[str, object],
    commit: str,
    run: Mapping[str, object],
) -> PipelineEvidence:
    workflow_run = artifact.get("workflow_run")
    workflow_run = workflow_run if isinstance(workflow_run, dict) else {}
    observed = str(workflow_run.get("head_sha") or run.get("head_sha", ""))
    run_id = _integer(run.get("id"), "workflow run id")
    return PipelineEvidence(
        kind="artifact",
        name=str(artifact.get("name", "")),
        identifier=f"{run_id}:{artifact.get('id', '')}",
        commit=observed,
        status="completed",
        conclusion="success" if artifact.get("expired") is not True else "expired",
        attempt=_integer(run.get("run_attempt", 1), "artifact attempt"),
        url=str(artifact.get("archive_download_url", "")),
        stale=observed != commit,
        expired=artifact.get("expired") is True,
    )


def _validate_request(request: GitHubPipelineRequest) -> None:
    if request.candidate.status != "configured_local":
        raise ValueError("Pipeline verification requires configured_local candidate")
    if not request.owner or not request.repository:
        raise ValueError("GitHub owner and repository are required")
    if len(request.commit) != 40:
        raise ValueError("candidate commit must be a full Git commit SHA")
    if not request.required_checks:
        raise ValueError("at least one required pipeline check is required")
    for name, purpose in request.missing_variables:
        if not name or not purpose:
            raise ValueError(
                "missing pipeline variables require a non-empty name and purpose"
            )


def _attempt_key(run: Mapping[str, object]) -> Tuple[int, int]:
    return (
        _integer(run.get("run_attempt", 1), "run attempt"),
        _integer(run.get("id"), "workflow run id"),
    )


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer") from error
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _mapping_list(
    value: Mapping[str, object],
    key: str,
) -> Tuple[Mapping[str, object], ...]:
    items = value.get(key, [])
    if not isinstance(items, list):
        raise ValueError(f"GitHub response {key} must be a list")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"GitHub response {key} items must be objects")
    return tuple(item for item in items if isinstance(item, dict))


def _dedupe_blockers(
    blockers: Sequence[IntakeBlocker],
) -> Tuple[IntakeBlocker, ...]:
    return tuple(
        {
            (item.code, item.message, item.action): item
            for item in blockers
        }.values()
    )


def _write_json_atomically(path, value: Mapping[str, object]) -> None:
    path = Path(path)
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
