from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .project import CandidatePublishProfile


class CandidatePublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidatePublishRequest:
    repository: Path
    branch: str
    commit: str
    profile: CandidatePublishProfile


@dataclass(frozen=True)
class CandidatePublishResult:
    remote: str
    ref: str
    commit: str


class CandidatePublisher:
    """Publish an exact Candidate commit without owning merge or retry policy."""

    def publish(self, request: CandidatePublishRequest) -> CandidatePublishResult:
        if not request.branch.startswith(request.profile.branch_prefix):
            raise CandidatePublishError(
                "Candidate branch is outside the policy-approved namespace"
            )
        ref = f"refs/heads/{request.branch}"
        self._git(request.repository, "check-ref-format", ref)
        self._git(
            request.repository,
            "push",
            "--porcelain",
            request.profile.remote,
            f"{request.commit}:{ref}",
        )
        remote_commit = self._remote_commit(
            request.repository,
            request.profile.remote,
            ref,
        )
        if remote_commit != request.commit:
            raise CandidatePublishError(
                f"remote ref verification failed: expected {request.commit}, got {remote_commit}"
            )
        return CandidatePublishResult(
            remote=request.profile.remote,
            ref=ref,
            commit=request.commit,
        )

    def _remote_commit(self, repository: Path, remote: str, ref: str) -> str:
        output = self._git(repository, "ls-remote", "--refs", remote, ref).stdout
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) != 1:
            raise CandidatePublishError(
                f"remote ref verification returned {len(lines)} refs"
            )
        return lines[0].split(maxsplit=1)[0]

    @staticmethod
    def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=str(repository),
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as error:
            detail = "\n".join(
                part.strip()
                for part in (error.stdout, error.stderr)
                if part and part.strip()
            ) or str(error)
            raise CandidatePublishError(f"Candidate push failed: {detail}") from error
