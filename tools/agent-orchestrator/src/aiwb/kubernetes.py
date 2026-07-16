from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from .browser import (
    BrowserDiagnosticAdapter,
    BrowserDiagnosticRequest,
    BrowserDiagnosticResult,
)
from .harness import HarnessError, HarnessExecution, HarnessRequest


@dataclass(frozen=True)
class JanitorReport:
    scanned: int
    cleaned: int
    failed: int
    retained: int


class KubernetesHarness:
    """Run a gate in an isolated, project-provisioned non-production namespace."""

    def __init__(
        self,
        state_dir: Path,
        browser_diagnostics: Optional[BrowserDiagnosticAdapter] = None,
    ) -> None:
        self._lease_dir = Path(state_dir).resolve() / "kubernetes-leases"
        self._lease_dir.mkdir(parents=True, exist_ok=True)
        self._browser_diagnostics = browser_diagnostics

    def execute(self, request: HarnessRequest) -> HarnessExecution:
        profile = request.profile
        namespace = _namespace(
            profile.namespace_prefix,
            request.run_id,
            request.execution_id,
        )
        artifact_dir = request.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        expires_at = int(time.time()) + profile.ttl_seconds
        environment = _environment(request, namespace, expires_at)
        lease_path = self._lease_dir / f"{namespace}.json"
        lease: Dict[str, object] = {
            "cleanup_command": list(profile.cleanup_command),
            "context": profile.kubernetes_context,
            "cwd": str(request.cwd),
            "expires_at": expires_at,
            "namespace": namespace,
            "run_id": request.run_id,
            "artifact_dir": str(artifact_dir),
            "coordinates": _durable_coordinates(environment),
            "status": "active",
        }
        _write_json(lease_path, lease)

        collected_artifacts: Tuple[str, ...] = tuple()
        browser_diagnostic = None
        provisioned = False
        try:
            provision = _run_json_command(
                "provision",
                profile.provision_command,
                request.cwd,
                environment,
                artifact_dir,
            )
            base_url = _base_url(provision)
            provisioned = True
            environment["AIWB_BASE_URL"] = base_url
            completed = subprocess.run(
                list(request.command),
                cwd=str(request.cwd),
                env=environment,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=request.timeout_seconds,
            )
            if (
                completed.returncode != 0
                and request.stage != "red"
                and profile.browser_diagnostic is not None
                and self._browser_diagnostics is not None
            ):
                diagnostic_dir = artifact_dir / "browser-diagnostic"
                diagnostic_dir.mkdir(parents=True, exist_ok=True)
                diagnostic_request = BrowserDiagnosticRequest(
                    profile=profile.browser_diagnostic,
                    base_url=base_url,
                    cwd=request.cwd,
                    artifact_dir=diagnostic_dir,
                    run_id=request.run_id,
                    execution_id=request.execution_id,
                    gate_stdout=completed.stdout,
                    gate_stderr=completed.stderr,
                )
                try:
                    browser_diagnostic = self._browser_diagnostics.diagnose(
                        diagnostic_request
                    )
                except Exception as error:
                    browser_diagnostic = BrowserDiagnosticResult(
                        adapter=profile.browser_diagnostic.adapter,
                        summary="browser diagnostic failed",
                        artifacts=tuple(
                            str(path)
                            for path in sorted(diagnostic_dir.iterdir())
                            if path.is_file()
                        ),
                        error=str(error),
                    )
            collected = _run_json_command(
                "collect",
                profile.collect_command,
                request.cwd,
                environment,
                artifact_dir,
            )
            collected_artifacts = _artifacts(collected)
        finally:
            try:
                _run_json_command(
                    "cleanup",
                    profile.cleanup_command,
                    request.cwd,
                    environment,
                    artifact_dir,
                )
            except Exception as error:
                lease["status"] = "cleanup_pending"
                lease["last_error"] = str(error)
                _write_json(lease_path, lease)
                raise
            else:
                lease_path.unlink(missing_ok=True)

        if not provisioned:
            raise HarnessError("Kubernetes Harness did not provision a target")
        logs = tuple(str(path) for path in sorted(artifact_dir.glob("*.log")))
        return HarnessExecution(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            base_url=base_url,
            artifacts=collected_artifacts + logs,
            environment=(
                f"{profile.environment}/{profile.kubernetes_context}/{namespace}"
            ),
            browser_diagnostic=browser_diagnostic,
        )


class KubernetesJanitor:
    """Retry failed cleanup and reclaim expired Kubernetes Harness leases."""

    def __init__(
        self,
        state_dir: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._lease_dir = Path(state_dir).resolve() / "kubernetes-leases"
        self._lease_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock

    def sweep(self) -> JanitorReport:
        scanned = 0
        cleaned = 0
        failed = 0
        retained = 0
        for lease_path in sorted(self._lease_dir.glob("*.json")):
            scanned += 1
            try:
                lease = _read_lease(lease_path)
                due = (
                    lease.get("status") == "cleanup_pending"
                    or int(lease["expires_at"]) <= int(self._clock())
                )
                if not due:
                    retained += 1
                    continue
                environment = os.environ.copy()
                environment.update(lease["coordinates"])
                _run_json_command(
                    "janitor-cleanup",
                    tuple(lease["cleanup_command"]),
                    Path(lease["cwd"]),
                    environment,
                    Path(lease["artifact_dir"]),
                )
            except Exception as error:
                failed += 1
                _mark_cleanup_pending(lease_path, str(error))
            else:
                lease_path.unlink(missing_ok=True)
                cleaned += 1
        return JanitorReport(
            scanned=scanned,
            cleaned=cleaned,
            failed=failed,
            retained=retained,
        )


def _namespace(prefix: str, run_id: str, execution_id: str) -> str:
    readable_run = re.sub(r"[^a-z0-9-]+", "-", run_id.lower()).strip("-")
    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:8]
    run_limit = 63 - len(prefix) - len(digest) - 2
    readable_run = readable_run[:run_limit].rstrip("-") or "run"
    return f"{prefix}-{readable_run}-{digest}"


def _environment(
    request: HarnessRequest,
    namespace: str,
    expires_at: int,
) -> Dict[str, str]:
    profile = request.profile
    environment = os.environ.copy()
    labels = {
        "ai-workbench.dev/managed-by": "agent-orchestrator",
        "ai-workbench.dev/run-id": request.run_id,
        "ai-workbench.dev/expires-at": str(expires_at),
    }
    environment.update(
        {
            "AIWB_ARTIFACT_DIR": str(request.artifact_dir),
            "AIWB_BASE_URL": "",
            "AIWB_HARNESS_PROFILE": profile.name,
            "AIWB_K8S_CONTEXT": profile.kubernetes_context,
            "AIWB_K8S_EXPIRES_AT": str(expires_at),
            "AIWB_K8S_LABELS": json.dumps(labels, sort_keys=True),
            "AIWB_K8S_NAMESPACE": namespace,
            "AIWB_K8S_TTL_SECONDS": str(profile.ttl_seconds),
            "AIWB_RUN_ID": request.run_id,
        }
    )
    return environment


def _durable_coordinates(environment: Mapping[str, str]) -> Dict[str, str]:
    keys = (
        "AIWB_ARTIFACT_DIR",
        "AIWB_BASE_URL",
        "AIWB_HARNESS_PROFILE",
        "AIWB_K8S_CONTEXT",
        "AIWB_K8S_EXPIRES_AT",
        "AIWB_K8S_LABELS",
        "AIWB_K8S_NAMESPACE",
        "AIWB_K8S_TTL_SECONDS",
        "AIWB_RUN_ID",
    )
    return {key: environment[key] for key in keys}


def _run_json_command(
    operation: str,
    command: Tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    artifact_dir: Path,
) -> Mapping[str, object]:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (artifact_dir / f"{operation}.stdout.log").write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (artifact_dir / f"{operation}.stderr.log").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise HarnessError(
            f"Kubernetes Harness {operation} failed with code "
            f"{completed.returncode}: {detail}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise HarnessError(f"Kubernetes Harness {operation} returned no JSON")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise HarnessError(
            f"Kubernetes Harness {operation} returned invalid JSON"
        ) from error
    if not isinstance(payload, dict):
        raise HarnessError(f"Kubernetes Harness {operation} must return a JSON mapping")
    return payload


def _base_url(payload: Mapping[str, object]) -> str:
    value = payload.get("base_url")
    if not isinstance(value, str):
        raise HarnessError("Kubernetes Harness provision must return base_url")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HarnessError("Kubernetes Harness base_url must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise HarnessError("Kubernetes Harness base_url must not contain credentials")
    return value.rstrip("/")


def _artifacts(payload: Mapping[str, object]) -> Tuple[str, ...]:
    value = payload.get("artifacts", [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise HarnessError("Kubernetes Harness artifacts must be a string list")
    return tuple(value)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(str(temporary), str(path))


def _read_lease(path: Path) -> Dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError(f"Kubernetes lease must be a mapping: {path}")
    command = value.get("cleanup_command")
    coordinates = value.get("coordinates")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
        or not isinstance(coordinates, dict)
        or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in coordinates.items()
        )
    ):
        raise HarnessError(f"Kubernetes lease is invalid: {path}")
    for key in ("artifact_dir", "cwd", "expires_at"):
        if key not in value:
            raise HarnessError(f"Kubernetes lease is missing {key}: {path}")
    return value


def _mark_cleanup_pending(path: Path, detail: str) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(value, dict):
        return
    value["status"] = "cleanup_pending"
    value["last_error"] = detail
    attempts = value.get("cleanup_attempts", 0)
    value["cleanup_attempts"] = int(attempts) + 1 if isinstance(attempts, int) else 1
    _write_json(path, value)
