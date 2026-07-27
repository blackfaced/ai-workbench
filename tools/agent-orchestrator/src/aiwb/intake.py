from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import yaml

from .project import ProjectConfigError, ProjectPolicy
from .runner import ContractError, preview_execution, preview_todo_graph
from .skills import SkillCatalog
from .tickets import TicketContractDraftBuilder


_DURABILITY_TERMS = (
    "browser",
    "durable",
    "e2e",
    "harness",
    "kubernetes",
    "overnight",
    "recover",
    "recovery",
    "unattended",
)


@dataclass(frozen=True)
class IntakeBlocker:
    code: str
    message: str
    action: str


@dataclass(frozen=True)
class GoalIntakeResult:
    source: str
    readiness: str
    cheapest_viable_path: str
    blockers: Tuple[IntakeBlocker, ...]
    execution_envelope: Mapping[str, object]
    next_action: str
    daemon_status: str
    approval_required: bool
    submission_required: bool
    planning_handoff: Mapping[str, object] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "readiness": self.readiness,
            "cheapest_viable_path": self.cheapest_viable_path,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "execution_envelope": dict(self.execution_envelope),
            "next_action": self.next_action,
            "daemon_status": self.daemon_status,
            "approval_required": self.approval_required,
            "submission_required": self.submission_required,
            "planning_handoff": dict(self.planning_handoff),
            "warnings": list(self.warnings),
        }


class GoalIntake:
    """Choose the cheapest engineering path and inspect unattended readiness."""

    def __init__(
        self,
        daemon_probe: Optional[Callable[[], bool]] = None,
        skill_catalog: Optional[SkillCatalog] = None,
    ) -> None:
        self._daemon_probe = daemon_probe or (lambda: False)
        self._skills = skill_catalog or SkillCatalog()
        self._tickets = TicketContractDraftBuilder()

    def inspect(
        self,
        *,
        repository: Path,
        contract_path: Optional[Path] = None,
        tickets_path: Optional[Path] = None,
        handoff_path: Optional[Path] = None,
        task: str = "",
    ) -> GoalIntakeResult:
        repository = Path(repository).expanduser().resolve()
        if not repository.is_dir():
            raise ValueError(f"repository is not a directory: {repository}")
        sources = tuple(
            path
            for path in (contract_path, tickets_path, handoff_path)
            if path is not None
        )
        if len(sources) != 1:
            raise ValueError(
                "intake requires exactly one Contract, tickets, or handoff path"
            )
        if handoff_path is not None:
            return self._inspect_handoff(repository, Path(handoff_path))
        daemon_status = "ok" if self._daemon_probe() else "unavailable"
        if tickets_path is not None:
            return self._inspect_tickets(
                repository,
                Path(tickets_path),
                task,
                daemon_status,
            )
        return self._inspect_contract(
            repository,
            Path(contract_path),
            task,
            daemon_status,
        )

    def _inspect_handoff(
        self,
        repository: Path,
        handoff_path: Path,
    ) -> GoalIntakeResult:
        try:
            data = _read_mapping(handoff_path, "planning handoff")
        except ValueError as error:
            blocker = IntakeBlocker(
                code="handoff_validation",
                message=str(error),
                action=(
                    "Provide valid JSON using aiwb.planning-handoff "
                    "schema_version 1 or a bare issue document."
                ),
            )
            return GoalIntakeResult(
                source="handoff",
                readiness="blocked",
                cheapest_viable_path="undetermined",
                blockers=(blocker,),
                execution_envelope={},
                next_action="resolve_handoff_blockers",
                daemon_status="not_required",
                approval_required=False,
                submission_required=False,
            )
        if data.get("kind") == "aiwb.planning-handoff":
            if data.get("schema_version") != 1:
                blocker = IntakeBlocker(
                    code="unsupported_handoff_schema",
                    message=(
                        "Planning handoff schema_version is unsupported: "
                        f"{data.get('schema_version')!r}."
                    ),
                    action=(
                        "Provide aiwb.planning-handoff schema_version 1 or a "
                        "bare issue JSON document."
                    ),
                )
                return GoalIntakeResult(
                    source="handoff",
                    readiness="blocked",
                    cheapest_viable_path="undetermined",
                    blockers=(blocker,),
                    execution_envelope={},
                    next_action="use_supported_handoff_schema",
                    daemon_status="not_required",
                    approval_required=False,
                    submission_required=False,
                )
            normalized = _normalize_versioned_handoff(data)
        else:
            if not _is_bare_issue(data):
                blocker = IntakeBlocker(
                    code="handoff_validation",
                    message=(
                        "Planning handoff must be a supported versioned envelope "
                        "or bare issue JSON document."
                    ),
                    action=(
                        "Provide aiwb.planning-handoff schema_version 1 or a "
                        "bare issue JSON document with number, title, and body."
                    ),
                )
                return GoalIntakeResult(
                    source="handoff",
                    readiness="blocked",
                    cheapest_viable_path="undetermined",
                    blockers=(blocker,),
                    execution_envelope={},
                    next_action="resolve_handoff_blockers",
                    daemon_status="not_required",
                    approval_required=False,
                    submission_required=False,
                )
            normalized = _normalize_bare_issue(data)
        goal = normalized["goal"]
        acceptance = normalized["acceptance"]
        todos = tuple(normalized["todos"])
        handoff_blockers = []
        warnings = []
        provenance = normalized["provenance"]
        if not provenance:
            handoff_blockers.append(
                IntakeBlocker(
                    code="handoff_provenance",
                    message="The planning handoff does not identify its source.",
                    action="Add the planning system and stable source reference.",
                )
            )
        todo_ids = {
            str(todo.get("id"))
            for todo in todos
            if isinstance(todo.get("id"), str) and todo.get("id")
        }
        dependencies_ok = True
        for todo in todos:
            todo_id = str(todo.get("id", "unknown"))
            dependencies = todo.get("depends_on")
            if (
                not isinstance(dependencies, list)
                or not all(isinstance(item, str) and item for item in dependencies)
                or set(dependencies) - todo_ids
            ):
                dependencies_ok = False
            acceptance_ids = todo.get("acceptance_ids")
            if not isinstance(acceptance_ids, list) or not acceptance_ids:
                warnings.append(f"Todo {todo_id} has no acceptance_ids mapping.")
        if not dependencies_ok:
            handoff_blockers.append(
                IntakeBlocker(
                    code="todo_dependencies",
                    message=(
                        "Planning handoff Todo relationships are incomplete "
                        "or invalid."
                    ),
                    action="Add explicit depends_on lists using known Todo ids.",
                )
            )
        graph = {
            str(todo["id"]): tuple(
                item
                for item in todo.get("depends_on", ())
                if isinstance(item, str) and item in todo_ids
            )
            for todo in todos
            if isinstance(todo.get("id"), str) and todo.get("id")
        }
        try:
            envelope = preview_todo_graph(
                goal_id=str(goal.get("id", "handoff-intake-preview")),
                approval_status="planning",
                provider="unselected",
                model=None,
                todo_dependencies=graph or {"T-1": ()},
            ).to_dict()
        except ContractError:
            handoff_blockers.append(
                IntakeBlocker(
                    code="todo_dependencies",
                    message=(
                        "Planning handoff Todo relationships must form an "
                        "acyclic graph."
                    ),
                    action="Remove cyclic Todo dependencies and rerun intake.",
                )
            )
            envelope = preview_todo_graph(
                goal_id=str(goal.get("id", "handoff-intake-preview")),
                approval_status="planning",
                provider="unselected",
                model=None,
                todo_dependencies={
                    todo_id: () for todo_id in graph
                } or {"T-1": ()},
            ).to_dict()
        requirement = str(goal.get("requirement", ""))
        if (
            acceptance
            and len(todos) <= 1
            and not handoff_blockers
            and not _has_durability_signal(requirement)
        ):
            return self._interactive_result(
                repository,
                source="handoff",
                envelope=envelope,
                daemon_status="not_required",
                planning_handoff=normalized,
            )
        blockers = list(handoff_blockers)
        blockers.extend(_policy_blockers(repository))
        if not acceptance:
            blockers.append(
                IntakeBlocker(
                    code="acceptance_boundary",
                    message=(
                        "The planning handoff does not contain accepted "
                        "acceptance criteria."
                    ),
                    action=(
                        "Review and add acceptance criteria before drafting "
                        "a Contract."
                    ),
                )
            )
        blockers.append(
            IntakeBlocker(
                code="contract_draft",
                message=(
                    "A planning handoff needs a reviewed Contract draft before "
                    "unattended readiness can be decided."
                ),
                action="Create a Contract draft from the preserved planning handoff.",
            )
        )
        return GoalIntakeResult(
            source="handoff",
            readiness="blocked",
            cheapest_viable_path="ai_workbench_unattended",
            blockers=_dedupe(blockers),
            execution_envelope=envelope,
            next_action=(
                "resolve_handoff_blockers"
                if handoff_blockers or not acceptance
                else "create_contract_draft"
            ),
            daemon_status="not_required",
            approval_required=True,
            submission_required=True,
            planning_handoff=normalized,
            warnings=tuple(warnings),
        )

    def _inspect_tickets(
        self,
        repository: Path,
        tickets_path: Path,
        task: str,
        daemon_status: str,
    ) -> GoalIntakeResult:
        inspection = self._tickets.inspect(tickets_path)
        envelope = preview_todo_graph(
            goal_id="tickets-intake-preview",
            approval_status="tickets",
            provider="unselected",
            model=None,
            todo_dependencies=dict(inspection.todo_dependencies),
        ).to_dict()
        durable = (
            inspection.ticket_count > 1
            or _has_durability_signal(f"{inspection.requirement} {task}")
        )
        if not durable:
            return self._interactive_result(
                repository,
                source="tickets",
                envelope=envelope,
                daemon_status=daemon_status,
            )
        blockers = list(_policy_blockers(repository))
        blockers.append(
            IntakeBlocker(
                code="contract_draft",
                message=(
                    "Accepted tickets need a reviewed Contract draft before "
                    "unattended readiness can be decided."
                ),
                action="Run aiwb goal draft, then review provider, resources, and tests.",
            )
        )
        return GoalIntakeResult(
            source="tickets",
            readiness="blocked",
            cheapest_viable_path="ai_workbench_unattended",
            blockers=_dedupe(blockers),
            execution_envelope=envelope,
            next_action="create_contract_draft",
            daemon_status=daemon_status,
            approval_required=True,
            submission_required=True,
        )

    def _inspect_contract(
        self,
        repository: Path,
        contract_path: Path,
        task: str,
        daemon_status: str,
    ) -> GoalIntakeResult:
        data = _read_mapping(contract_path, "Contract")
        todos = _contract_todos(data)
        graph = _safe_todo_graph(todos)
        goal = data.get("goal")
        goal = goal if isinstance(goal, dict) else {}
        agent = data.get("agent")
        agent = agent if isinstance(agent, dict) else {}
        approval = data.get("approval")
        approval = approval if isinstance(approval, dict) else {}
        requirement = str(goal.get("requirement", ""))
        durable = (
            len(todos) > 1
            or _contract_has_heavy_capability(data, todos)
            or _has_durability_signal(f"{requirement} {task}")
        )
        try:
            envelope = preview_execution(contract_path).to_dict()
            preview_error = ""
        except (ContractError, ProjectConfigError, OSError, ValueError) as error:
            preview_error = str(error)
            envelope = preview_todo_graph(
                goal_id=str(goal.get("id", "contract-intake-preview")),
                approval_status=str(approval.get("status", "draft")),
                provider=str(agent.get("provider", "unselected")),
                model=(
                    str(agent["model"])
                    if isinstance(agent.get("model"), str)
                    else None
                ),
                todo_dependencies=graph,
                resources=(
                    data["resources"]
                    if isinstance(data.get("resources"), dict)
                    else {}
                ),
            ).to_dict()
        if not durable:
            return self._interactive_result(
                repository,
                source="contract",
                envelope=envelope,
                daemon_status=daemon_status,
            )

        blockers = list(_contract_blockers(repository, data, todos))
        if preview_error and not blockers:
            blockers.append(
                IntakeBlocker(
                    code="contract_validation",
                    message=preview_error,
                    action="Resolve the Contract validation error and rerun intake.",
                )
            )
        approval_status = approval.get("status")
        if blockers:
            return GoalIntakeResult(
                source="contract",
                readiness="blocked",
                cheapest_viable_path="ai_workbench_unattended",
                blockers=_dedupe(blockers),
                execution_envelope=envelope,
                next_action="resolve_blockers",
                daemon_status=daemon_status,
                approval_required=True,
                submission_required=True,
            )
        if approval_status != "approved":
            return GoalIntakeResult(
                source="contract",
                readiness="ready_for_approval",
                cheapest_viable_path="ai_workbench_unattended",
                blockers=(),
                execution_envelope=envelope,
                next_action="approve_contract",
                daemon_status=daemon_status,
                approval_required=True,
                submission_required=True,
            )
        if daemon_status != "ok":
            blocker = IntakeBlocker(
                code="daemon_state",
                message="The local AI Workbench daemon is unavailable.",
                action="Start or install the daemon, then rerun intake.",
            )
            return GoalIntakeResult(
                source="contract",
                readiness="blocked",
                cheapest_viable_path="ai_workbench_unattended",
                blockers=(blocker,),
                execution_envelope=envelope,
                next_action="start_daemon",
                daemon_status=daemon_status,
                approval_required=False,
                submission_required=True,
            )
        return GoalIntakeResult(
            source="contract",
            readiness="ready_to_submit",
            cheapest_viable_path="ai_workbench_unattended",
            blockers=(),
            execution_envelope=envelope,
            next_action="submit_contract",
            daemon_status=daemon_status,
            approval_required=False,
            submission_required=True,
        )

    def _interactive_result(
        self,
        repository: Path,
        *,
        source: str,
        envelope: Mapping[str, object],
        daemon_status: str,
        planning_handoff: Optional[Mapping[str, object]] = None,
    ) -> GoalIntakeResult:
        ask_matt = any(
            skill.name == "ask-matt"
            for skill in self._skills.inspect(repository).skills
        )
        return GoalIntakeResult(
            source=source,
            readiness="interactive",
            cheapest_viable_path="interactive_matt",
            blockers=(),
            execution_envelope=envelope,
            next_action=(
                "invoke_ask_matt" if ask_matt else "setup_matt_skills"
            ),
            daemon_status=daemon_status,
            approval_required=False,
            submission_required=False,
            planning_handoff=planning_handoff or {},
        )


def _contract_blockers(
    repository: Path,
    data: Mapping[str, object],
    todos: Sequence[Mapping[str, object]],
) -> Tuple[IntakeBlocker, ...]:
    blockers = list(_policy_blockers(repository))
    goal = data.get("goal")
    goal = goal if isinstance(goal, dict) else {}
    acceptance = goal.get("acceptance")
    acceptance_ids = {
        str(item.get("id"))
        for item in acceptance
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("statement"), str)
        and str(item.get("statement")).strip()
    } if isinstance(acceptance, list) else set()
    if not acceptance_ids:
        blockers.append(
            IntakeBlocker(
                "acceptance_boundary",
                "The Goal needs at least one concrete acceptance statement.",
                "Add accepted Goal acceptance criteria and map each Todo to them.",
            )
        )

    todo_ids = {
        str(todo.get("id"))
        for todo in todos
        if isinstance(todo.get("id"), str) and todo.get("id")
    }
    dependencies_ok = bool(todos)
    harness_ok = bool(todos)
    for todo in todos:
        dependencies = todo.get("depends_on")
        if (
            not isinstance(dependencies, list)
            or not all(isinstance(item, str) and item for item in dependencies)
            or set(dependencies) - todo_ids
        ):
            dependencies_ok = False
        test_ids = todo.get("test_ids")
        if (
            not isinstance(test_ids, list)
            or not test_ids
            or not set(str(item) for item in test_ids) <= acceptance_ids
        ):
            blockers.append(
                IntakeBlocker(
                    "acceptance_boundary",
                    "Every Todo must map to known Goal acceptance criteria.",
                    "Set each Todo test_ids list to accepted Goal criteria.",
                )
            )
        test = todo.get("test")
        if not isinstance(test, dict):
            harness_ok = False
            continue
        command = test.get("command")
        paths = test.get("allowed_paths")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) and item for item in command)
            or not isinstance(paths, list)
            or not paths
            or not all(isinstance(item, str) and item for item in paths)
        ):
            harness_ok = False
        if "production" in str(test.get("harness", "")).lower():
            blockers.append(
                IntakeBlocker(
                    "non_production",
                    "Production Harness targets are outside AI Workbench scope.",
                    "Select an approved local or non-production Harness profile.",
                )
            )
    if not dependencies_ok:
        blockers.append(
            IntakeBlocker(
                "todo_dependencies",
                "Every Todo needs an explicit, valid depends_on list.",
                "Declare the accepted acyclic Todo dependency graph.",
            )
        )
    if not harness_ok:
        blockers.append(
            IntakeBlocker(
                "harness_configuration",
                "Every Todo needs an approved test command and protected test paths.",
                "Bind each Todo to project-approved executable acceptance Evidence.",
            )
        )

    agent = data.get("agent")
    if (
        not isinstance(agent, dict)
        or agent.get("provider") not in {"codex", "claude-code"}
    ):
        blockers.append(
            IntakeBlocker(
                "provider_selection",
                "Unattended intake requires an explicit Codex or Claude Code provider.",
                "Set agent.provider and review the optional fixed model.",
            )
        )
    if "resources" not in data or not isinstance(data.get("resources"), dict):
        blockers.append(
            IntakeBlocker(
                "resource_policy",
                "The draft must record the subscription resource-policy decision.",
                "Add resources: {} or reviewed positive optional boundaries.",
            )
        )
    return _dedupe(blockers)


def _policy_blockers(repository: Path) -> Tuple[IntakeBlocker, ...]:
    path = repository / ".ai-workbench" / "workflow.yaml"
    try:
        data = _read_mapping(path, "project workflow")
    except ValueError as error:
        return (
            IntakeBlocker(
                "permissions",
                str(error),
                "Run aiwb setup, then review and approve the project workflow.",
            ),
        )
    blockers = []
    project = data.get("project")
    project = project if isinstance(project, dict) else {}
    if data.get("status") != "approved" or project.get("trusted") is not True:
        blockers.append(
            IntakeBlocker(
                "permissions",
                "Project policy and repository trust must be explicitly approved.",
                "Review workflow capabilities, set trusted true, then approve it.",
            )
        )
    capabilities = data.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    commands = capabilities.get("commands")
    if (
        not isinstance(commands, dict)
        or not commands
        or not any(
            isinstance(item, dict) and item.get("approved") is True
            for item in commands.values()
        )
    ):
        blockers.append(
            IntakeBlocker(
                "harness_configuration",
                "Project policy needs at least one approved test capability.",
                "Approve the exact command used for acceptance Evidence.",
            )
        )
    if _contains_production(data):
        blockers.append(
            IntakeBlocker(
                "non_production",
                "Project policy contains a production environment or target.",
                "Remove production targets and use local or non-production profiles.",
            )
        )
    try:
        ProjectPolicy.load(path)
    except ProjectConfigError as error:
        if not blockers:
            blockers.append(
                IntakeBlocker(
                    "permissions",
                    str(error),
                    "Resolve the project policy validation error.",
                )
            )
    return _dedupe(blockers)


def _contract_todos(data: Mapping[str, object]) -> Tuple[Mapping[str, object], ...]:
    value = data.get("todos")
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, dict))
    legacy = data.get("todo")
    return (legacy,) if isinstance(legacy, dict) else ()


def _safe_todo_graph(
    todos: Sequence[Mapping[str, object]],
) -> Mapping[str, Sequence[str]]:
    if not todos:
        return {"T-1": ()}
    ids = [
        str(todo.get("id") or f"T-{index}")
        for index, todo in enumerate(todos, start=1)
    ]
    known = set(ids)
    graph = {}
    for todo_id, todo in zip(ids, todos):
        dependencies = todo.get("depends_on")
        graph[todo_id] = tuple(
            item
            for item in dependencies
            if isinstance(item, str) and item in known and item != todo_id
        ) if isinstance(dependencies, list) else ()
    try:
        preview_todo_graph(
            goal_id="validation",
            approval_status="draft",
            provider="unselected",
            model=None,
            todo_dependencies=graph,
        )
    except ContractError:
        return {todo_id: () for todo_id in ids}
    return graph


def _contract_has_heavy_capability(
    data: Mapping[str, object],
    todos: Sequence[Mapping[str, object]],
) -> bool:
    if isinstance(data.get("resources"), dict) and bool(data["resources"]):
        return True
    if data.get("image") or data.get("publishing"):
        return True
    return any(
        isinstance(todo.get("test"), dict)
        and bool(todo["test"].get("harness"))
        for todo in todos
    )


def _has_durability_signal(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in _DURABILITY_TERMS)


def _contains_production(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_production(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_production(item) for item in value)
    return isinstance(value, str) and value.strip().lower() == "production"


def _normalize_versioned_handoff(
    data: Mapping[str, object],
) -> Mapping[str, object]:
    goal = data.get("goal")
    goal = goal if isinstance(goal, dict) else {}
    acceptance = goal.get("acceptance")
    acceptance = acceptance if isinstance(acceptance, list) else []
    todos = data.get("todos")
    todos = todos if isinstance(todos, list) else []
    provenance = data.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    return {
        "schema_version": data.get("schema_version"),
        "kind": data.get("kind"),
        "format": "versioned",
        "provenance": dict(provenance),
        "goal": {
            key: goal[key]
            for key in ("id", "title", "requirement")
            if key in goal
        },
        "acceptance": [
            dict(item) for item in acceptance if isinstance(item, dict)
        ],
        "todos": [dict(item) for item in todos if isinstance(item, dict)],
    }


def _normalize_bare_issue(data: Mapping[str, object]) -> Mapping[str, object]:
    number = data.get("number")
    title = data.get("title")
    body = data.get("body")
    html_url = data.get("html_url", data.get("url"))
    repository_url = data.get("repository_url")
    repository_name = ""
    if isinstance(repository_url, str):
        marker = "/repos/"
        parsed_path = urlparse(repository_url).path
        if marker in parsed_path:
            repository_name = parsed_path.split(marker, 1)[1].strip("/")
    if not repository_name and isinstance(html_url, str):
        parts = tuple(
            part for part in urlparse(html_url).path.split("/") if part
        )
        if len(parts) >= 4 and parts[2] == "issues":
            repository_name = "/".join(parts[:2])
    issue_id = (
        f"github:{repository_name}#{number}"
        if repository_name and isinstance(number, int)
        else "github:issue"
    )
    provenance = {"system": "github"}
    if repository_name:
        provenance["repository"] = repository_name
    if isinstance(number, int):
        provenance["issue"] = number
    if isinstance(html_url, str) and html_url:
        provenance["url"] = html_url
    return {
        "schema_version": 1,
        "kind": "aiwb.planning-handoff",
        "format": "bare_issue",
        "provenance": provenance,
        "goal": {
            "id": issue_id,
            **({"title": title} if isinstance(title, str) else {}),
            **({"requirement": body} if isinstance(body, str) else {}),
        },
        "acceptance": [],
        "todos": [],
    }


def _is_bare_issue(data: Mapping[str, object]) -> bool:
    return (
        isinstance(data.get("number"), int)
        and isinstance(data.get("title"), str)
        and bool(str(data["title"]).strip())
        and isinstance(data.get("body"), str)
    )


def _read_mapping(path: Path, name: str) -> Mapping[str, object]:
    path = Path(path).expanduser().resolve()
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read {name}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a YAML mapping")
    return value


def _dedupe(blockers: Sequence[IntakeBlocker]) -> Tuple[IntakeBlocker, ...]:
    by_code = {}
    for blocker in blockers:
        by_code.setdefault(blocker.code, blocker)
    return tuple(by_code[code] for code in sorted(by_code))
