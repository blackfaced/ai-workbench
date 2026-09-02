from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb import (  # noqa: E402
    HarnessApplyRequest,
    HarnessSetup,
    HarnessSetupRequest,
)
from aiwb import harness_setup as harness_setup_module  # noqa: E402


def test_skills_ask_cli_is_advisory_and_returns_bounded_json() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "skills",
                "ask",
                "--repo",
                str(repository),
                "--task",
                "submit an approved unattended goal and inspect evidence",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["recommendations"][0]["name"] == (
            "run-approved-goal"
        )
        assert not (repository / ".ai-workbench").exists()


def test_setup_cli_requires_apply_before_it_installs_a_project_skill() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")
        command = [
            sys.executable,
            "-m",
            "aiwb",
            "setup",
            "--repo",
            str(repository),
            "--agent-target",
            "codex",
            "--install-skill",
            "ask-ai-workbench",
        ]

        inspected = subprocess.run(
            command,
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        installed = repository / ".codex" / "skills" / "ask-ai-workbench" / "SKILL.md"
        assert inspected.returncode == 0, inspected.stderr
        assert not installed.exists()

        applied = subprocess.run(
            [*command, "--apply"],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert applied.returncode == 0, applied.stderr
        assert installed.is_file()


def test_setup_cli_installs_an_explicit_project_local_skill() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        source = repository / "skills" / "focused" / "SKILL.md"
        source.parent.mkdir(parents=True)
        source.write_text(
            "---\nname: focused\ndescription: Focus this project.\n---\n\n# Focused\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        installed = repository / ".codex" / "skills" / "focused" / "SKILL.md"
        assert completed.returncode == 0, completed.stderr
        assert installed.read_bytes() == source.read_bytes()


def test_setup_cli_resolves_a_project_skill_for_the_selected_agent_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        codex_skill = repository / ".codex" / "skills" / "focused" / "SKILL.md"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        codex_skill.parent.mkdir(parents=True)
        claude_skill.parent.mkdir(parents=True)
        codex_skill.write_text(
            "---\nname: focused\ndescription: Codex version.\n---\n\n# Codex\n",
            encoding="utf-8",
        )
        claude_skill.write_text(
            "---\nname: focused\ndescription: Claude version.\n---\n\n# Claude\n",
            encoding="utf-8",
        )
        expected = codex_skill.read_bytes()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert codex_skill.read_bytes() == expected


def test_setup_cli_previews_the_skill_selected_for_the_exact_agent_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        codex_skill = repository / ".codex" / "skills" / "focused" / "SKILL.md"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        codex_skill.parent.mkdir(parents=True)
        claude_skill.parent.mkdir(parents=True)
        codex_skill.write_text(
            "---\nname: focused\ndescription: Codex version.\n---\n\n# Codex\n",
            encoding="utf-8",
        )
        claude_skill.write_text(
            "---\nname: focused\ndescription: Claude version.\n---\n\n# Claude\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["selected_skills"] == [
            {
                "name": "focused",
                "agent_target": "codex",
                "source": str(codex_skill.resolve()),
                "destination": str(codex_skill.resolve()),
                "sha256": hashlib.sha256(codex_skill.read_bytes()).hexdigest(),
            }
        ]


def test_setup_cli_rejects_a_symlinked_agent_skill_root() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        claude_skill.parent.mkdir(parents=True)
        claude_skill.write_text(
            "---\nname: focused\ndescription: Claude version.\n---\n\n# Claude\n",
            encoding="utf-8",
        )
        codex_root = repository / ".codex"
        codex_root.mkdir()
        (codex_root / "skills").symlink_to(repository / ".claude" / "skills")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 1
        assert "Agent target Skill root must not contain symlinks" in completed.stderr
        assert "# Claude" in claude_skill.read_text(encoding="utf-8")


def test_setup_cli_rejects_a_symlinked_target_skill_directory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        claude_skill.parent.mkdir(parents=True)
        claude_skill.write_text(
            "---\nname: focused\ndescription: Claude version.\n---\n\n# Claude\n",
            encoding="utf-8",
        )
        codex_skills = repository / ".codex" / "skills"
        codex_skills.mkdir(parents=True)
        (codex_skills / "focused").symlink_to(claude_skill.parent)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 1
        assert "Agent target Skill root must not contain symlinks" in completed.stderr


def test_setup_cli_rejects_a_symlinked_shared_skill_source() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        claude_skill = repository / ".claude" / "skills" / "focused" / "SKILL.md"
        claude_skill.parent.mkdir(parents=True)
        claude_skill.write_text(
            "---\nname: focused\ndescription: Claude version.\n---\n\n# Claude\n",
            encoding="utf-8",
        )
        shared = repository / ".agents" / "skills"
        shared.mkdir(parents=True)
        (shared / "focused").symlink_to(claude_skill.parent)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-skill",
                "focused",
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 1
        assert "Skill source must not contain symlinks" in completed.stderr


def test_setup_installs_a_non_skill_extension_only_after_harness_probe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "focused-mcp"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        source = repository / "extensions" / "focused-mcp.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: mcp\n"
            "name: focused-mcp\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/focused-mcp\n",
            encoding="utf-8",
        )
        probed = []

        def probe(agent_target, descriptor, root, resolved_entrypoint):
            assert resolved_entrypoint == (
                root / descriptor["configuration"]["entrypoint"]
            ).resolve()
            completed = subprocess.run((str(resolved_entrypoint),), check=False)
            if completed.returncode:
                raise ValueError("Harness could not load extension")
            probed.append((agent_target, descriptor["name"]))

        setup = HarnessSetup(extension_probe=probe)
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )
        result = setup.apply(
            HarnessApplyRequest(
                plan,
                confirmed=True,
                install_extensions=(source,),
            )
        )

        installed = (
            repository
            / ".ai-workbench"
            / "extensions"
            / "mcp"
            / "focused-mcp.yaml"
        )
        assert installed.read_bytes() == source.read_bytes()
        assert probed == [("codex", "focused-mcp")]
        assert not hasattr(result, "installed_extensions")
        assert tuple(extension.identity for extension in result.extensions) == (
            "mcp:focused-mcp@1",
        )


def test_setup_cli_fails_closed_when_extension_probe_is_unavailable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "focused-mcp"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        source = repository / "extensions" / "focused-mcp.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: mcp\n"
            "name: focused-mcp\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/focused-mcp\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-extension",
                str(source),
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        installed = (
            repository
            / ".ai-workbench"
            / "extensions"
            / "mcp"
            / "focused-mcp.yaml"
        )
        assert completed.returncode == 1
        assert "availability probe is unavailable" in completed.stderr
        assert not installed.exists()


def test_setup_cli_installs_an_extension_after_its_harness_probe_succeeds() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "focused-command"
        probe = repository / "tools" / "probe-focused-command"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        probe.write_text(
            "#!/bin/sh\ntest -x tools/focused-command\n", encoding="utf-8"
        )
        entrypoint.chmod(0o755)
        probe.chmod(0o755)
        source = repository / "extensions" / "focused-command.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: command\n"
            "name: focused-command\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/focused-command\n"
            "  harness_probe:\n"
            "    - tools/probe-focused-command\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-extension",
                str(source),
                "--apply",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        installed = (
            repository
            / ".ai-workbench"
            / "extensions"
            / "command"
            / "focused-command.yaml"
        )
        assert completed.returncode == 0, completed.stderr
        assert installed.read_bytes() == source.read_bytes()
        output = json.loads(completed.stdout)
        assert "installed_extensions" not in output
        assert [extension["identity"] for extension in output["extensions"]] == [
            "command:focused-command@1"
        ]


def test_setup_cli_previews_the_exact_extension_without_writing_or_probing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "focused-command"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        source = repository / "extensions" / "focused-command.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: command\n"
            "name: focused-command\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/focused-command\n"
            "  harness_probe:\n"
            "    - tools/probe-that-must-not-run\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
                "--install-extension",
                str(source),
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["extensions"] == [
            {
                "identity": "command:focused-command@1",
                "agent_target": "codex",
                "source": str(source.resolve()),
                "destination": str(
                    repository.resolve()
                    / ".ai-workbench"
                    / "extensions"
                    / "command"
                    / "focused-command.yaml"
                ),
                "entrypoint": str(entrypoint.resolve()),
                "descriptor_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "entrypoint_sha256": hashlib.sha256(
                    entrypoint.read_bytes()
                ).hexdigest(),
                "harness_probe": ["tools/probe-that-must-not-run"],
            }
        ]
        assert not (
            repository
            / ".ai-workbench"
            / "extensions"
            / "command"
            / "focused-command.yaml"
        ).exists()


def test_setup_does_not_install_an_extension_rejected_by_the_harness_probe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "broken-plugin"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/missing/interpreter\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        source = repository / "extensions" / "broken-plugin.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: plugin\n"
            "name: broken-plugin\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/broken-plugin\n",
            encoding="utf-8",
        )

        def reject(_agent_target, _descriptor, _root, _resolved_entrypoint):
            raise ValueError("Harness could not load extension")

        setup = HarnessSetup(extension_probe=reject)
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )

        with pytest.raises(ValueError, match="Harness could not load extension"):
            setup.apply(
                HarnessApplyRequest(
                    plan,
                    confirmed=True,
                    install_extensions=(source,),
                )
            )

        assert not (
            repository
            / ".ai-workbench"
            / "extensions"
            / "plugin"
            / "broken-plugin.yaml"
        ).exists()
        assert not (repository / ".ai-workbench" / "workflow.yaml").exists()


def test_setup_rejects_duplicate_extension_identity_before_probe_or_write() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "focused-hook"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        sources = []
        for folder in ("first", "second"):
            source = repository / folder / "focused-hook.yaml"
            source.parent.mkdir()
            source.write_text(
                "kind: hook\n"
                "name: focused-hook\n"
                "version: 1\n"
                "driver: codex\n"
                "configuration:\n"
                "  entrypoint: tools/focused-hook\n",
                encoding="utf-8",
            )
            sources.append(source)
        probed = []

        def probe(*_arguments):
            probed.append(True)

        setup = HarnessSetup(extension_probe=probe)
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )

        with pytest.raises(ValueError, match="duplicate Harness Extension"):
            setup.apply(
                HarnessApplyRequest(
                    plan,
                    confirmed=True,
                    install_extensions=tuple(sources),
                )
            )

        assert probed == []
        assert not (
            repository
            / ".ai-workbench"
            / "extensions"
            / "hook"
            / "focused-hook.yaml"
        ).exists()


def test_setup_rejects_an_entrypoint_changed_during_probe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        tools = repository / "tools"
        tools.mkdir(parents=True)
        first = tools / "first-command"
        second = tools / "second-command"
        for entrypoint in (first, second):
            entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            entrypoint.chmod(0o755)
        selected = tools / "selected-command"
        selected.write_bytes(first.read_bytes())
        selected.chmod(0o755)
        source = repository / "extensions" / "selected-command.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: command\n"
            "name: selected-command\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/selected-command\n",
            encoding="utf-8",
        )

        def swap(_agent_target, _descriptor, _root, resolved_entrypoint):
            assert resolved_entrypoint == selected.resolve()
            selected.write_bytes(second.read_bytes() + b"# changed\n")

        setup = HarnessSetup(extension_probe=swap)
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )

        with pytest.raises(ValueError, match="entrypoint changed during Setup"):
            setup.apply(
                HarnessApplyRequest(
                    plan,
                    confirmed=True,
                    install_extensions=(source,),
                )
            )

        assert not (
            repository
            / ".ai-workbench"
            / "extensions"
            / "command"
            / "selected-command.yaml"
        ).exists()


def test_setup_rejects_a_stable_entrypoint_symlink_before_probe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        tools = repository / "tools"
        tools.mkdir(parents=True)
        executable = tools / "actual-command"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        selected = tools / "selected-command"
        selected.symlink_to(executable)
        source = repository / "extensions" / "selected-command.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: command\n"
            "name: selected-command\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/selected-command\n",
            encoding="utf-8",
        )
        probed = []

        setup = HarnessSetup(extension_probe=lambda *_arguments: probed.append(True))
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )

        with pytest.raises(ValueError, match="entrypoint must not contain symlinks"):
            setup.apply(
                HarnessApplyRequest(
                    plan,
                    confirmed=True,
                    install_extensions=(source,),
                )
            )

        assert probed == []


def test_setup_rejects_a_symlinked_extension_destination_before_probe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        entrypoint = repository / "tools" / "selected-command"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        source = repository / "extensions" / "selected-command.yaml"
        source.parent.mkdir()
        source.write_text(
            "kind: command\n"
            "name: selected-command\n"
            "version: 1\n"
            "driver: codex\n"
            "configuration:\n"
            "  entrypoint: tools/selected-command\n",
            encoding="utf-8",
        )
        redirected = repository / "redirected"
        redirected.mkdir()
        metadata = repository / ".ai-workbench"
        metadata.mkdir()
        (metadata / "extensions").symlink_to(redirected)
        probed = []

        setup = HarnessSetup(extension_probe=lambda *_arguments: probed.append(True))
        plan = setup.plan(
            HarnessSetupRequest(repository, agent_targets=("codex",))
        )

        with pytest.raises(ValueError, match="destination must not contain symlinks"):
            setup.apply(
                HarnessApplyRequest(
                    plan,
                    confirmed=True,
                    install_extensions=(source,),
                )
            )

        assert probed == []
        assert not (redirected / "command" / "selected-command.yaml").exists()


def test_extension_probe_timeout_terminates_the_entire_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        marker = repository / "leaked-child"
        probe = repository / "probe"
        probe.write_text(
            "#!/bin/sh\n"
            f"(trap '' TERM; sleep 0.5; printf leaked > {marker}) &\n"
            "sleep 1\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        entrypoint = repository / "entrypoint"
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        monkeypatch.setattr(
            harness_setup_module,
            "_EXTENSION_PROBE_TIMEOUT_SECONDS",
            0.1,
            raising=False,
        )

        with pytest.raises(ValueError, match="availability probe failed"):
            harness_setup_module._run_declared_harness_probe(
                "codex",
                {
                    "configuration": {
                        "harness_probe": [str(probe)],
                    }
                },
                repository,
                entrypoint,
            )

        time.sleep(0.6)
        assert not marker.exists()


def test_extension_probe_cleanup_cannot_turn_a_timeout_into_an_unbounded_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        probe = repository / "probe"
        probe.write_text("#!/bin/sh\nsleep 1\n", encoding="utf-8")
        probe.chmod(0o755)
        entrypoint = repository / "entrypoint"
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        monkeypatch.setattr(
            harness_setup_module,
            "_EXTENSION_PROBE_TIMEOUT_SECONDS",
            0.1,
        )
        monkeypatch.setattr(
            harness_setup_module.os,
            "killpg",
            lambda *_arguments: (_ for _ in ()).throw(PermissionError()),
        )

        started = time.monotonic()
        with pytest.raises(ValueError, match="availability probe failed"):
            harness_setup_module._run_declared_harness_probe(
                "codex",
                {"configuration": {"harness_probe": [str(probe)]}},
                repository,
                entrypoint,
            )

        assert time.monotonic() - started < 0.8


def test_setup_cli_lists_the_optional_matt_pack_without_installing_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory) / "project"
        repository.mkdir()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(TOOL_ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aiwb",
                "setup",
                "--repo",
                str(repository),
                "--agent-target",
                "codex",
            ],
            cwd=str(TOOL_ROOT),
            env=environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert completed.returncode == 0, completed.stderr
        matt = next(
            pack for pack in json.loads(completed.stdout)["packs"] if pack["name"] == "matt"
        )
        assert matt["installable"] is True
        assert matt["revision"] == (
            "v1.1.0 (resolved d574778f94cf620fcc8ce741584093bc650a61d3)"
        )
        assert matt["profiles"][0]["name"] == "engineering"
        assert not (repository / ".agents").exists()
