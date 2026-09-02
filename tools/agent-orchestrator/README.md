# AI Workbench Agent Orchestrator

An admitted Run owns one AIWB worktree and starts one bounded Agent Harness
Attempt. The Harness owns its internal planning, tools, subagents and rework;
AI Workbench records only immutable Admission data, Attempts, bounded Activity,
lease-fenced transitions and Evidence references.

`AgentHarnessDriver.execute(AttemptSpec, event_sink) -> AttemptOutcome` is the
only agent execution seam. A Driver must validate the frozen
`AgentHarnessProfile` before external execution and fail closed for unsupported
driver, model configuration, permissions, capabilities, extensions, paths,
tools, resource limits or trace coverage. This repository ships a strict fake
Driver for behavioral tests. A production Codex Driver is intentionally not
included; it belongs to issue #56.

An `AttemptOutcome.completed` moves a Run only to verification. Verification
uses the admitted project policy and a frozen command or existing local/Kubernetes
Harness Profile. Its Evidence is retained by the RunLedger; only successful
Verification Evidence can accept a Candidate. Optional approved image building
and Candidate publication run after verification and are recorded as Evidence.
Interrupted Attempts are terminal. Retrying creates a fresh Attempt in the same
AIWB-owned worktree and never resumes a Harness session.

The durable SQLite schema is v5. Existing incompatible state is rejected and
requires the existing explicit reset operation; there is no migration.

Minimal Contract shape:

```yaml
schema_version: 5
goal:
  id: example
  title: Example
  requirement: Implement the accepted behavior.
  acceptance: [{id: AC-1, statement: Verification passes.}]
approval:
  artifact_path: /outside/the/repository/example.execution-approval.json
instructions: Implement the accepted behavior and report the outcome.
agent_harness:
  driver: codex
  model: gpt-5
  effort: high
  permissions: [workspace-write]
  capability_ceiling: [git]
  extensions: []
  allowed_paths: [.]
  tools: [shell]
  input_artifact: contract.yaml
  output_schema: attempt-outcome/v1
  timeout_seconds: 1800
  max_attempts: 1
  resource_limits: {tokens: 100000}
  native_configuration: {mode: autonomous}
  trace_coverage: [activity]
project: {repo: /absolute/path/to/repository, base_ref: main}
verification:
  command: [python3, -m, pytest, -q]
  timeout_seconds: 900
```

Named project-local extensions use `kind:name@version`. Skills resolve from
the selected Agent's Skill directory. MCP, plugin, hook, and command descriptors
resolve from `.ai-workbench/extensions/<kind>/<name>.yaml`; each descriptor
declares matching `kind`, `name`, and `version`, plus a project-relative
`configuration.entrypoint` that is executable at the frozen base commit.
Preflight freezes the descriptor and entrypoint digests.

Run `aiwb goal preflight --contract ...` to review the complete resolved
execution and digest. Then run `aiwb goal approve --contract ... --approved-by
... --approval-artifact ...` to write the configured external Approval artifact.
Admission rejects a missing or stale artifact, including any later change to
instructions, base commit, Profile, extensions, verification, image, or
publication settings.
