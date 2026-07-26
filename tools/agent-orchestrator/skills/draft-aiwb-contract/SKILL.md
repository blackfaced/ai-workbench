---
name: draft-aiwb-contract
description: Create an unapproved AI Workbench Contract draft from an already-approved local tickets.md breakdown. Use after to-tickets and before any unattended Goal is approved.
---

# Draft AI Workbench Contract

Use this Skill only after the owner has approved a local `tickets.md` breakdown
created by `$to-tickets`. It is a bridge between upstream planning and AI
Workbench's execution boundary; it does not replace either.

## Create the draft

Require concrete repository, tickets, and output paths. Run:

```bash
aiwb goal draft --repo /path/to/repository \
  --tickets /path/to/repository/tickets.md \
  --output /path/to/repository/feature.contract.yaml
```

In this source checkout, when `aiwb` is not installed on `PATH`, use:

```bash
PYTHONPATH=tools/agent-orchestrator/src python3 -m aiwb goal draft \
  --repo /path/to/repository \
  --tickets /path/to/repository/tickets.md \
  --output /path/to/repository/feature.contract.yaml
```

The command maps ticket titles to Todos, `Blocked by` edges to `depends_on`,
and ticket acceptance criteria to test IDs. It accepts only the standard local
`tickets.md` template; tracker fetching remains the issue tracker's and
upstream Skill's responsibility.

## Review boundary

The result is deliberately not executable:

- `approval.status` stays `draft`.
- Every Todo has placeholder test commands and allowed paths.
- Harness choice, permissions, provider, candidate publication, and final test
  capabilities remain owner review decisions.

Explain the generated draft and the required review. Do not change the approval
status, fill placeholders, submit a Goal, start a daemon, or infer a Harness.
Use `$run-approved-goal` only after the owner has completed and explicitly
approved the Contract.
