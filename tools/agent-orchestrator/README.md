# Agent Orchestrator

- Type: CLI, daemon, and MCP server
- Domain: coding
- Source: local
- Status: prototype
- Use when: executing an approved development Contract through clean test-design, implementation, and verification roles without keeping an Agent conversation open.

## Product Boundary

Agent Orchestrator owns durable coordination. It does not interpret production credentials, merge a target branch, silently weaken tests, or replace project-owned build and test logic.

The public tool contains no organization-specific integrations. Projects expose their capabilities through a reviewed `.ai-workbench/workflow.yaml`; secrets remain outside repositories and are injected only into approved Harness commands.

## Module Shape

`GoalRunner.run(contract)` is the execution interface and test surface. It hides Contract validation, checkpoint persistence, Git worktree management, RED/GREEN machine gates, role prompts, Evidence capture, and recovery.

`DaemonClient.submit/status/report` is the control interface. It hides the Unix socket protocol, background queue, SQLite job state, thread pool, stale socket handling, and process-restart recovery.

`McpServer` is a thin stdio Adapter over that same control interface. It exposes daemon health plus Goal submit, status, and report tools; it does not own Runs or offer arbitrary command execution.

The external Agent CLI varies behind one seam:

```python
class AgentAdapter(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...
```

`CodexCliAdapter` and `ClaudeCodeCliAdapter` are production adapters. `AgentRouter` selects exactly the provider fixed in the immutable Contract and never falls back to the other provider. Tests replace only this true external CLI seam; Git, SQLite, command execution, and recovery remain real.

## Target Architecture

```text
Codex Skill ─┐
MCP Server ──┼── Unix socket ── Daemon ── GoalRunner
aiwb CLI ────┘                    ├── RunStore (SQLite)
                                 ├── Git worktrees
                                 ├── AgentRouter
                                 │   ├── CodexCliAdapter
                                 │   └── ClaudeCodeCliAdapter
                                 ├── CandidatePublisher
                                 ├── MergeConflictRepairer
                                 ├── Project commands
                                 ├── Harness / ImageBuilder adapters
                                 └── KubernetesJanitor
```

The Daemon can run in the foreground or as a macOS user LaunchAgent. Linux `systemd --user` support is a later host-supervisor adapter.

## Contract Lifecycle

```text
draft → awaiting_approval → approved
approved → running ─────────────────────────────→ merge_ready
                   └→ candidate_verified → waiting_image → merge_ready
                   ├→ blocked
                   ├→ provider_blocked
                   └→ budget_exhausted
```

Within each Todo, durable checkpoints advance through:

```text
pending → red_verified → code_ready → verified → integrated
```

The Run becomes `merge_ready` only after every Todo is integrated into the
Candidate and its affected gate passes there.

Active Agent work is never itself a checkpoint. After interruption, the runner discards partial changes and resumes from the last durable Git commit.

## Implemented Tracer Bullets

The execution tracer supports approved Todo DAGs and local test commands:

- load and validate an approved YAML Contract;
- create one isolated Candidate worktree plus one branch and worktree per Todo;
- schedule dependency-ready Todos concurrently with a bounded worker pool;
- invoke fresh Test Designer, Implementer, and Verifier roles through `AgentAdapter`;
- require a failing test before implementation and a passing test afterward;
- protect the RED test from implementation changes;
- reject Verifier source mutations;
- integrate verified Todo branches into the Candidate in deterministic Todo-ID order;
- rerun each Todo gate after Candidate integration;
- keep blocked downstream Todos frozen while independent work reaches a durable checkpoint;
- persist Run and Todo checkpoints in SQLite and resume after interruption;
- emit a JSON report containing Candidate and Todo branches, commits, worktrees, role sessions, commands, and statuses.

The durable control tracer adds:

- a `0600` Unix domain socket and structured JSON request protocol;
- non-blocking Goal submission plus status and report queries;
- a persistent SQLite job queue;
- automatic recovery of queued or running work after Daemon process death;
- foreground serving and a generated macOS LaunchAgent with `RunAtLoad` and `KeepAlive`;
- repository capability discovery that produces inert suggestions without executing scripts;
- preflight checks for approval, explicit trust, Git, the selected Agent provider, approved commands, and non-production Harness profiles.
- an execution hard gate that requires the Contract command to exactly match an approved project capability.

The local E2E Harness tracer adds:

- approved `local_process` profiles with an approved service start command;
- per-gate loopback port allocation and HTTP readiness checks;
- `AIWB_BASE_URL`, `AIWB_PORT`, `AIWB_RUN_ID`, and `AIWB_ARTIFACT_DIR` injection;
- service stdout and stderr retention under the Run Evidence directory;
- process-group termination after pass, failure, timeout, or interruption;
- Harness profile, environment identity, base URL, and artifact paths in Evidence;
- optional `browser_gate: playwright`, which requires a Playwright Test command as formal pass Evidence.

The asynchronous image tracer adds:

- project-owned `start`, `status`, and `result` commands behind an approved local or non-production image profile;
- durable persistence of the external build `operation_id` before polling begins;
- process-restart recovery that resumes the same external build instead of starting a duplicate;
- live daemon reports while a Run is `waiting_image`;
- command stdout and stderr retention alongside project-returned artifacts;
- an immutable `sha256:<64 lowercase hex>` digest hard gate before `merge_ready`.

The Kubernetes Harness tracer adds:

- project-approved `kubernetes` profiles bound to an explicit allowlist of non-production contexts;
- a deterministic, DNS-safe namespace per Run, Todo, and gate stage;
- project-owned `provision`, `collect`, and idempotent `cleanup` commands;
- mandatory TTL values from 60 seconds through 24 hours plus managed-by, Run ID, and expiry labels;
- context, namespace, base URL, command output, and collected artifacts in Evidence;
- durable cleanup leases written before provisioning starts;
- immediate retry of `cleanup_pending` leases and TTL reclamation after process death;
- daemon startup and periodic Janitor sweeps plus a standalone CLI sweep.

The Agent interaction tracer adds:

- a dependency-free stdio MCP server with `initialize`, `ping`, `tools/list`, and `tools/call` support;
- four narrow tools: `aiwb_daemon_status`, `aiwb_goal_submit`, `aiwb_goal_status`, and `aiwb_goal_report`;
- immediate Goal submission so an Agent conversation never owns the Run lifetime;
- structured operational errors inside MCP tool results and standard JSON-RPC protocol errors;
- a bundled `run-approved-goal` Codex Skill that requires an already-approved Contract and interprets durable Evidence conservatively;
- no MCP tool for direct execution, permission expansion, target-branch merge, production access, or test weakening.

The Claude Code provider tracer adds:

- an immutable `agent.provider` and optional `agent.model` in every Contract, defaulting to `codex` for older Contracts;
- provider routing across every Test Designer, Implementer, and Verifier Attempt without automatic fallback;
- Claude Code print mode with single-result JSON, a fresh process in the Todo worktree, and retained session IDs;
- user-setting and ambient MCP exclusion while preserving trusted project/local settings and subscription authentication;
- `plan` mode for read-only requests and configurable `auto`, `acceptEdits`, or `dontAsk` for writable requests;
- an explicit rejection of `bypassPermissions`, which is unsafe for this host-native, non-containerized tool.

The browser diagnostic tracer adds:

- an optional, project-approved `browser_diagnostic` block on Playwright Harness profiles;
- interchangeable `playwright-mcp` and `chrome-devtools-mcp` stdio Adapters;
- bounded navigation, accessibility snapshot, console, network, and screenshot collection after an unexpected GREEN, verification, or integration failure;
- collection while the local or non-production Kubernetes target is still live, before normal Harness cleanup;
- retained raw MCP results, screenshot, MCP stderr, and the original gate failure under the Run Evidence directory;
- failure isolation: a diagnostic error is reported but never replaces the authoritative Playwright Test return code.

The Candidate publication tracer adds:

- an optional `publishing.candidate` policy that must be explicitly approved;
- a fixed Git remote and namespaced branch prefix owned by project policy, never by the Contract or Agent;
- publication only after the Candidate reaches `merge_ready`, including after immutable image digest Evidence when configured;
- an exact commit-to-ref push followed by remote ref verification and durable remote/ref/commit reporting;
- restart-safe idempotence when Git push succeeds before the SQLite checkpoint is written;
- normal fast-forward protection with no force-push path, so a diverged remote ref blocks publication without being overwritten.

The Candidate merge-conflict repair tracer adds:

- a fresh `conflict_repairer` Agent session only when a Todo branch conflicts while entering the Candidate;
- a narrow repair contract that permits changes only to Git's existing unmerged paths and forbids the Agent from staging or committing;
- runner-owned staging and merge commit creation after it confirms every conflict is resolved;
- durable Todo session and repair-commit reporting, followed by the same authoritative Candidate gate;
- restart-safe continuation of the same in-progress merge only when its `MERGE_HEAD` matches the Todo branch;
- rejection of unrelated merges, unresolved paths, unexpected staged changes, or unrelated tracked and untracked file changes.

The lightweight role-guidance tracer adds:

- optional project-owned `SKILL.md` text for `test_designer`, `implementer`, `verifier`, or `conflict_repairer` only;
- explicit paths under the trusted repository, bounded UTF-8 content, and no ambient user Skill discovery or execution;
- advisory injection into only the selected fresh Agent role; Contract and role safety constraints always take precedence;
- Skill text in the Contract hash, so changing guidance creates a new Run rather than silently resuming an old one.

For a concise, project-local implementation hint, review and add it explicitly to the approved workflow:

```yaml
capabilities:
  skills:
    implementer:
      - .agents/skills/focused-implementation/SKILL.md
```

Keep these files focused on project conventions and suggestions. They do not execute scripts, change permissions, add commands, replace tests, or enable a heavy mandatory process.

The lightweight setup-and-ask tracer adds:

- a single `SkillCatalog` interface that lists bundled and project-local Skills while safely ignoring malformed or escaping entries;
- an advisory `aiwb skills ask` command that recommends zero to two Skills and never invokes one;
- an idempotent `aiwb setup` inspection that reuses project-capability discovery without writing;
- an explicit `--apply` boundary for draft workflow creation, role-guidance selection, and optional project-local Skill copies;
- Codex and Claude Code project targets only when selected, with no writes to user-global Agent configuration;
- destination containment checks that reject Skill paths escaping the selected repository.

The orchestrator does not build images itself, call `kubectl` directly, or need to run in a container. Project commands may wrap a local builder, `docker buildx`, remote CI, Helm, or another cluster tool, while ownership and credentials stay with those external systems. Playwright MCP and Chrome DevTools MCP are diagnostic aids, never pass gates.

## Try the Tracer Bullet

Create and activate a Python 3.9+ environment, then install the tool:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Discover an existing project's capabilities first:

```bash
aiwb init --repo /path/to/project
```

Review `.ai-workbench/workflow.yaml`, move accepted suggestions into `capabilities`, set each command to `approved: true`, change the project to `trusted: true`, and set the configuration status to `approved`. Then run the non-executing preflight:

```bash
aiwb doctor --config /path/to/project/.ai-workbench/workflow.yaml
```

`doctor` is not advisory: both direct and Daemon execution load the same project policy before creating a worktree or starting an Agent. The Contract test command must exactly match one approved command, and any production Harness profile is rejected.

Candidate publication is off by default. To let an overnight Run publish its merge-ready Candidate, review and add this project-owned policy:

```yaml
publishing:
  candidate:
    approved: true
    remote: origin
    branch_prefix: aiwb/
```

The prefix must be a Git-safe namespace ending in `/`. It becomes the local and remote Candidate branch namespace. The orchestrator never pushes `project.base_ref`, never creates a pull request, and never force-pushes. If the process dies after the remote accepts the commit but before SQLite records it, rerunning the same Contract safely confirms the same ref and completes the checkpoint.

Copy [`examples/single-todo.contract.yaml`](examples/single-todo.contract.yaml) or [`examples/multi-todo.contract.yaml`](examples/multi-todo.contract.yaml), point `project.repo` at the trusted Git repository, and replace the example Goal and test command with an approved Contract. Every multi-Todo entry maps `test_ids` to the Goal acceptance boundary, declares `depends_on`, and owns its test command and protected test paths. The target repository must have Git author configuration because the runner records RED and GREEN checkpoints as commits.

The Contract fixes the provider for its entire lifetime. Use `agent.provider: codex` or select Claude Code explicitly:

```yaml
agent:
  provider: claude-code
  model: sonnet # optional
```

For browser E2E, review [`examples/local-playwright.workflow.yaml`](examples/local-playwright.workflow.yaml) and [`examples/local-playwright.contract.yaml`](examples/local-playwright.contract.yaml). The service must bind to `AIWB_PORT`; the test command receives `AIWB_BASE_URL`. The service, Playwright Test, and optional diagnostic MCP server commands must exactly match approved capabilities.

An optional diagnostic block runs only after an unexpected failing browser gate, never during the expected RED gate and never after a pass:

```yaml
browser_gate: playwright
browser_diagnostic:
  adapter: playwright-mcp # or chrome-devtools-mcp
  command: [npx, -y, "@playwright/mcp@latest", --headless]
  timeout_seconds: 120
```

The Adapter speaks MCP directly and discovers the required tools before navigating to `AIWB_BASE_URL`. Both supported Adapters capture five observations: navigation, accessibility snapshot, console messages, network requests, and a full-page screenshot. Browser content is untrusted diagnostic input; it is retained as Evidence and is not treated as an instruction. Local profiles remain loopback-only, Kubernetes profiles remain allowlisted and non-production, and diagnostic timeouts are capped at five minutes.

Use the official [Playwright MCP](https://github.com/microsoft/playwright-mcp) or [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) server command. Pin package versions in long-lived project policies when reproducibility matters; changing the approved command is a policy review, not a Run-time Agent decision.

For an asynchronous Candidate image, review [`examples/async-image.workflow.yaml`](examples/async-image.workflow.yaml) and [`examples/async-image.contract.yaml`](examples/async-image.contract.yaml). Each command prints one JSON object on its final non-empty stdout line:

```text
start  → {"operation_id":"build-123"}
status → {"status":"queued|running|succeeded|failed","detail":"optional"}
result → {"digest":"sha256:<64 lowercase hex>","artifacts":["optional/path"]}
```

The commands receive `AIWB_RUN_ID`, `AIWB_IMAGE_PROFILE`, `AIWB_IMAGE_STATE_DIR`, and `AIWB_IMAGE_OPERATION_ID`; the last value is empty for `start`. A mutable tag such as `latest` is rejected. The external builder may outlive the daemon, but its status and result commands must remain queryable by the persisted operation ID.

For non-production Kubernetes E2E, review [`examples/kubernetes-e2e.workflow.yaml`](examples/kubernetes-e2e.workflow.yaml) and [`examples/kubernetes-e2e.contract.yaml`](examples/kubernetes-e2e.contract.yaml). `provision` prints a JSON object containing `base_url`; `collect` prints an optional `artifacts` string list; `cleanup` prints any JSON mapping and must be idempotent. All three commands must exactly match approved capabilities.

The commands receive `AIWB_K8S_CONTEXT`, `AIWB_K8S_NAMESPACE`, `AIWB_K8S_TTL_SECONDS`, `AIWB_K8S_EXPIRES_AT`, `AIWB_K8S_LABELS`, `AIWB_RUN_ID`, and `AIWB_ARTIFACT_DIR`. The gate also receives `AIWB_BASE_URL`. Configuration cannot name a Kubernetes context unless it appears in `allowed_kubernetes_contexts`, and every Kubernetes profile must declare `environment: non-production`.

For foreground development:

```bash
aiwb daemon serve \
  --max-workers 1 \
  --todo-workers 2 \
  --image-poll-seconds 5 \
  --claude-permission-mode auto
```

The daemon configures both CLI adapters; each Contract selects one. Claude Code `auto` is the unattended default but requires an eligible Claude account. Use `acceptEdits` or `dontAsk` only when the trusted project's permission rules are sufficient. The runner never changes mode or falls back to Codex after a provider error.

In another terminal:

```bash
aiwb daemon status
aiwb goal submit --contract /path/to/contract.yaml
aiwb goal status <run-id>
aiwb goal report <run-id>
```

The daemon sweeps Kubernetes cleanup leases at startup and every minute. A manual or independently scheduled sweep is also available:

```bash
aiwb janitor sweep --state-dir ~/.ai-workbench
```

To expose the daemon control plane to Codex, install the package and explicitly register its local stdio server:

```bash
codex mcp add ai-workbench -- aiwb-mcp --state-dir ~/.ai-workbench
codex mcp list
```

Registration is intentionally a user action; the repository never edits global Codex configuration. The MCP server needs no network access or OpenAI API key. It connects only to the local `0600` daemon socket. Start or install the daemon separately before using the tools.

The bundled interaction Skills live in [`skills/`](skills/): `run-approved-goal`, `setup-ai-workbench`, and `ask-ai-workbench`. To make one globally discoverable, the user may copy or link its directory into `$CODEX_HOME/skills/<name>` (or `~/.codex/skills/<name>` when `CODEX_HOME` is unset). The repository never performs that global change itself. `run-approved-goal` submits an approved Contract and observes its durable Run; `$setup-ai-workbench` inspects first and requires explicit confirmation before project-local setup; `$ask-ai-workbench` is advisory and can return no recommendation.

For direct CLI use, inspect first and add `--apply` only after reviewing the exact planned changes:

```bash
aiwb setup --repo /path/to/project
aiwb setup --repo /path/to/project --agent-target codex \
  --install-skill ask-ai-workbench --apply
aiwb skills ask --repo /path/to/project --task "describe the task"
```

The optional install writes only to `/path/to/project/.codex/skills/` or `/path/to/project/.claude/skills/`; it never changes user-global configuration. `ask` is side-effect free and returns at most two optional recommendations.

For macOS background operation, inspect the plist without loading it:

```bash
aiwb daemon install --no-load
```

Omit `--no-load` to write the user LaunchAgent and bootstrap it with `launchctl`. Runtime logs are written under `~/.ai-workbench/logs/`.

The direct command remains available as an operational fallback:

```bash
aiwb goal run \
  --contract /path/to/contract.yaml \
  --state-dir ~/.ai-workbench \
  --todo-workers 2 \
  --image-poll-seconds 5
```

Rerunning the same command after interruption reuses the immutable Contract hash and resumes from the last durable checkpoint. Runtime state and managed worktrees stay under the selected state directory, not in this repository.

## Planned Delivery Slices

1. Single-Todo recoverable Codex runner. ✅
2. Daemon, Unix socket, launchd, `init`, and `doctor`. ✅
3. Multiple Todo DAGs and Candidate integration. ✅
4. Local E2E and Playwright Harness. ✅
5. Asynchronous image builds and immutable digest Evidence. ✅
6. Non-production Kubernetes Harness and Janitor. ✅
7. MCP and Codex Skill interaction. ✅
8. Claude Code CLI adapter and Contract-fixed provider routing. ✅
9. Playwright MCP and Chrome DevTools MCP browser diagnostics. ✅
10. Policy-approved namespaced Candidate publication. ✅
11. Bounded, restart-safe Candidate merge-conflict repair. ✅
12. Optional, project-owned role guidance from bounded local Skills. ✅
13. Lightweight, confirmation-gated setup and advisory Skill routing. ✅
