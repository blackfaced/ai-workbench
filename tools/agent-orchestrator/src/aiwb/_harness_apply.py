from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Optional, Sequence, Tuple

import yaml

from .evidence import EvidenceReference, EvidenceStore

if TYPE_CHECKING:
    from .harness_setup import HarnessPlan


@dataclass(frozen=True)
class HarnessFileProjection:
    path: str
    content: str
    executable: bool = False
    previous_sha256: str = ""

    def to_dict(self) -> Mapping[str, object]:
        return {
            "path": self.path,
            "content": self.content,
            "executable": self.executable,
            "previous_sha256": self.previous_sha256,
            "sha256": hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True)
class HarnessProbeCommand:
    name: str
    argv: Tuple[str, ...]
    source_argv: Tuple[str, ...]
    working_directory: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "source_argv": list(self.source_argv),
            "working_directory": self.working_directory,
        }


@dataclass(frozen=True)
class HarnessApplyPreview:
    state: str
    repository: str
    plan_digest: str
    base_commit: str
    state_dir: str
    branch: str
    worktree: str
    files: Tuple[HarnessFileProjection, ...]
    dependencies: Tuple[str, ...]
    commands: Tuple[HarnessProbeCommand, ...]
    side_effects: Tuple[str, ...]
    digest: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "state": self.state,
            "repository": self.repository,
            "plan_digest": self.plan_digest,
            "base_commit": self.base_commit,
            "state_dir": self.state_dir,
            "branch": self.branch,
            "worktree": self.worktree,
            "files": [item.to_dict() for item in self.files],
            "dependencies": list(self.dependencies),
            "commands": [item.to_dict() for item in self.commands],
            "side_effects": list(self.side_effects),
            "digest": self.digest,
        }


@dataclass(frozen=True)
class HarnessApplyApproval:
    status: str
    approved_by: str
    approved_at: str
    artifact_path: str
    preview: HarnessApplyPreview

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "artifact_path": self.artifact_path,
            "preview": self.preview.to_dict(),
        }


@dataclass(frozen=True)
class HarnessProbeEvidence:
    name: str
    command: Tuple[str, ...]
    working_directory: str
    returncode: int
    stdout: str
    stderr: str
    recorded_at: str
    duration_seconds: float
    artifacts: Tuple[str, ...] = ()
    stdout_ref: Optional[EvidenceReference] = None
    stderr_ref: Optional[EvidenceReference] = None

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "working_directory": self.working_directory,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "recorded_at": self.recorded_at,
            "duration_seconds": self.duration_seconds,
            "artifacts": list(self.artifacts),
            "stdout_ref": _reference_dict(self.stdout_ref),
            "stderr_ref": _reference_dict(self.stderr_ref),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HarnessProbeEvidence":
        command = value.get("command", [])
        artifacts = value.get("artifacts", [])
        if not isinstance(command, list) or not all(
            isinstance(item, str) for item in command
        ):
            raise ValueError("Harness Evidence command must be a string list")
        if not isinstance(artifacts, list) or not all(
            isinstance(item, str) for item in artifacts
        ):
            raise ValueError("Harness Evidence artifacts must be a string list")
        return cls(
            name=str(value.get("name", "")),
            command=tuple(command),
            working_directory=str(value.get("working_directory", "")),
            returncode=int(value.get("returncode", 0)),
            stdout=str(value.get("stdout", "")),
            stderr=str(value.get("stderr", "")),
            recorded_at=str(value.get("recorded_at", "")),
            duration_seconds=float(value.get("duration_seconds", 0)),
            artifacts=tuple(artifacts),
            stdout_ref=_reference_from_dict(value.get("stdout_ref")),
            stderr_ref=_reference_from_dict(value.get("stderr_ref")),
        )


@dataclass(frozen=True)
class HarnessApplyResult:
    status: str
    changed: bool
    repository: str
    branch: str
    worktree: str
    base_commit: str
    candidate_commit: str
    evidence: Tuple[HarnessProbeEvidence, ...]
    consumption: Mapping[str, object]
    report_path: str
    cleanup_status: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "changed": self.changed,
            "repository": self.repository,
            "branch": self.branch,
            "worktree": self.worktree,
            "base_commit": self.base_commit,
            "candidate_commit": self.candidate_commit,
            "evidence": [item.to_dict() for item in self.evidence],
            "consumption": dict(self.consumption),
            "report_path": self.report_path,
            "cleanup_status": self.cleanup_status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HarnessApplyResult":
        evidence = value.get("evidence", [])
        consumption = value.get("consumption", {})
        if not isinstance(evidence, list) or not all(
            isinstance(item, dict) for item in evidence
        ):
            raise ValueError("Harness Apply evidence must be an object list")
        if not isinstance(consumption, dict):
            raise ValueError("Harness Apply consumption must be an object")
        return cls(
            status=str(value.get("status", "")),
            changed=bool(value.get("changed", False)),
            repository=str(value.get("repository", "")),
            branch=str(value.get("branch", "")),
            worktree=str(value.get("worktree", "")),
            base_commit=str(value.get("base_commit", "")),
            candidate_commit=str(value.get("candidate_commit", "")),
            evidence=tuple(
                HarnessProbeEvidence.from_dict(item)
                for item in evidence
                if isinstance(item, dict)
            ),
            consumption=dict(consumption),
            report_path=str(value.get("report_path", "")),
            cleanup_status=str(value.get("cleanup_status", "")),
        )


def preview_python_l0_apply(
    plan: "HarnessPlan",
    *,
    base_commit: str,
    state_dir: Path,
    command_names: Sequence[str],
) -> HarnessApplyPreview:
    if plan.approval.status != "approved":
        raise ValueError("Apply preview requires an approved Harness Plan")
    if plan.request.planning_mode != "python-l0":
        raise ValueError("Apply preview requires a Python L0 Harness Plan")
    repository = Path(plan.request.repository).expanduser().resolve()
    state_dir = Path(state_dir).expanduser().resolve()
    try:
        state_dir.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Apply state directory must stay outside the target repository")
    base_commit = _resolve_commit(repository, base_commit)
    selected = _select_commands(plan, command_names)
    files, commands = _render_projections(repository, base_commit, selected)
    side_effects = (
        "create candidate branch from the explicit base commit",
        "create isolated candidate worktree under the selected state directory",
        "write and commit the exact approved projection files",
        "execute only the selected project-owned local probe commands",
        "retain the candidate worktree and external report on success or failure",
        "do not modify or merge the target branch",
    )
    plan_digest = _digest(plan.to_dict())
    intent = {
        "repository": str(repository),
        "plan_digest": plan_digest,
        "base_commit": base_commit,
        "state_dir": str(state_dir),
        "files": [item.to_dict() for item in files],
        "dependencies": [],
        "commands": [item.to_dict() for item in commands],
        "side_effects": list(side_effects),
    }
    digest = _digest(intent)
    branch = f"aiwb/harness-setup/{base_commit[:8]}-{digest[:10]}"
    worktree = state_dir / "worktrees" / "harness-setup" / digest[:16]
    return HarnessApplyPreview(
        state="awaiting_apply_approval",
        repository=str(repository),
        plan_digest=plan_digest,
        base_commit=base_commit,
        state_dir=str(state_dir),
        branch=branch,
        worktree=str(worktree),
        files=files,
        dependencies=(),
        commands=commands,
        side_effects=side_effects,
        digest=digest,
    )


def approve_python_l0_apply(
    preview: HarnessApplyPreview,
    *,
    approved_by: str,
    artifact_path: Path,
    approved_at: Optional[datetime] = None,
) -> HarnessApplyApproval:
    if preview.state != "awaiting_apply_approval":
        raise ValueError("Apply Approval requires an awaiting_apply_approval preview")
    if not approved_by.strip():
        raise ValueError("Apply Approval requires an approver")
    _validate_preview_digest(preview)
    artifact_path = Path(artifact_path).expanduser().resolve()
    repository = Path(preview.repository)
    try:
        artifact_path.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ValueError("Apply Approval artifact must stay outside the target repository")
    if artifact_path.exists():
        raise ValueError(f"Apply Approval artifact already exists: {artifact_path}")
    approved_at = approved_at or datetime.now(timezone.utc)
    approval = HarnessApplyApproval(
        status="approved",
        approved_by=approved_by.strip(),
        approved_at=approved_at.astimezone(timezone.utc).isoformat(),
        artifact_path=str(artifact_path),
        preview=preview,
    )
    _write_json_atomically(artifact_path, approval.to_dict())
    return approval


def load_python_l0_apply_approval(
    preview: HarnessApplyPreview,
    artifact_path: Path,
) -> HarnessApplyApproval:
    artifact_path = Path(artifact_path).expanduser().resolve()
    data = _read_json_mapping(artifact_path, "Apply Approval")
    approval = HarnessApplyApproval(
        status=str(data.get("status", "")),
        approved_by=str(data.get("approved_by", "")),
        approved_at=str(data.get("approved_at", "")),
        artifact_path=str(data.get("artifact_path", "")),
        preview=preview,
    )
    if approval.status != "approved":
        raise ValueError("Apply Approval artifact is not approved")
    if approval.artifact_path != str(artifact_path):
        raise ValueError("Apply Approval artifact path does not match its content")
    if approval.to_dict() != data:
        raise ValueError("Apply Approval artifact does not match the current exact preview")
    _validate_preview_digest(preview)
    return approval


def apply_python_l0(
    plan: "HarnessPlan",
    approval: HarnessApplyApproval,
    *,
    state_dir: Path,
) -> HarnessApplyResult:
    if plan.approval.status != "approved":
        raise ValueError("Candidate Apply requires an approved Harness Plan")
    if approval.status != "approved":
        raise ValueError("Candidate Apply requires exact Apply Approval")
    preview = approval.preview
    _validate_preview_digest(preview)
    if preview.plan_digest != _digest(plan.to_dict()):
        raise ValueError("Apply Approval does not match the approved Harness Plan")
    state_dir = Path(state_dir).expanduser().resolve()
    if str(state_dir) != preview.state_dir:
        raise ValueError("Apply state directory does not match the approved preview")
    repository = Path(preview.repository)
    worktree = Path(preview.worktree)
    _ensure_candidate_worktree(
        repository=repository,
        worktree=worktree,
        branch=preview.branch,
        base_commit=preview.base_commit,
        files=preview.files,
    )
    changed = _write_projections(worktree, preview.files)
    if changed:
        _git(worktree, "add", "-A")
        _git(
            worktree,
            "commit",
            "-m",
            "chore: configure Python L0 Harness",
            "-m",
            "Co-authored-by: TRAE CLI <noreply@bytedance.com>",
        )
    candidate_commit = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    evidence = []
    evidence_store = EvidenceStore(state_dir)
    started = time.monotonic()
    for command in preview.commands:
        command_started = time.monotonic()
        completed = subprocess.run(
            list(command.argv),
            cwd=str(worktree),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
        stdout, stdout_ref = evidence_store.retain_text(
            completed.stdout,
            label=f"harness-setup/{preview.digest}/{command.name}/stdout",
        )
        stderr, stderr_ref = evidence_store.retain_text(
            completed.stderr,
            label=f"harness-setup/{preview.digest}/{command.name}/stderr",
        )
        evidence.append(
            HarnessProbeEvidence(
                name=command.name,
                command=command.argv,
                working_directory=".",
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                recorded_at=_now(),
                duration_seconds=time.monotonic() - command_started,
                artifacts=_retain_probe_artifacts(
                    worktree,
                    state_dir,
                    preview.digest,
                    command.name,
                ),
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
            )
        )
        if completed.returncode != 0:
            break
    status = (
        "configured_local"
        if evidence and all(item.returncode == 0 for item in evidence)
        else "failed_local"
    )
    consumption = {
        "probe_executions": len(evidence),
        "probe_seconds": time.monotonic() - started,
    }
    report_path = (
        state_dir
        / "reports"
        / "harness-setup"
        / preview.digest
        / "report.json"
    )
    result = HarnessApplyResult(
        status=status,
        changed=changed,
        repository=str(repository),
        branch=preview.branch,
        worktree=str(worktree),
        base_commit=preview.base_commit,
        candidate_commit=candidate_commit,
        evidence=tuple(evidence),
        consumption=consumption,
        report_path=str(report_path),
        cleanup_status="not_required",
    )
    _write_json_atomically(report_path, result.to_dict())
    return result


def _select_commands(
    plan: "HarnessPlan",
    command_names: Sequence[str],
) -> Tuple[object, ...]:
    if not command_names:
        raise ValueError("Apply preview requires at least one canonical command")
    selected = []
    for requested in command_names:
        matches = tuple(
            candidate
            for candidate in plan.command_candidates
            if candidate.name == requested
            or candidate.name.rsplit(":", 1)[-1] == requested
        )
        if len(matches) != 1:
            raise ValueError(
                f"canonical command name must resolve exactly once: {requested}"
            )
        candidate = matches[0]
        disposition = _candidate_disposition(plan, candidate.name)
        if disposition not in {"keep", "augment"}:
            raise ValueError(
                f"canonical command is not locally configured: {candidate.name}"
            )
        selected.append(candidate)
    return tuple(selected)


def _candidate_disposition(plan: "HarnessPlan", name: str) -> str:
    target_path, separator, capability_name = name.rpartition(":")
    if not separator:
        target_path = "."
        capability_name = name
    profile = plan.assessment.project_profile
    if profile is None:
        return ""
    for target in profile.targets:
        if target.path != target_path:
            continue
        for capability in target.capabilities:
            if capability.name == capability_name:
                return capability.disposition
    return ""


def _render_projections(
    repository: Path,
    base_commit: str,
    selected: Sequence[object],
) -> Tuple[Tuple[HarnessFileProjection, ...], Tuple[HarnessProbeCommand, ...]]:
    wrappers = []
    probe_commands = []
    approved_commands = {}
    canonical_lines = []
    pipeline_lines = []
    for candidate in selected:
        safe_name = _safe_name(candidate.name)
        source_argv = tuple(candidate.argv)
        if safe_name == "unit" and "pytest" in source_argv:
            source_argv = source_argv + ("-s", "--junitxml=junit.xml")
        wrapper_path = f".ai-workbench/commands/{safe_name}.sh"
        wrapper = _wrapper_content(
            working_directory=candidate.working_directory,
            argv=source_argv,
        )
        wrappers.append(
            HarnessFileProjection(
                path=wrapper_path,
                content=wrapper,
                executable=True,
            )
        )
        canonical = ("bash", wrapper_path)
        approved_commands[safe_name] = {
            "argv": list(canonical),
            "approved": True,
        }
        probe_commands.append(
            HarnessProbeCommand(
                name=safe_name,
                argv=canonical,
                source_argv=source_argv,
                working_directory=candidate.working_directory,
            )
        )
        rendered = shlex.join(canonical)
        canonical_lines.append(f"- `{rendered}`")
        pipeline_lines.append(f"      - run: {rendered}")
    workflow = {
        "schema_version": 1,
        "status": "approved",
        "project": {"root": str(repository), "trusted": True},
        "capabilities": {"commands": approved_commands, "skills": {}},
        "harness": {"allowed_kubernetes_contexts": [], "profiles": {}},
        "images": {"profiles": {}},
    }
    guide = (
        "# Project Harness\n\n"
        "Run only the project-owned canonical commands:\n\n"
        + "\n".join(canonical_lines)
        + "\n\nLocal success means `configured_local`, not pipeline verification.\n"
    )
    skill = (
        "---\n"
        "name: project-harness\n"
        "description: Run the project-owned local Harness commands.\n"
        "---\n\n"
        "# Project Harness\n\n"
        + "\n".join(canonical_lines)
        + "\n\nDo not substitute global commands or production environments.\n"
    )
    pipeline = (
        "name: AI Workbench Harness\n"
        "on:\n"
        "  push:\n"
        "  pull_request:\n"
        "jobs:\n"
        "  harness:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2\n"
        + "\n".join(pipeline_lines)
        + "\n"
    )
    self_test = (
        "from pathlib import Path\n\n"
        "def test_harness_projection_is_consistent():\n"
        "    root = Path(__file__).resolve().parents[2]\n"
        "    workflow = (root / '.ai-workbench/workflow.yaml').read_text()\n"
        "    guide = (root / 'docs/engineering/harness.md').read_text()\n"
        "    pipeline = (root / '.github/workflows/aiwb-harness.yml').read_text()\n"
        f"    commands = {list(shlex.join(item.argv) for item in probe_commands)!r}\n"
        "    for command in commands:\n"
        "        assert command in guide\n"
        "        assert command in pipeline\n"
        "        assert command.split()[-1] in workflow\n"
    )
    files = (
        HarnessFileProjection(
            path=".ai-workbench/workflow.yaml",
            content=yaml.safe_dump(workflow, sort_keys=False),
        ),
        *wrappers,
        HarnessFileProjection(
            path=".github/workflows/aiwb-harness.yml",
            content=pipeline,
        ),
        HarnessFileProjection(
            path=".codex/skills/project-harness/SKILL.md",
            content=skill,
        ),
        HarnessFileProjection(
            path=".claude/skills/project-harness/SKILL.md",
            content=skill,
        ),
        HarnessFileProjection(
            path="docs/engineering/harness.md",
            content=guide,
        ),
        HarnessFileProjection(
            path="tests/aiwb/test_harness_projection.py",
            content=self_test,
        ),
    )
    return (
        tuple(
            replace(
                projection,
                previous_sha256=_base_file_digest(
                    repository,
                    base_commit,
                    projection.path,
                ),
            )
            for projection in files
        ),
        tuple(probe_commands),
    )


def _wrapper_content(
    *,
    working_directory: str,
    argv: Sequence[str],
) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", 'root="$(git rev-parse --show-toplevel)"']
    if working_directory == ".":
        lines.append('cd "$root"')
    else:
        lines.append(f'cd "$root"/{shlex.quote(working_directory)}')
    lines.append(f"exec {shlex.join(tuple(argv))}")
    return "\n".join(lines) + "\n"


def _retain_probe_artifacts(
    worktree: Path,
    state_dir: Path,
    preview_digest: str,
    command_name: str,
) -> Tuple[str, ...]:
    names = {
        "unit": ("junit.xml",),
        "coverage": ("coverage.xml",),
    }.get(command_name, ())
    retained = []
    for name in names:
        source = worktree / name
        if not source.is_file():
            continue
        destination = (
            state_dir
            / "reports"
            / "harness-setup"
            / preview_digest
            / "artifacts"
            / command_name
            / name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomically(destination, source.read_bytes())
        source.unlink()
        retained.append(str(destination))
    return tuple(retained)


def _base_file_digest(repository: Path, commit: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=str(repository),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return ""
    return hashlib.sha256(completed.stdout).hexdigest()


def _reference_dict(
    reference: Optional[EvidenceReference],
) -> Optional[Mapping[str, object]]:
    if reference is None:
        return None
    return {
        "artifact_id": reference.artifact_id,
        "sha256": reference.sha256,
        "size_bytes": reference.size_bytes,
        "media_type": reference.media_type,
        "label": reference.label,
    }


def _reference_from_dict(value: object) -> Optional[EvidenceReference]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Evidence reference must be an object")
    return EvidenceReference(
        artifact_id=str(value.get("artifact_id", "")),
        sha256=str(value.get("sha256", "")),
        size_bytes=int(value.get("size_bytes", 0)),
        media_type=str(value.get("media_type", "")),
        label=str(value.get("label", "")),
    )


def _ensure_candidate_worktree(
    *,
    repository: Path,
    worktree: Path,
    branch: str,
    base_commit: str,
    files: Sequence[HarnessFileProjection],
) -> None:
    if (worktree / ".git").exists():
        actual_branch = _git(worktree, "branch", "--show-current").stdout.strip()
        if actual_branch != branch:
            raise ValueError("existing candidate worktree is on an unexpected branch")
        head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        if head != base_commit and not _candidate_matches_approved_projection(
            worktree,
            base_commit,
            files,
        ):
            raise ValueError(
                "existing candidate worktree is not at the approved base commit "
                "or exact approved projection"
            )
        if _git(worktree, "status", "--porcelain").stdout:
            raise ValueError("existing candidate worktree must be clean")
        return
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch_exists = (
        _git(
            repository,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        ).returncode
        == 0
    )
    if branch_exists:
        branch_head = _git(repository, "rev-parse", branch).stdout.strip()
        if branch_head != base_commit:
            raise ValueError(
                "existing candidate branch is not at the approved base commit"
            )
        _git(repository, "worktree", "add", str(worktree), branch)
    else:
        _git(
            repository,
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree),
            base_commit,
        )


def _write_projections(
    worktree: Path,
    files: Sequence[HarnessFileProjection],
) -> bool:
    _validate_projection_destinations(worktree, files)
    changed = False
    for projection in files:
        relative = Path(projection.path)
        destination = worktree / relative
        encoded = projection.content.encode("utf-8")
        if destination.is_file() and destination.read_bytes() == encoded:
            if projection.executable:
                destination.chmod(destination.stat().st_mode | 0o100)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomically(destination, encoded)
        if projection.executable:
            destination.chmod(0o755)
        changed = True
    return changed


def _validate_projection_destinations(
    worktree: Path,
    files: Sequence[HarnessFileProjection],
) -> None:
    for projection in files:
        relative = Path(projection.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                f"projection path must stay inside the candidate: {projection.path}"
            )
        destination = worktree / projection.path
        try:
            destination.resolve().relative_to(worktree.resolve())
        except ValueError as error:
            raise ValueError(
                f"projection path must stay inside the candidate: {projection.path}"
            ) from error


def _candidate_matches_approved_projection(
    worktree: Path,
    base_commit: str,
    files: Sequence[HarnessFileProjection],
) -> bool:
    try:
        _validate_projection_destinations(worktree, files)
    except ValueError:
        return False
    changed = {
        path
        for path in _git(
            worktree,
            "diff",
            "--name-only",
            f"{base_commit}..HEAD",
        ).stdout.splitlines()
        if path
    }
    if changed != {projection.path for projection in files}:
        return False
    for projection in files:
        destination = worktree / projection.path
        if not destination.is_file():
            return False
        if destination.read_text(encoding="utf-8") != projection.content:
            return False
    return True


def _validate_preview_digest(preview: HarnessApplyPreview) -> None:
    intent = {
        "repository": preview.repository,
        "plan_digest": preview.plan_digest,
        "base_commit": preview.base_commit,
        "state_dir": preview.state_dir,
        "files": [item.to_dict() for item in preview.files],
        "dependencies": list(preview.dependencies),
        "commands": [item.to_dict() for item in preview.commands],
        "side_effects": list(preview.side_effects),
    }
    if preview.digest != _digest(intent):
        raise ValueError("Apply preview digest does not match its exact envelope")


def _resolve_commit(repository: Path, value: str) -> str:
    if not value:
        raise ValueError("Apply preview requires an explicit base commit")
    resolved = _git(
        repository,
        "rev-parse",
        "--verify",
        f"{value}^{{commit}}",
        check=False,
    )
    if resolved.returncode != 0:
        raise ValueError(f"base commit is not available: {value}")
    commit = resolved.stdout.strip()
    if value != commit:
        raise ValueError("base commit must be an explicit full commit hash")
    return commit


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "command"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(
    cwd: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write_json_atomically(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_bytes_atomically(path, encoded)


def _read_json_mapping(path: Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
