---
name: run-approved-goal
version: 1
description: Submit and observe one approved AI Workbench Agent Harness Run.
---

# Run Approved Goal

Require a schema-v5 Contract with a matching external Execution Approval
artifact. Confirm that `aiwb goal preflight` displayed the exact instructions,
base commit, complete Agent Harness Profile, resolved extensions, permissions,
verification, image and publication settings before the owner ran `aiwb goal
approve`. Do not complete missing choices or alter the Contract after approval.

Call `aiwb_goal_submit` once, then report the durable `run_id`. Progress and
report calls are projections of the RunLedger. The daemon prepares the owned
worktree and starts one bounded Attempt; the Harness owns planning and any
internal agents. A completed Attempt is not acceptance: only successful
Verification Harness Evidence accepts a Candidate.

An interrupted Attempt is terminal. On an explicit retry, the daemon creates a
fresh Attempt and does not resume a Harness session. Never switch Driver,
Model, permissions, capabilities or extensions, and never silently fall back to
another provider. Production Driver installation is outside this Skill.

When reporting, distinguish Activity from Verification Evidence. Include the
Candidate commit and retained Evidence references when present; do not describe
a Candidate as merged, released or deployed.
