# 0002 - Add a Generic Unattended Agent Orchestrator

## Status

Accepted

## Context

The workbench currently catalogs skills, tools, and workflows but cannot execute a development Goal after its initiating Agent conversation closes. The desired workflow needs clean role-specific Agent sessions, test-first implementation, independent verification, durable recovery, and local or non-production Harnesses.

Reusing a private orchestration project directly would couple this public personal workbench to private platforms, names, and assumptions. Keeping orchestration entirely inside a Skill would also tie execution lifetime to an Agent session and provide no durable state owner.

## Decision

Add a self-contained Python tool under `tools/agent-orchestrator/`, exposed as the `aiwb` CLI.

The tool will use:

- a host Daemon as the durable owner of Goals, Runs, worktrees, Agent processes, Harness executions, and recovery;
- SQLite plus filesystem artifacts under `~/.ai-workbench/` for local state and Evidence;
- a small `AgentAdapter` interface, with Codex CLI and Claude Code behind a no-fallback `AgentRouter`;
- a local Unix domain socket as the default control seam;
- CLI, MCP, and a Codex Skill as separate interaction layers over the same control plane;
- project-owned `.ai-workbench/workflow.yaml` files for approved commands, paths, Harness profiles, and capabilities;
- optional, project-owned role guidance loaded from explicitly approved local `SKILL.md` files, with bounded content and no ambient Skill discovery at execution time;
- a shared advisory `SkillCatalog`, plus confirmation-gated project setup that can copy only selected bundled Skills into selected repository-local Codex or Claude Code directories;
- isolated Git worktrees and fresh sessions for independent roles;
- bounded, dependency-layer scheduling for Todo DAGs, with one branch and worktree per Todo;
- deterministic integration of verified Todo branches into a separate Candidate worktree;
- bounded repair of Candidate merge conflicts by a fresh Agent limited to Git's existing unmerged paths, with runner-owned merge commits and durable repair evidence;
- optional project-approved publication of a merge-ready Candidate commit to a fixed Git remote and namespaced branch;
- project-owned local-process Harness profiles that provision loopback services, wait for readiness, inject runtime coordinates, retain logs, and always clean up;
- Playwright Test as the only formal browser pass gate, while browser MCP tools remain diagnostic aids;
- project-approved Playwright MCP or Chrome DevTools MCP diagnostics that run against a still-live failed browser target and retain raw artifacts without changing the gate result;
- project-owned asynchronous image profiles whose approved `start`, `status`, and `result` commands wrap local or remote builders;
- durable external image operation IDs, restart-safe polling, and immutable SHA-256 digests as the only acceptable image Evidence;
- project-owned Kubernetes Harness commands bound to allowlisted non-production contexts, deterministic isolated namespaces, and bounded TTLs;
- durable cleanup leases plus a daemon-owned recovery Janitor that retries failed cleanup and reclaims resources after process death;
- a dependency-free stdio MCP Adapter exposing only daemon health and durable Goal submit/status/report operations;
- a concise Codex Skill that checks the approval boundary, invokes the MCP tools, and explains Evidence without owning execution;
- one approved Contract before unattended execution, with a fixed Agent provider and no mid-run permission expansion.

The orchestrator is provider-neutral at its core but Codex-first in delivery. A Contract names `codex` or `claude-code` plus an optional model; every Attempt in that Run uses the same selection, and provider errors never trigger fallback. Claude Code runs in non-interactive JSON mode, excludes user settings and ambient MCP configuration, maps read-only work to `plan`, and permits only `auto`, `acceptEdits`, or `dontAsk` for writable work. Host-native `bypassPermissions` is unsupported. The tool targets explicitly trusted local repositories and may use approved non-production environments, but production access is outside its scope. Public code and examples must not contain private company systems, addresses, credentials, or adapters.

## Consequences

The repository evolves from a knowledge-only workbench into a knowledge workbench that also contains executable tools. Runtime code remains inside the existing `tools/` artifact type rather than introducing a new top-level directory.

The first tracer bullet proves a single approved Todo through RED test creation, implementation, fresh verification, durable checkpoints, and a merge-ready Candidate. The second adds durable daemon supervision and project policy. The third adds multi-Todo dependency scheduling, bounded parallelism, Todo-level recovery, and Candidate integration. The fourth adds disposable local-process Harnesses and Playwright Test gates. The fifth delegates image work to external asynchronous builders, persists the returned operation ID, resumes polling after daemon restart, and prevents `merge_ready` until the integrated Candidate has an immutable digest. The sixth adds isolated non-production Kubernetes Harnesses and a recovery Janitor. The seventh adds MCP and Codex Skill interaction over the existing daemon. The eighth adds Claude Code and Contract-fixed provider routing. The ninth adds approved Playwright MCP and Chrome DevTools MCP diagnostics for unexpected browser gate failures while preserving Playwright Test as the sole pass authority. The tenth adds optional namespaced Candidate publication after `merge_ready`, with exact-commit verification, durable publication Evidence, restart idempotence, and no force-push or target-branch path. The eleventh adds a fresh conflict-repair session only for Candidate Todo-merge conflicts, constrains it to the existing unmerged paths, has the runner create the merge commit, persists the repair session and commit, reruns the Candidate gate, and resumes only a matching interrupted merge. The twelfth adds optional role-specific local Skill text as bounded advisory guidance; changing that text produces a new Contract hash and Run. The thirteenth adds repository onboarding and advisory Skill routing: setup reuses discovery but writes only after explicit confirmation, routes never execute a Skill, and any selected bundled Skill is copied only into a selected repository-local Agent directory.

Candidate publication is project policy, not a Contract capability. The reviewed workflow fixes the remote and namespace; the orchestrator derives the Candidate branch inside that namespace and pushes only its exact merge-ready commit. A failed or diverged push leaves the verified Candidate intact for inspection and retry, while a crash between remote acceptance and the local SQLite checkpoint is safe because publishing the same commit to the same ref is idempotent.

Candidate conflict repair is deliberately narrower than ordinary implementation. It never touches the target branch, never invokes `git merge --abort`, and refuses any conflict state not created by the next deterministic Todo integration. The repair Agent cannot expand scope beyond the conflicted paths or create a commit; the runner checks tracked, staged, and untracked changes before it stages the resolved paths and lets Git complete the existing merge. This makes an interrupted repair inspectable and restartable without silently discarding work.

Role guidance is intentionally not a workflow engine. A project may opt in per standard role with one or more reviewed `SKILL.md` files under its own trusted root. Their bounded text is advisory only: it neither executes a script nor changes the approved command, environment, permission, production, or test-gate boundaries. The Runner incorporates the resolved text into the Contract hash, preventing a changed Skill from being used to resume a Run that started with different guidance.

Setup and ask are likewise interaction helpers, not a second workflow engine. Setup is inspect-first and requires a separate explicit apply action before creating a draft workflow, changing role guidance, or copying a bundled Skill. The catalog may describe malformed local files as unavailable but never runs their contents. Router results are bounded to two optional recommendations and have no daemon, Goal, permission, or filesystem side effect. Selected Codex or Claude Code setup writes stay under the repository; it never edits user-global configuration, selects a provider for a Run, or introduces a provider-specific external host adapter.

The daemon intentionally does not own a container runtime or a provider-specific build API. This keeps the core adapter shallow: projects retain their existing image scripts, CI systems, credentials, logs, and retention rules. The tradeoff is that every image profile must provide stable status and result lookup for an operation that can outlive the orchestrator process.

The same rule applies to Kubernetes: the orchestrator never shells out to a hard-coded cluster tool. A reviewed project profile supplies provision, collection, and cleanup commands. The Harness injects only runtime coordinates, persists no credentials, and requires cleanup to be idempotent because normal finally cleanup, daemon recovery, and TTL reclamation may target the same namespace.

MCP and Skill remain interaction Adapters, not alternate orchestrators. MCP never launches a direct synchronous Run, and the Skill never reimplements recovery or polling ownership. Both reuse `DaemonClient`, so CLI, MCP, and future interaction surfaces observe the same SQLite state and enforcement decisions.
