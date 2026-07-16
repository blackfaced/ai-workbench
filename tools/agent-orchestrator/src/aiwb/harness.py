from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, Tuple
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from .project import HarnessProfile


class HarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class HarnessExecution:
    returncode: int
    stdout: str
    stderr: str
    base_url: str
    artifacts: Tuple[str, ...]
    environment: str = ""


@dataclass(frozen=True)
class HarnessRequest:
    profile: HarnessProfile
    command: Tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    run_id: str
    artifact_dir: Path
    execution_id: str = ""


class HarnessAdapter(Protocol):
    def execute(self, request: HarnessRequest) -> HarnessExecution:
        ...


class LocalProcessHarness:
    """Run one command against a disposable loopback service."""

    def execute(self, request: HarnessRequest) -> HarnessExecution:
        profile = request.profile
        port = _available_port()
        ready_url = profile.ready_url.format(port=port)
        parsed = urlsplit(ready_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        artifact_dir = request.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        service_stdout = artifact_dir / "service.stdout.log"
        service_stderr = artifact_dir / "service.stderr.log"
        environment = _environment(
            profile=profile,
            port=port,
            base_url=base_url,
            run_id=request.run_id,
            artifact_dir=artifact_dir,
        )

        with service_stdout.open("w", encoding="utf-8") as stdout_file, service_stderr.open(
            "w", encoding="utf-8"
        ) as stderr_file:
            process = subprocess.Popen(
                list(profile.start_command),
                cwd=str(request.cwd),
                env=environment,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
            try:
                _wait_until_ready(process, ready_url, profile.ready_timeout_seconds)
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
            except HarnessError as error:
                raise HarnessError(
                    f"{error}; service logs: {service_stdout}, {service_stderr}"
                ) from error
            finally:
                _terminate_process_group(process)

        return HarnessExecution(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            base_url=base_url,
            artifacts=(str(service_stdout), str(service_stderr)),
            environment=profile.environment,
        )


def _environment(
    profile: HarnessProfile,
    port: int,
    base_url: str,
    run_id: str,
    artifact_dir: Path,
) -> Mapping[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "AIWB_ARTIFACT_DIR": str(artifact_dir),
            "AIWB_BASE_URL": base_url,
            "AIWB_HARNESS_PROFILE": profile.name,
            "AIWB_PORT": str(port),
            "AIWB_RUN_ID": run_id,
        }
    )
    return environment


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_ready(
    process: subprocess.Popen[str],
    ready_url: str,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            raise HarnessError(
                f"local Harness process exited before readiness with code {returncode}"
            )
        try:
            with urlopen(ready_url, timeout=0.2) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.05)
    raise HarnessError(f"local Harness readiness timed out: {ready_url}")


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
