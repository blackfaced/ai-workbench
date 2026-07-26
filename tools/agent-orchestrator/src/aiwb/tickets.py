from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import yaml


_TITLE = re.compile(r"^# Tickets:\s*(?P<title>.+?)\s*$")
_TICKET = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_WHAT = re.compile(r"^\*\*What to build:\*\*\s*(?P<value>.+?)\s*$")
_BLOCKED_BY = re.compile(r"^\*\*Blocked by:\*\*\s*(?P<value>.+?)\s*$")
_ACCEPTANCE = re.compile(r"^- \[ \]\s+(?P<value>.+?)\s*$")


class TicketDraftError(ValueError):
    pass


@dataclass(frozen=True)
class TicketContractDraftResult:
    output: str
    ticket_count: int
    acceptance_count: int
    status: str = "draft"


@dataclass(frozen=True)
class _Ticket:
    title: str
    requirement: str
    blocked_by: Tuple[str, ...]
    acceptance: Tuple[str, ...]


class TicketContractDraftBuilder:
    """Convert a local `to-tickets` document into a deliberately unapproved Contract."""

    def create(
        self,
        tickets_path: Path,
        repository: Path,
        output_path: Path,
        force: bool = False,
    ) -> TicketContractDraftResult:
        tickets_path = Path(tickets_path).expanduser().resolve()
        repository = Path(repository).expanduser().resolve()
        output_path = Path(output_path).expanduser().resolve()
        if not tickets_path.is_file():
            raise TicketDraftError(f"tickets file is not readable: {tickets_path}")
        if not repository.is_dir():
            raise TicketDraftError(f"repository is not a directory: {repository}")
        if output_path.exists() and not force:
            raise TicketDraftError(f"draft output already exists: {output_path}")

        title, requirement, tickets = _parse_tickets(tickets_path)
        document = _draft_document(title, requirement, tickets, repository, tickets_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump(document, sort_keys=False),
            encoding="utf-8",
        )
        return TicketContractDraftResult(
            output=str(output_path),
            ticket_count=len(tickets),
            acceptance_count=sum(len(ticket.acceptance) for ticket in tickets),
        )


def _parse_tickets(path: Path) -> Tuple[str, str, Tuple[_Ticket, ...]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = ""
    requirement = ""
    raw_tickets: List[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        if not title:
            match = _TITLE.match(line)
            if match is not None:
                title = match.group("title")
            continue
        match = _TICKET.match(line)
        if match is not None:
            current = {
                "title": match.group("title"),
                "requirement": "",
                "blocked_by": [],
                "acceptance": [],
            }
            raw_tickets.append(current)
            continue
        if current is None:
            if line.strip() and not requirement:
                requirement = line.strip()
            continue
        match = _WHAT.match(line)
        if match is not None:
            current["requirement"] = match.group("value")
            continue
        match = _BLOCKED_BY.match(line)
        if match is not None:
            current["blocked_by"] = _blockers(match.group("value"))
            continue
        match = _ACCEPTANCE.match(line)
        if match is not None:
            current["acceptance"].append(match.group("value"))

    if not title:
        raise TicketDraftError("tickets file must start with '# Tickets: <title>'")
    if not raw_tickets:
        raise TicketDraftError("tickets file must contain at least one '## <ticket>' section")
    tickets = tuple(
        _Ticket(
            title=str(ticket["title"]),
            requirement=str(ticket["requirement"]),
            blocked_by=tuple(ticket["blocked_by"]),
            acceptance=tuple(ticket["acceptance"]),
        )
        for ticket in raw_tickets
    )
    titles = {ticket.title for ticket in tickets}
    if len(titles) != len(tickets):
        raise TicketDraftError("ticket titles must be unique")
    for ticket in tickets:
        if not ticket.requirement:
            raise TicketDraftError(f"ticket is missing 'What to build': {ticket.title}")
        if not ticket.acceptance:
            raise TicketDraftError(f"ticket is missing acceptance criteria: {ticket.title}")
        unknown = set(ticket.blocked_by) - titles
        if unknown:
            raise TicketDraftError(
                f"ticket has unknown blockers: {ticket.title}: {', '.join(sorted(unknown))}"
            )
    return title, requirement or f"Implement the approved tickets for {title}.", tickets


def _blockers(value: str) -> List[str]:
    normalized = value.strip()
    if normalized.lower().startswith("none"):
        return []
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _draft_document(
    title: str,
    requirement: str,
    tickets: Tuple[_Ticket, ...],
    repository: Path,
    tickets_path: Path,
) -> dict[str, object]:
    todo_ids = {ticket.title: f"T-{index}" for index, ticket in enumerate(tickets, start=1)}
    acceptance = []
    todos = []
    for todo_index, ticket in enumerate(tickets, start=1):
        test_ids = []
        for acceptance_index, statement in enumerate(ticket.acceptance, start=1):
            test_id = f"AC-{todo_index}-{acceptance_index}"
            acceptance.append({"id": test_id, "statement": statement})
            test_ids.append(test_id)
        todos.append(
            {
                "id": todo_ids[ticket.title],
                "title": ticket.title,
                "depends_on": [todo_ids[blocker] for blocker in ticket.blocked_by],
                "test_ids": test_ids,
                "test": {
                    "command": ["REPLACE_WITH_APPROVED_TEST_COMMAND"],
                    "allowed_paths": ["REPLACE_WITH_APPROVED_TEST_PATH"],
                    "timeout_seconds": 600,
                },
            }
        )
    return {
        "schema_version": 1,
        "draft": {
            "source_tickets": str(tickets_path),
            "review_required": [
                "Replace each placeholder test command and allowed test path with project-approved capabilities.",
                "Review the agent provider, harness, permissions, and candidate publication policy.",
                "Set approval status, approver, and timestamp only after the Contract is complete.",
            ],
        },
        "goal": {
            "id": _goal_id(title),
            "title": title,
            "requirement": requirement,
            "acceptance": acceptance,
        },
        "approval": {
            "status": "draft",
            "approved_by": "",
            "approved_at": "",
        },
        "agent": {"provider": "codex"},
        "project": {"repo": str(repository), "base_ref": "main"},
        "todos": todos,
    }


def _goal_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"tickets-{slug or 'draft'}"
