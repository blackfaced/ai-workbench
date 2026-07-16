from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .agent import AgentAdapter, AgentRequest, AgentResult


class MergeConflictRepairError(RuntimeError):
    pass


@dataclass(frozen=True)
class MergeConflictRepairRequest:
    worktree: Path
    todo_id: str
    prompt: str
    conflict_paths: Tuple[str, ...]
    provider: str
    model: Optional[str]
    timeout_seconds: int


@dataclass(frozen=True)
class MergeConflictRepairResult:
    agent_result: AgentResult
    merge_commit: str


class MergeConflictRepairer:
    """Resolve and commit one in-progress Candidate merge through a fresh Agent."""

    def __init__(self, agent: AgentAdapter) -> None:
        self._agent = agent

    def repair(self, request: MergeConflictRepairRequest) -> MergeConflictRepairResult:
        expected = set(request.conflict_paths)
        if not expected or set(self._unmerged_paths(request.worktree)) != expected:
            raise MergeConflictRepairError("Candidate merge is not in the expected conflict state")
        staged_before = set(self._staged_paths(request.worktree))
        result = self._agent.run(
            AgentRequest(
                role="conflict_repairer",
                prompt=request.prompt,
                worktree=str(request.worktree),
                todo_id=request.todo_id,
                provider=request.provider,
                model=request.model,
                timeout_seconds=request.timeout_seconds,
            )
        )
        staged_after = set(self._staged_paths(request.worktree))
        unexpected_staged = staged_after - staged_before - expected
        if unexpected_staged:
            raise MergeConflictRepairError(
                "Conflict repairer staged unexpected paths: "
                + ", ".join(sorted(unexpected_staged))
            )
        changed_paths = set(self._unstaged_paths(request.worktree)) | set(
            self._untracked_paths(request.worktree)
        )
        unexpected_changed = changed_paths - expected
        if unexpected_changed:
            raise MergeConflictRepairError(
                "Conflict repairer changed unexpected paths: "
                + ", ".join(sorted(unexpected_changed))
            )
        self._git(request.worktree, "add", "--", *request.conflict_paths)
        unresolved = self._unmerged_paths(request.worktree)
        if unresolved:
            raise MergeConflictRepairError(
                "Conflict repairer left unresolved paths: " + ", ".join(unresolved)
            )
        self._git(request.worktree, "commit", "--no-edit")
        return MergeConflictRepairResult(
            agent_result=result,
            merge_commit=self._git(request.worktree, "rev-parse", "HEAD").stdout.strip(),
        )

    @classmethod
    def _unmerged_paths(cls, worktree: Path) -> Tuple[str, ...]:
        return cls._paths(worktree, "diff", "--name-only", "--diff-filter=U")

    @classmethod
    def _staged_paths(cls, worktree: Path) -> Tuple[str, ...]:
        return cls._paths(worktree, "diff", "--cached", "--name-only")

    @classmethod
    def _unstaged_paths(cls, worktree: Path) -> Tuple[str, ...]:
        return cls._paths(worktree, "diff", "--name-only")

    @classmethod
    def _untracked_paths(cls, worktree: Path) -> Tuple[str, ...]:
        return cls._paths(worktree, "ls-files", "--others", "--exclude-standard")

    @classmethod
    def _paths(cls, worktree: Path, *arguments: str) -> Tuple[str, ...]:
        output = cls._git(worktree, *arguments, "-z").stdout
        return tuple(path for path in output.split("\0") if path)

    @staticmethod
    def _git(worktree: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=str(worktree),
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
            raise MergeConflictRepairError(f"Conflict repair Git command failed: {detail}") from error
