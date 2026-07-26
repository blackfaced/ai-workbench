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
release should be consumed at a reviewed immutable revision rather than a
moving installer default or tag.

## Decision

Keep Matt Skills optional and project-local. Offer one reviewed `matt`
`engineering` profile containing the dependency closure of `ask-matt`'s
engineering routes, pinned to the reviewed source commit. `ask-ai-workbench`
recommends an installed `ask-matt` router for general engineering work instead
of copying its routing logic.

AI Workbench owns only a thin local `tickets.md` to Contract-draft bridge. It
preserves ticket slices, acceptance criteria, and blocking edges, but generates
an intentionally unapproved Contract with test placeholders. The owner must
still choose approved commands, Harnesses, permissions, and approval before an
unattended Run can begin.

Do not invoke upstream `implement` inside the durable Runner: it owns its own
interactive commit and review loop, while the Runner owns worktrees,
checkpoints, integration, and Evidence.

## Consequences

The planning and interactive implementation experience can evolve with the
upstream project. AI Workbench remains narrow at its unique execution boundary,
and a malformed or incomplete ticket breakdown cannot silently become an
authorized overnight Goal.
