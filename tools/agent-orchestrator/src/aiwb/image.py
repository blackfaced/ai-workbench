from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Tuple

from .project import ImageProfile


class ImageBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageBuildRequest:
    profile: ImageProfile
    cwd: Path
    run_id: str
    artifact_dir: Path


@dataclass(frozen=True)
class ImageBuildResult:
    digest: str
    artifacts: Tuple[str, ...]


class CommandImageBuilder:
    """Drive an external asynchronous image builder through approved commands."""

    def start(self, request: ImageBuildRequest) -> str:
        payload = self._run(request, "start", request.profile.start_command, "")
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", operation_id
        ):
            raise ImageBuildError("image start must return a valid operation_id")
        return operation_id

    def status(self, request: ImageBuildRequest, operation_id: str) -> str:
        payload = self._run(
            request,
            "status",
            request.profile.status_command,
            operation_id,
        )
        status = payload.get("status")
        if status not in {"queued", "running", "succeeded", "failed"}:
            raise ImageBuildError("image status must be queued, running, succeeded, or failed")
        if status == "failed":
            detail = payload.get("detail")
            raise ImageBuildError(
                f"image build {operation_id!r} failed: {detail or 'no detail'}"
            )
        return str(status)

    def result(
        self,
        request: ImageBuildRequest,
        operation_id: str,
    ) -> ImageBuildResult:
        payload = self._run(
            request,
            "result",
            request.profile.result_command,
            operation_id,
        )
        digest = payload.get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ImageBuildError(
                "image result must return an immutable sha256:<64 lowercase hex> digest"
            )
        artifacts_value = payload.get("artifacts", [])
        if not isinstance(artifacts_value, list) or not all(
            isinstance(item, str) and item for item in artifacts_value
        ):
            raise ImageBuildError("image result artifacts must be a string list")
        local_artifacts = tuple(
            str(path) for path in sorted(request.artifact_dir.glob("*.log"))
        )
        return ImageBuildResult(
            digest=digest,
            artifacts=tuple(artifacts_value) + local_artifacts,
        )

    @staticmethod
    def _run(
        request: ImageBuildRequest,
        operation: str,
        command: Tuple[str, ...],
        operation_id: str,
    ) -> Mapping[str, object]:
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        sequence = len(tuple(request.artifact_dir.glob("*.stdout.log"))) + 1
        prefix = request.artifact_dir / f"{sequence:03d}-{operation}"
        environment = os.environ.copy()
        environment.update(
            {
                "AIWB_IMAGE_OPERATION_ID": operation_id,
                "AIWB_IMAGE_PROFILE": request.profile.name,
                "AIWB_IMAGE_STATE_DIR": str(request.artifact_dir),
                "AIWB_RUN_ID": request.run_id,
            }
        )
        completed = subprocess.run(
            list(command),
            cwd=str(request.cwd),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        prefix.with_suffix(".stdout.log").write_text(
            completed.stdout,
            encoding="utf-8",
        )
        prefix.with_suffix(".stderr.log").write_text(
            completed.stderr,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ImageBuildError(
                f"image {operation} command failed with code {completed.returncode}: {detail}"
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise ImageBuildError(f"image {operation} command returned no JSON result")
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise ImageBuildError(
                f"image {operation} command returned invalid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ImageBuildError(f"image {operation} result must be a JSON mapping")
        return payload
