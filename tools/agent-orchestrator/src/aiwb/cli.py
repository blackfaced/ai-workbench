from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .agent import AgentRouter, ClaudeCodeCliAdapter, CodexCliAdapter
from .daemon import AgentDaemon, DaemonClient, DaemonError
from .handoff_bridge import GoalHandoffBridge
from .harness_setup import (
    HarnessApplyRequest,
    HarnessSetup,
    HarnessSetupRequest,
    HarnessVerifyRequest,
)
from .intake import GoalIntake
from .kubernetes import KubernetesJanitor
from .project import (
    ProjectConfigError,
    ProjectInitError,
)
from .runner import GoalRunner, preview_execution
from .skills import SkillCatalog
from .supervisor import LaunchdError, LaunchdService
from .tickets import TicketContractDraftBuilder


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
        "evidence": _run_evidence,
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
    setup.add_argument("--install-pack", action="append", default=[])
    setup.add_argument("--pack-skill", action="append", default=[])
    setup.add_argument("--pack-profile", action="append", default=[])
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

    resume = goal_commands.add_parser("resume")
    resume.add_argument("run_id")
    _add_control_options(resume)

    intake = goal_commands.add_parser("intake")
    intake.add_argument("--repo", required=True, type=Path)
    intake_source = intake.add_mutually_exclusive_group(required=True)
    intake_source.add_argument("--contract", type=Path)
    intake_source.add_argument("--tickets", type=Path)
    intake_source.add_argument("--handoff", type=Path)
    intake.add_argument("--task", default="")
    _add_control_options(intake)

    goal_evidence = goal_commands.add_parser("evidence")
    goal_evidence.add_argument("run_id")
    goal_evidence.add_argument("artifact_id")
    _add_control_options(goal_evidence)

    preflight = goal_commands.add_parser("preflight")
    preflight.add_argument("--contract", required=True, type=Path)
    preflight_policy = preflight.add_mutually_exclusive_group()
    preflight_policy.add_argument("--workflow", type=Path)
    preflight_policy.add_argument("--policy", dest="workflow", type=Path)

    draft = goal_commands.add_parser("draft")
    draft.add_argument("--repo", required=True, type=Path)
    draft.add_argument("--tickets", required=True, type=Path)
    draft.add_argument("--output", required=True, type=Path)
    draft.add_argument("--force", action="store_true")

    bridge = goal_commands.add_parser("bridge")
    bridge.add_argument("--repo", required=True, type=Path)
    bridge.add_argument("--handoff", required=True, type=Path)
    bridge.add_argument("--policy", required=True, type=Path)
    bridge.add_argument("--output", required=True, type=Path)

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

    evidence = commands.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(
        dest="evidence_command",
        required=True,
    )
    prune = evidence_commands.add_parser("prune")
    prune.add_argument("--older-than-days", required=True, type=int)
    _add_control_options(prune)
    return parser


def _run_init(options: argparse.Namespace) -> int:
    setup = HarnessSetup()
    plan = setup.plan(
        HarnessSetupRequest(
            repository=options.repo,
            operation="initialize",
            output_path=options.output,
        )
    )
    result = setup.apply(
        HarnessApplyRequest(
            plan=plan,
            confirmed=True,
            force=options.force,
        )
    )
    _print_json(
        {
            "config": result.workflow_path,
            "status": result.status,
            "suggestions": result.suggestions,
        }
    )
    return 0


def _run_setup(options: argparse.Namespace) -> int:
    setup = HarnessSetup()
    targets = tuple(options.agent_target)
    plan = setup.plan(
        HarnessSetupRequest(
            repository=options.repo,
            agent_targets=targets,
        )
    )
    role_skills = _role_skills(options.role_skill)
    pack_skills = _pack_skills(options.install_pack, options.pack_skill)
    pack_profiles = _pack_profiles(options.install_pack, options.pack_profile)
    if options.apply:
        result = setup.apply(
            HarnessApplyRequest(
                plan=plan,
                confirmed=True,
                role_skills=role_skills,
                install_skills=tuple(options.install_skill),
                pack_skills=pack_skills,
                pack_profiles=pack_profiles,
            )
        )
        _print_json(
            {
                "workflow_path": result.workflow_path,
                "workflow_action": result.workflow_action,
                "changed": result.changed,
                "agent_targets": result.agent_targets,
                "installed_packs": result.installed_packs,
                "next_actions": result.next_actions,
            }
        )
    else:
        result = plan.assessment
        _print_json(
            {
                "workflow_path": result.workflow_path,
                "workflow_action": result.workflow_action,
                "suggestions": result.suggestions,
                "agent_targets": result.agent_targets,
                "skills": [skill.__dict__ for skill in result.catalog.skills],
                "warnings": result.catalog.warnings,
                "packs": [_pack_to_dict(pack) for pack in result.packs],
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
    result = HarnessSetup().verify(
        HarnessVerifyRequest(
            config_path=options.config,
            codex_bin=options.codex_bin,
            agent_provider=options.agent_provider,
            claude_bin=options.claude_bin,
        )
    )
    report = result.report
    _print_json(report.to_dict())
    return 0 if report.status == "ok" else 1


def _run_goal(options: argparse.Namespace) -> int:
    if options.goal_command == "bridge":
        result = GoalHandoffBridge().create(
            repository=options.repo,
            handoff_path=options.handoff,
            policy_path=options.policy,
            output_path=options.output,
        )
        _print_json(result.to_dict())
        return 0
    if options.goal_command == "draft":
        result = TicketContractDraftBuilder().create(
            tickets_path=options.tickets,
            repository=options.repo,
            output_path=options.output,
            force=options.force,
        )
        _print_json(result.__dict__)
        return 0
    if options.goal_command == "preflight":
        _print_json(
            preview_execution(
                options.contract,
                workflow_path=options.workflow,
            ).to_dict()
        )
        return 0
    if options.goal_command == "intake":
        client = DaemonClient(_socket_path(options))
        result = GoalIntake(daemon_probe=client.ping).inspect(
            repository=options.repo,
            contract_path=options.contract,
            tickets_path=options.tickets,
            handoff_path=options.handoff,
            task=options.task,
        )
        _print_json(result.to_dict())
        return 0
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
    elif options.goal_command == "resume":
        _print_json(client.resume(options.run_id).__dict__)
    elif options.goal_command == "evidence":
        _print_json(
            client.evidence(options.run_id, options.artifact_id).to_dict()
        )
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


def _run_evidence(options: argparse.Namespace) -> int:
    if options.evidence_command != "prune":
        raise ValueError(f"unsupported Evidence command: {options.evidence_command}")
    report = DaemonClient(_socket_path(options)).prune_evidence(
        options.older_than_days
    )
    _print_json(report.__dict__)
    return 0


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


def _pack_skills(
    packs: Sequence[str],
    values: Sequence[str],
) -> dict[str, Tuple[str, ...]]:
    selected = {name: [] for name in packs}
    for value in values:
        pack, separator, skill = value.partition("=")
        if not separator or not pack or not skill:
            raise ValueError("pack skills must use PACK=SKILL")
        if pack not in selected:
            raise ValueError("pack skills require a matching --install-pack")
        selected[pack].append(skill)
    return {pack: tuple(skills) for pack, skills in selected.items()}


def _pack_profiles(
    packs: Sequence[str],
    values: Sequence[str],
) -> dict[str, Tuple[str, ...]]:
    selected = {name: [] for name in packs}
    for value in values:
        pack, separator, profile = value.partition("=")
        if not separator or not pack or not profile:
            raise ValueError("pack profiles must use PACK=PROFILE")
        if pack not in selected:
            raise ValueError("pack profiles require a matching --install-pack")
        selected[pack].append(profile)
    return {pack: tuple(profiles) for pack, profiles in selected.items() if profiles}


def _pack_to_dict(pack) -> dict[str, object]:
    return {
        "name": pack.name,
        "description": pack.description,
        "source": pack.source,
        "revision": pack.revision,
        "installable": pack.installable,
        "setup_action": pack.setup_action,
        "profiles": [profile.__dict__ for profile in pack.profiles],
    }


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
