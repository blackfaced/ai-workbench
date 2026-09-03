from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .codex_driver import CodexDriver
from .daemon import AgentDaemon, DaemonClient, DaemonError
from .github_pipeline import (
    GhApiGitHubSource,
    GitHubActionsAdapter,
    GitHubPipelineRequest,
)
from ._harness_apply import HarnessApplyResult
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
from .recipe_catalog import RecipeCatalog
from .runner import approve_execution, preview_execution
from .skills import SkillCatalog
from .state import (
    DurableStateSetup,
    INCOMPATIBLE_CURRENT_STATE_MESSAGE,
    StateAssessment,
    StateFormat,
    StateResetError,
)
from .supervisor import LaunchdError, LaunchdService


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    options = parser.parse_args(arguments)
    handlers = {
        "init": _run_init,
        "setup": _run_setup,
        "skills": _run_skills,
        "doctor": _run_doctor,
        "pipeline": _run_pipeline,
        "recipes": _run_recipes,
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
        StateResetError,
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
    setup.add_argument("--install-skill", action="append", default=[])
    setup.add_argument(
        "--install-extension", action="append", type=Path, default=[]
    )
    setup.add_argument("--install-pack", action="append", default=[])
    setup.add_argument("--pack-skill", action="append", default=[])
    setup.add_argument("--pack-profile", action="append", default=[])
    setup.add_argument("--planning-mode", choices=("python-l0",))
    setup.add_argument("--approve-plan", action="store_true")
    setup.add_argument("--approved-by")
    setup.add_argument("--plan-artifact", type=Path)
    setup.add_argument("--approved-plan", type=Path)
    apply_operation = setup.add_mutually_exclusive_group()
    apply_operation.add_argument("--preview-apply", action="store_true")
    apply_operation.add_argument("--approve-apply", action="store_true")
    apply_operation.add_argument("--execute-apply", action="store_true")
    setup.add_argument("--base-commit")
    setup.add_argument("--state-dir", type=Path)
    setup.add_argument("--apply-command", action="append", default=[])
    setup.add_argument("--apply-artifact", type=Path)
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--reset-incompatible-state", action="store_true")

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

    pipeline = commands.add_parser("pipeline")
    pipeline_commands = pipeline.add_subparsers(
        dest="pipeline_command",
        required=True,
    )
    pipeline_verify = pipeline_commands.add_parser("verify")
    pipeline_verify.add_argument("--candidate-report", required=True, type=Path)
    pipeline_verify.add_argument("--owner", required=True)
    pipeline_verify.add_argument("--repository", required=True)
    pipeline_verify.add_argument("--workflow-name", required=True)
    pipeline_verify.add_argument(
        "--required-check",
        action="append",
        default=[],
    )
    pipeline_verify.add_argument(
        "--required-artifact",
        action="append",
        default=[],
    )
    pipeline_verify.add_argument(
        "--missing-variable",
        action="append",
        default=[],
    )
    pipeline_verify.add_argument("--state-dir", required=True, type=Path)

    recipes = commands.add_parser("recipes")
    recipe_commands = recipes.add_subparsers(
        dest="recipes_command",
        required=True,
    )
    recipe_audit = recipe_commands.add_parser("audit")
    recipe_audit.add_argument("--catalog", type=Path)
    recipe_refresh = recipe_commands.add_parser("refresh")
    recipe_refresh.add_argument("--proposed", required=True, type=Path)
    recipe_refresh.add_argument("--output", required=True, type=Path)

    goal = commands.add_parser("goal")
    goal_commands = goal.add_subparsers(dest="goal_command", required=True)
    run = goal_commands.add_parser("run")
    run.add_argument("--contract", required=True, type=Path)
    _add_control_options(run)

    submit = goal_commands.add_parser("submit")
    submit.add_argument("--contract", required=True, type=Path)
    submit.add_argument("--workflow", type=Path)
    submit.add_argument("--idempotency-key")
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
    intake.add_argument("--contract", required=True, type=Path)
    _add_control_options(intake)

    goal_evidence = goal_commands.add_parser("evidence")
    goal_evidence.add_argument("run_id")
    goal_evidence.add_argument("artifact_id")
    _add_control_options(goal_evidence)

    preflight = goal_commands.add_parser("preflight")
    preflight.add_argument("--contract", required=True, type=Path)
    preflight.add_argument("--workflow", type=Path)

    approve = goal_commands.add_parser("approve")
    approve.add_argument("--contract", required=True, type=Path)
    approve.add_argument("--workflow", type=Path)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--approval-artifact", required=True, type=Path)

    daemon = commands.add_parser("daemon")
    daemon_commands = daemon.add_subparsers(dest="daemon_command", required=True)
    serve = daemon_commands.add_parser("serve")
    _add_control_options(serve)
    serve.add_argument("--max-workers", type=int, default=1)

    daemon_status = daemon_commands.add_parser("status")
    _add_control_options(daemon_status)

    install = daemon_commands.add_parser("install")
    _add_control_options(install)
    install.add_argument("--plist", type=Path)
    install.add_argument("--max-workers", type=int, default=1)
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
    state_fields: dict[str, object] = {}
    if options.planning_mode:
        if options.reset_incompatible_state:
            raise ValueError(
                "--reset-incompatible-state cannot be combined with --planning-mode"
            )
    elif options.reset_incompatible_state and options.state_dir is None:
        raise ValueError("--reset-incompatible-state requires --state-dir")
    elif options.state_dir is not None:
        state_setup = DurableStateSetup()
        assessment = state_setup.inspect(options.state_dir)
        decision = "not_needed"
        if assessment.format == StateFormat.INCOMPATIBLE_CURRENT:
            raise StateResetError(INCOMPATIBLE_CURRENT_STATE_MESSAGE)
        if assessment.format == StateFormat.INCOMPATIBLE_LEGACY:
            if not assessment.resettable:
                raise StateResetError(assessment.detail)
            if options.reset_incompatible_state:
                decision = "explicit"
            else:
                _print_legacy_reset_preview(assessment)
                if not _read_confirmation():
                    _print_json(
                        {
                            "state": assessment.to_dict(),
                            "state_reset": {
                                "changed": False,
                                "decision": "declined",
                            },
                        }
                    )
                    return 1
                decision = "confirmed"
            result = state_setup.reset(options.state_dir, confirmed=True)
            assessment = result.assessment
            changed = result.changed
        elif options.reset_incompatible_state:
            decision = "explicit"
            changed = False
        else:
            changed = False
        state_fields = {
            "state": assessment.to_dict(),
            "state_reset": {"changed": changed, "decision": decision},
        }

    setup = HarnessSetup()
    targets = tuple(options.agent_target)
    plan = setup.plan(
        HarnessSetupRequest(
            repository=options.repo,
            agent_targets=targets,
            planning_mode=options.planning_mode or "",
        )
    )
    if options.planning_mode:
        if options.apply:
            raise ValueError(
                "planning mode is read-only and cannot be combined with --apply"
            )
        apply_requested = (
            options.preview_apply
            or options.approve_apply
            or options.execute_apply
        )
        if apply_requested:
            if (
                options.approved_plan is None
                or not options.base_commit
                or options.state_dir is None
                or not options.apply_command
            ):
                raise ValueError(
                    "Harness Apply requires --approved-plan, --base-commit, "
                    "--state-dir, and at least one --apply-command"
                )
            approved_plan = setup.load_approved_plan(
                plan,
                options.approved_plan,
            )
            preview = setup.preview_apply(
                approved_plan,
                base_commit=options.base_commit,
                state_dir=options.state_dir,
                command_names=tuple(options.apply_command),
            )
            if options.preview_apply:
                _print_json(preview.to_dict())
                return 0
            if options.apply_artifact is None:
                raise ValueError(
                    "Apply Approval and execution require --apply-artifact"
                )
            if options.approve_apply:
                if not options.approved_by:
                    raise ValueError("Apply Approval requires --approved-by")
                approval = setup.approve_apply(
                    preview,
                    approved_by=options.approved_by,
                    artifact_path=options.apply_artifact,
                )
                _print_json(approval.to_dict())
                return 0
            approval = setup.load_apply_approval(
                preview,
                options.apply_artifact,
            )
            result = setup.apply_approved(
                approved_plan,
                approval,
                state_dir=options.state_dir,
            )
            _print_json(result.to_dict())
            return 0
        if options.approve_plan:
            if not options.approved_by or options.plan_artifact is None:
                raise ValueError(
                    "Plan Approval requires --approved-by and --plan-artifact"
                )
            plan = setup.approve_plan(
                plan,
                approved_by=options.approved_by,
                artifact_path=options.plan_artifact,
            )
        elif options.approved_by or options.plan_artifact is not None:
            raise ValueError(
                "--approved-by and --plan-artifact require --approve-plan"
            )
        elif (
            options.approved_plan is not None
            or options.base_commit
            or options.state_dir is not None
            or options.apply_command
            or options.apply_artifact is not None
        ):
            raise ValueError(
                "Harness Apply arguments require an Apply operation"
            )
        _print_json(plan.to_dict())
        return 0
    if (
        options.approve_plan
        or options.approved_by
        or options.plan_artifact is not None
        or options.approved_plan is not None
        or options.preview_apply
        or options.approve_apply
        or options.execute_apply
        or options.base_commit
        or options.apply_command
        or options.apply_artifact is not None
    ):
        raise ValueError("Plan Approval requires --planning-mode")
    pack_skills = _pack_skills(options.install_pack, options.pack_skill)
    pack_profiles = _pack_profiles(options.install_pack, options.pack_profile)
    extension_resolutions = setup.preview_extensions(
        options.repo,
        tuple(options.install_extension),
        tuple(options.agent_target),
    )
    skill_resolutions = setup.preview_skills(
        options.repo,
        tuple(options.install_skill),
        tuple(options.agent_target),
    )
    if options.apply:
        result = setup.apply(
            HarnessApplyRequest(
                plan=plan,
                confirmed=True,
                install_skills=tuple(options.install_skill),
                install_extensions=tuple(options.install_extension),
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
                "extensions": [
                    resolution.to_dict()
                    for resolution in result.extensions
                ],
                "selected_skills": [
                    resolution.to_dict()
                    for resolution in result.selected_skills
                ],
                "installed_packs": result.installed_packs,
                "next_actions": result.next_actions,
                **state_fields,
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
                "extensions": [
                    resolution.to_dict()
                    for resolution in extension_resolutions
                ],
                "selected_skills": [
                    resolution.to_dict()
                    for resolution in skill_resolutions
                ],
                **state_fields,
            }
        )
    return 0


def _print_legacy_reset_preview(assessment: StateAssessment) -> None:
    print(
        "Incompatible legacy Run state detected. This state cannot be migrated.",
        file=sys.stderr,
    )
    print("The following legacy databases will be removed:", file=sys.stderr)
    for path in assessment.legacy_databases:
        print(f"  {path}", file=sys.stderr)
    if assessment.managed_paths:
        print(
            "The following managed Run workspaces and temporary state will be removed:",
            file=sys.stderr,
        )
        for path in assessment.managed_paths:
            print(f"  {path}", file=sys.stderr)
    print(
        "Evidence, logs, harness-setup worktrees, and unrelated files are preserved.",
        file=sys.stderr,
    )


def _read_confirmation() -> bool:
    print(
        "Reset incompatible legacy state? [y/N] ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    answer = sys.stdin.readline()
    return answer.strip().lower() in {"y", "yes"}


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


def _run_pipeline(options: argparse.Namespace) -> int:
    if options.pipeline_command != "verify":
        raise ValueError(f"unsupported pipeline command: {options.pipeline_command}")
    try:
        value = json.loads(options.candidate_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read candidate report: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("candidate report must be a JSON object")
    request = GitHubPipelineRequest(
        owner=options.owner,
        repository=options.repository,
        candidate=HarnessApplyResult.from_dict(value),
        required_checks=tuple(options.required_check),
        workflow_name=options.workflow_name,
        required_artifacts=tuple(options.required_artifact),
        missing_variables=tuple(
            _named_values(options.missing_variable, "missing variable")
        ),
    )
    executable = os.environ.get("AIWB_GH_BIN") or None
    result = HarnessSetup().verify_pipeline(
        request,
        adapter=GitHubActionsAdapter(
            GhApiGitHubSource(executable=executable)
        ),
        state_dir=options.state_dir,
    )
    _print_json(result.to_dict())
    return 0 if result.status in {"pipeline_pending", "verified"} else 1


def _run_recipes(options: argparse.Namespace) -> int:
    catalog = RecipeCatalog()
    if options.recipes_command == "audit":
        result = catalog.audit(catalog_path=options.catalog)
        _print_json(result.to_dict())
        return 0 if result.status == "ok" else 1
    if options.recipes_command == "refresh":
        result = catalog.refresh_preview(
            proposed_catalog=options.proposed,
            output_path=options.output,
        )
        _print_json(result.to_dict())
        return 0 if result.status in {"review_required", "unchanged"} else 1
    raise ValueError(f"unsupported Recipes command: {options.recipes_command}")


def _run_goal(options: argparse.Namespace) -> int:
    if options.goal_command == "preflight":
        _print_json(
            preview_execution(
                options.contract, workflow_path=options.workflow
            ).to_dict()
        )
        return 0
    if options.goal_command == "approve":
        _print_json(
            approve_execution(
                options.contract,
                workflow_path=options.workflow,
                approved_by=options.approved_by,
                artifact_path=options.approval_artifact,
            ).to_dict()
        )
        return 0
    if options.goal_command == "intake":
        client = DaemonClient(_socket_path(options))
        result = GoalIntake(daemon_probe=client.ping).inspect(
            repository=options.repo,
            contract_path=options.contract,
        )
        _print_json(result.to_dict())
        return 0
    if options.goal_command == "run":
        client = DaemonClient(_socket_path(options))
        submitted = client.submit(options.contract)
        terminal = {
            "candidate",
            "failed",
            "interrupted",
        }
        status = submitted
        while status.status not in terminal:
            time.sleep(0.1)
            status = client.status(submitted.run_id)
        _print_json(client.report(submitted.run_id).to_dict())
        return 0 if status.status == "candidate" else 1

    client = DaemonClient(_socket_path(options))
    if options.goal_command == "submit":
        _print_json(
            client.submit(
                options.contract,
                workflow_path=options.workflow,
                idempotency_key=options.idempotency_key,
            ).__dict__
        )
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
        assessment = DurableStateSetup().inspect(options.state_dir)
        if assessment.format == StateFormat.INCOMPATIBLE_LEGACY:
            raise DaemonError(
                "incompatible_state",
                "incompatible legacy Run state; no migration is available; review and reset "
                "it with aiwb setup --repo <path> --state-dir <state-dir>",
            )
        if assessment.format == StateFormat.INCOMPATIBLE_CURRENT:
            raise DaemonError("incompatible_state", INCOMPATIBLE_CURRENT_STATE_MESSAGE)
        agent_daemon = AgentDaemon(
            options.state_dir,
            CodexDriver(),
            socket_path=_socket_path(options),
            max_workers=options.max_workers,
        )
        agent_daemon.serve_forever()
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
            max_workers=options.max_workers,
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


def _named_values(
    values: Sequence[str],
    label: str,
) -> Tuple[Tuple[str, str], ...]:
    result = []
    for value in values:
        name, separator, purpose = value.partition("=")
        if not separator or not name.strip() or not purpose.strip():
            raise ValueError(f"{label} must use NAME=PURPOSE")
        result.append((name.strip(), purpose.strip()))
    return tuple(result)


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


def _socket_path(options: argparse.Namespace) -> Path:
    if options.socket:
        return options.socket.expanduser().resolve()
    return options.state_dir.expanduser().resolve() / "run" / "daemon.sock"


def _print_json(value: object, stream=None) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )
