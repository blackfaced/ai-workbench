# Architecture decisions

This index is the navigation entry for repository governance and structure decisions. A decision file remains the source of truth for its rationale and consequences; this page only identifies its current role.

## Current decisions

| ADR | Status | Purpose |
| --- | --- | --- |
| [0001 — Repository scope and structure](0001-repository-scope-and-structure.md) | Accepted; primary purpose updated by 0010 | Keep top-level organization by artifact type. |
| [0009 — Reproduce development environments](0009-reproducible-development-environments.md) | Accepted, illustrative | Describe the generic fresh-machine bootstrap pattern without recording a real host. |
| [0010 — Environment-first repository scope](0010-environment-first-repository-scope.md) | Accepted | Make development-environment maintenance the primary scope and retire the orchestrator runtime. |
| [0011 — Generic rule source and distribution](0011-generic-rules-source-and-distribution.md) | Accepted | Keep generic rules in one source and distribute them without copying project-specific content. |
| [0012 — Home Mac maintenance validation](0012-home-mac-maintenance-validation.md) | Accepted | Require explicit Profile selection and record the verified home-Mac maintenance boundary. |
| [0013 — Project-owned agent context](0013-project-owned-agent-context.md) | Accepted | Keep project context owned by the target repository rather than duplicating it in AIWB. |

## Historical decisions

These records explain the retired orchestrator design. They are not current implementation guidance.

| ADR | Status | Historical subject |
| --- | --- | --- |
| [0002 — Generic unattended agent orchestrator](0002-unattended-agent-orchestrator.md) | Retired by 0010 | Original orchestrator proposal. |
| [0003 — Upstream engineering Skills and contract drafts](0003-upstream-engineering-skills-and-contract-drafts.md) | Retired by 0010 | Earlier boundary between upstream Skills and an AIWB runtime. |
| [0004 — Subscription-first resource boundaries](0004-subscription-first-resource-boundaries.md) | Retired by 0010 | Runtime resource-provider boundaries. |
| [0005 — Content-addressed evidence](0005-content-addressed-evidence.md) | Retired by 0010 | Runtime evidence retention. |
| [0006 — ExecutionSnapshot and RunLedger](0006-execution-snapshot-run-ledger.md) | Retired by 0010 | Runtime control-state authority. |
| [0008 — Delegate the agent loop to agent harnesses](0008-delegate-agent-loop-to-agent-harnesses.md) | Retired by 0010 | Runtime ownership of the agent loop. |

## Candidate

| ADR | Status | Purpose |
| --- | --- | --- |
| [0014 — Maintained project context renderer](0014-project-context-declaration.md) | Candidate; not merged | Explore a pinned local entry for rendering project-owned context. |
