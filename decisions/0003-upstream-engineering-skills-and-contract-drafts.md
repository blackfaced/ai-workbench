# 0003 - Reuse Upstream Engineering Skills and Bridge Only at the Contract Boundary

## Status

Accepted

## Context

AI Workbench provides durable, unattended execution: approved Contracts,
isolated Todo worktrees, test gates, Harnesses, Evidence, and recovery. It
should not independently recreate interactive engineering disciplines already
maintained upstream, such as idea grilling, specification writing, ticket
splitting, TDD, and architecture review.

`mattpocock/skills` supplies those small, composable Skills. Its engineering
router is useful only when its referenced Skills are present, and its public
release should be consumed at a reviewed release tag with the resolved commit
recorded rather than a moving installer default or branch.

## Decision

Keep Matt Skills optional and project-local. Offer one reviewed `matt`
`engineering` profile containing the dependency closure of `ask-matt`'s
engineering routes, pinned to the reviewed release tag and recorded commit. `ask-ai-workbench`
recommends an installed `ask-matt` router for general engineering work instead
of copying its routing logic.

Maintain one first-party `engineering-principles` Skill as the installable
engineering doctrine. It semantically synthesizes the reviewed Karpathy
guidelines with Ponytail's implementation ladder, adds an explicit
complexity-justification check and Stop When Done rule, and avoids copying two
overlapping upstream Skills into every repository. Skip it where equivalent
repository instructions are already authoritative.

An intentional simplification with a non-obvious known ceiling may use a
`lazy:` comment. That marker means complete but deliberately limited, not
unfinished or incorrect; it points to an Issue only when a concrete future
trigger needs tracking.

Offer only upstream `ponytail-review` through a reviewed, project-local
`ponytail=review` profile. It is an on-demand complexity-detection pass, not a
second always-on doctrine. Do not install the main Ponytail Skill, lifecycle
hooks, intensity modes, or Caveman through this profile.

Pack updates are explicit. `--update-pack` re-applies the named profile from
the catalog's new reviewed release and reports it as an update, not an install.
It never updates from a moving branch or changes user-global Skills.

AI Workbench owns only a thin local `tickets.md` to Contract-draft bridge. It
preserves ticket slices, acceptance criteria, and blocking edges, but generates
an intentionally unapproved Contract with test placeholders. The owner must
still choose approved commands, Harnesses, permissions, and approval before an
unattended Run can begin.

At that seam, one read-only Goal intake module chooses the cheapest viable
path. Small tasks return to the installed `ask-matt` interactive router.
Durable, multi-Todo, Harness, recovery, or unattended work receives an AI
Workbench execution envelope plus actionable readiness blockers and one next
action. CLI, MCP, and the project-local intake Skill adapt the same result; none
may approve, submit, execute, or copy upstream engineering workflows.

Do not invoke upstream `implement` inside the durable Runner: it owns its own
interactive commit and review loop, while the Runner owns worktrees,
checkpoints, integration, and Evidence.

## Consequences

The planning and interactive implementation experience can evolve with the
upstream project. AI Workbench remains narrow at its unique execution boundary,
and a malformed or incomplete ticket breakdown cannot silently become an
authorized overnight Goal.
