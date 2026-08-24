from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


LAUNCHD_LABEL = "com.ai-workbench.agent-orchestrator"


@dataclass(frozen=True)
class LaunchdInstallResult:
    label: str
    plist: str
    loaded: bool


class LaunchdError(RuntimeError):
    pass


class LaunchdService:
    """Render and load the macOS user LaunchAgent for the daemon."""

    def __init__(self, label: str = LAUNCHD_LABEL) -> None:
        self.label = label

    def install(
        self,
        state_dir: Path,
        socket_path: Path,
        plist_path: Optional[Path] = None,
        codex_bin: str = "codex",
        claude_bin: str = "claude",
        claude_permission_mode: str = "auto",
        max_workers: int = 1,
        todo_workers: int = 2,
        image_poll_interval_seconds: float = 5.0,
        load: bool = True,
    ) -> LaunchdInstallResult:
        if (
            max_workers <= 0
            or todo_workers <= 0
            or image_poll_interval_seconds <= 0
        ):
            raise ValueError("worker counts must be positive")
        state_dir = Path(state_dir).expanduser().resolve()
        socket_path = Path(socket_path).expanduser().resolve()
        plist_path = (
            Path(plist_path).expanduser().resolve()
            if plist_path
            else Path("~/Library/LaunchAgents").expanduser()
            / f"{self.label}.plist"
        )
        logs = state_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        service = {
            "Label": self.label,
            "EnvironmentVariables": {
                "PATH": os.environ.get("PATH", os.defpath),
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            },
            "ProgramArguments": [
                sys.executable,
                "-m",
                "aiwb",
                "daemon",
                "serve",
                "--state-dir",
                str(state_dir),
                "--socket",
                str(socket_path),
                "--codex-bin",
                codex_bin,
                "--claude-bin",
                claude_bin,
                "--claude-permission-mode",
                claude_permission_mode,
                "--max-workers",
                str(max_workers),
                "--todo-workers",
                str(todo_workers),
                "--image-poll-seconds",
                str(image_poll_interval_seconds),
            ],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": str(logs / "daemon.stdout.log"),
            "StandardErrorPath": str(logs / "daemon.stderr.log"),
        }
        with plist_path.open("wb") as destination:
            plistlib.dump(service, destination, sort_keys=True)
        os.chmod(plist_path, 0o600)

        if load:
            self._load(plist_path)
        return LaunchdInstallResult(
            label=self.label,
            plist=str(plist_path),
            loaded=load,
        )

    def _load(self, plist_path: Path) -> None:
        domain = f"gui/{os.getuid()}"
        service = f"{domain}/{self.label}"
        already_loaded = subprocess.run(
            ["launchctl", "print", service],
            check=False,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if already_loaded:
            self._launchctl("bootout", service)
        self._launchctl("bootstrap", domain, str(plist_path))

    @staticmethod
    def _launchctl(*arguments: str) -> None:
        completed = subprocess.run(
            ["launchctl", *arguments],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise LaunchdError(
                f"launchctl {' '.join(arguments)} failed with exit code "
                f"{completed.returncode}: {detail}"
            )
