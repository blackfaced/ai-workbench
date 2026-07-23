from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .agent import AgentRouter, ClaudeCodeCliAdapter, CodexCliAdapter
from .daemon import AgentDaemon, DaemonClient, DaemonError
from .kubernetes import KubernetesJanitor
from .project import (
    ProjectConfigError,
    ProjectDoctor,
    ProjectInitError,
    ProjectInitializer,
)
from .runner import GoalRunner
from .setup import WorkbenchSetup
from .skills import SkillCatalog
from .supervisor import LaunchdError, LaunchdService


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    options = parser.parse_args(arguments)
    handlers = {
        "init": _run_init,
        "setup": _run_setup,
        "skills": _run_skills,
        "doctor": _run_doctor,
        "goal": _run_goal,
        "daemon": _run_daemon,
        "janitor": _run_janitor,
    }
    try:
        return handlers[options.command](options)
    except (
        DaemonError,
        LaunchdError,
        ProjectConfigError,
        ProjectInitError,
        ValueError,
        OSError,
    ) as error:
        _print_json(
            {
                "error": getattr(error, "code", "operation_error"),
                "message": str(error),
            },
            stream=sys.stderr,
        )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiwb")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--repo", required=True, type=Path)
    initialize.add_argument("--output", type=Path)
    initialize.add_argument("--force", action="store_true")

    setup = commands.add_parser("setup")
    setup.add_argument("--repo", required=True, type=Path)
    setup.add_argument(
        "--agent-target",
        action="append",
        choices=("codex", "claude-code"),
        default=[],
    )
    setup.add_argument("--role-skill", action="append", default=[])
    setup.add_argument("--install-skill", action="append", default=[])
    setup.add_argument("--apply", action="store_true")

    skills = commands.add_parser("skills")
    skills_commands = skills.add_subparsers(dest="skills_command", required=True)
    ask = skills_commands.add_parser("ask")
    ask.add_argument("--repo", required=True, type=Path)
    ask.add_argument("--task", required=True)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--config", required=True, type=Path)
    doctor.add_argument(
        "--agent-provider",
        choices=("codex", "claude-code"),
        default="codex",
    )
    doctor.add_argument("--codex-bin", default="codex")
    doctor.add_argument("--claude-bin", default="claude")

    goal = commands.add_parser("goal")
    goal_commands = goal.add_subparsers(dest="goal_command", required=True)
    run = goal_commands.add_parser("run")
    run.add_argument("--contract", required=True, type=Path)
    _add_control_options(run)
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--claude-bin", default="claude")
    run.add_argument(
        "--claude-permission-mode",
        choices=("auto", "acceptEdits", "dontAsk"),
        default="auto",
    )
    run.add_argument("--todo-workers", type=int, default=2)
    run.add_argument("--image-poll-seconds", type=float, default=5.0)

    submit = goal_commands.add_parser("submit")
    submit.add_argument("--contract", required=True, type=Path)
    _add_control_options(submit)

    goal_status = goal_commands.add_parser("status")
    goal_status.add_argument("run_id")
    _add_control_options(goal_status)

    report = goal_commands.add_parser("report")
    report.add_argument("run_id")
    _add_control_options(report)

    daemon = commands.add_parser("daemon")
    daemon_commands = daemon.add_subparsers(dest="daemon_command", required=True)
    serve = daemon_commands.add_parser("serve")
    _add_control_options(serve)
    serve.add_argument("--codex-bin", default="codex")
    serve.add_argument("--claude-bin", default="claude")
    serve.add_argument(
        "--claude-permission-mode",
        choices=("auto", "acceptEdits", "dontAsk"),
        default="auto",
    )
    serve.add_argument("--max-workers", type=int, default=1)
    serve.add_argument("--todo-workers", type=int, default=2)
    serve.add_argument("--image-poll-seconds", type=float, default=5.0)

    daemon_status = daemon_commands.add_parser("status")
    _add_control_options(daemon_status)

    install = daemon_commands.add_parser("install")
    _add_control_options(install)
    install.add_argument("--plist", type=Path)
    install.add_argument("--codex-bin", default="codex")
    install.add_argument("--claude-bin", default="claude")
    install.add_argument(
        "--claude-permission-mode",
        choices=("auto", "acceptEdits", "dontAsk"),
        default="auto",
    )
    install.add_argument("--max-workers", type=int, default=1)
    install.add_argument("--todo-workers", type=int, default=2)
    install.add_argument("--image-poll-seconds", type=float, default=5.0)
    install.add_argument("--no-load", action="store_true")

    janitor = commands.add_parser("janitor")
    janitor_commands = janitor.add_subparsers(
        dest="janitor_command",
        required=True,
    )
    sweep = janitor_commands.add_parser("sweep")
    sweep.add_argument(
        "--state-dir",
        type=Path,
        default=Path("~/.ai-workbench").expanduser(),
    )
    return parser


def _run_init(options: argparse.Namespace) -> int:
    result = ProjectInitializer().initialize(
        repository=options.repo,
        output_path=options.output,
        force=options.force,
    )
    _print_json(result.__dict__)
    return 0


def _run_setup(options: argparse.Namespace) -> int:
    setup = WorkbenchSetup()
    targets = tuple(options.agent_target)
    role_skills = _role_skills(options.role_skill)
    if options.apply:
        result = setup.apply(
            repository=options.repo,
            confirmed=True,
            agent_targets=targets,
            role_skills=role_skills,
            install_skills=tuple(options.install_skill),
        )
        _print_json(
            {
                "workflow_path": result.workflow_path,
                "workflow_action": result.workflow_action,
                "changed": result.changed,
                "agent_targets": result.agent_targets,
            }
        )
    else:
        result = setup.inspect(options.repo, targets)
        _print_json(
            {
                "workflow_path": result.workflow_path,
                "workflow_action": result.workflow_action,
                "suggestions": result.suggestions,
                "agent_targets": result.agent_targets,
                "skills": [skill.__dict__ for skill in result.catalog.skills],
                "warnings": result.catalog.warnings,
            }
        )
    return 0


def _run_skills(options: argparse.Namespace) -> int:
    if options.skills_command != "ask":
        raise ValueError(f"unsupported skills command: {options.skills_command}")
    result = SkillCatalog().recommend(options.repo, options.task)
    _print_json(
        {"recommendations": [item.__dict__ for item in result.recommendations]}
    )
    return 0


def _run_doctor(options: argparse.Namespace) -> int:
    report = ProjectDoctor().inspect(
        config_path=options.config,
        codex_bin=options.codex_bin,
        agent_provider=options.agent_provider,
        claude_bin=options.claude_bin,
    )
    _print_json(report.to_dict())
    return 0 if report.status == "ok" else 1


def _run_goal(options: argparse.Namespace) -> int:
    if options.goal_command == "run":
        report = GoalRunner(
            state_dir=options.state_dir,
            agent=_agent_router(options),
            max_workers=options.todo_workers,
            image_poll_interval_seconds=options.image_poll_seconds,
        ).run(options.contract)
        _print_json(report.to_dict())
        return 0

    client = DaemonClient(_socket_path(options))
    if options.goal_command == "submit":
        _print_json(client.submit(options.contract).__dict__)
    elif options.goal_command == "status":
        _print_json(client.status(options.run_id).__dict__)
    elif options.goal_command == "report":
        _print_json(client.report(options.run_id).to_dict())
    else:
        raise ValueError(f"unsupported goal command: {options.goal_command}")
    return 0


def _run_daemon(options: argparse.Namespace) -> int:
    if options.daemon_command == "serve":
        daemon = AgentDaemon(
            state_dir=options.state_dir,
            agent=_agent_router(options),
            socket_path=_socket_path(options),
            max_workers=options.max_workers,
            todo_workers=options.todo_workers,
            image_poll_interval_seconds=options.image_poll_seconds,
        )
        try:
            daemon.serve_forever()
        except KeyboardInterrupt:
            daemon.shutdown()
        return 0
    if options.daemon_command == "status":
        socket_path = _socket_path(options)
        status = "ok" if DaemonClient(socket_path).ping() else "unavailable"
        _print_json({"socket": str(socket_path), "status": status})
        return 0 if status == "ok" else 1
    if options.daemon_command == "install":
        result = LaunchdService().install(
            state_dir=options.state_dir,
            socket_path=_socket_path(options),
            plist_path=options.plist,
            codex_bin=options.codex_bin,
            claude_bin=options.claude_bin,
            claude_permission_mode=options.claude_permission_mode,
            max_workers=options.max_workers,
            todo_workers=options.todo_workers,
            image_poll_interval_seconds=options.image_poll_seconds,
            load=not options.no_load,
        )
        _print_json(result.__dict__)
        return 0
    raise ValueError(f"unsupported daemon command: {options.daemon_command}")


def _run_janitor(options: argparse.Namespace) -> int:
    if options.janitor_command != "sweep":
        raise ValueError(f"unsupported Janitor command: {options.janitor_command}")
    report = KubernetesJanitor(options.state_dir).sweep()
    _print_json(report.__dict__)
    return 0 if report.failed == 0 else 1


def _add_control_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("~/.ai-workbench").expanduser(),
    )
    parser.add_argument("--socket", type=Path)


def _role_skills(values: Sequence[str]) -> dict[str, Tuple[str, ...]]:
    result = {}
    for value in values:
        role, separator, path = value.partition("=")
        if not separator or not role or not path:
            raise ValueError("role skills must use ROLE=PATH")
        result.setdefault(role, []).append(path)
    return {role: tuple(paths) for role, paths in result.items()}


def _agent_router(options: argparse.Namespace) -> AgentRouter:
    return AgentRouter(
        {
            "codex": CodexCliAdapter(options.codex_bin),
            "claude-code": ClaudeCodeCliAdapter(
                options.claude_bin,
                permission_mode=options.claude_permission_mode,
            ),
        }
    )


def _socket_path(options: argparse.Namespace) -> Path:
    if options.socket:
        return options.socket.expanduser().resolve()
    return options.state_dir.expanduser().resolve() / "run" / "daemon.sock"


def _print_json(value: object, stream=None) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )
