from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]


def test_cli_renders_a_user_launch_agent_without_loading_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state_dir = root / "state"
        plist_path = root / "com.ai-workbench.agent-orchestrator.plist"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "daemon",
                "install",
                "--state-dir",
                str(state_dir),
                "--plist",
                str(plist_path),
                "--claude-bin",
                "/custom/claude",
                "--claude-permission-mode",
                "dontAsk",
                "--no-load",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        output = json.loads(completed.stdout)
        assert output == {
            "label": "com.ai-workbench.agent-orchestrator",
            "loaded": False,
            "plist": str(plist_path.resolve()),
        }
        with plist_path.open("rb") as source:
            service = plistlib.load(source)

        assert service["Label"] == "com.ai-workbench.agent-orchestrator"
        assert service["KeepAlive"] is True
        assert service["RunAtLoad"] is True
        assert service["ProgramArguments"] == [
            sys.executable,
            "-m",
            "aiwb",
            "daemon",
            "serve",
            "--state-dir",
            str(state_dir.resolve()),
            "--socket",
            str((state_dir / "run" / "daemon.sock").resolve()),
            "--codex-bin",
            "codex",
            "--claude-bin",
            "/custom/claude",
            "--claude-permission-mode",
            "dontAsk",
            "--max-workers",
            "1",
            "--todo-workers",
            "2",
            "--image-poll-seconds",
            "5.0",
        ]
        assert service["StandardOutPath"] == str(
            (state_dir / "logs" / "daemon.stdout.log").resolve()
        )
        assert service["StandardErrorPath"] == str(
            (state_dir / "logs" / "daemon.stderr.log").resolve()
        )
