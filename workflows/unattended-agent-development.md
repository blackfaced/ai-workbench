# Unattended Agent Development

- Type: workflow
- Domain: coding
- Source: personal workflow
- Status: designing
- Use when: turning an approved requirement into a test-first, independently verified Candidate that can continue after the initiating Agent conversation closes.

## Interaction

1. `aiwb init` discovers repository capabilities and proposes, but never executes, project commands and Skills.
2. `aiwb doctor` validates trust, Git, agent provider, commands, paths, non-production Harness access, and cleanup behavior. The Runner enforces the same approved project policy at execution time.
3. A conversational Skill grills the requirement.
4. a clean Planner produces the Contract: acceptance boundary, fixed Agent provider/model, vertical Todo graph, test contract, Harness selection, permissions, deadline, and optional budgets.
5. A human approves the complete Contract once.
6. A Codex Skill or CLI submits the approved Contract to the Daemon and returns the durable Run ID immediately.
7. The Daemon executes until the Candidate is `merge_ready`, the deadline is reached, or work is explicitly `blocked`.

## Todo Loop

For each dependency-ready Todo:

1. Create an isolated worktree and a fresh Test Designer session.
2. Materialize one approved test slice and prove that it fails for the expected reason.
3. Commit the RED test as a protected checkpoint.
4. Start a clean Implementer session and work in RED-GREEN-REFACTOR cycles without weakening the protected test.
5. Commit code only after the machine gate is GREEN.
6. Start a fresh Verifier session and execute the approved unit, integration, local E2E, browser, image, or non-production Kubernetes gates.
7. Reject any source mutation made by the Verifier.
8. Integrate verified commits into the Candidate branch in Todo dependency order and rerun affected gates.

After all affected gates pass on the integrated Candidate, an optional image profile starts exactly once and returns an external operation ID. The Runner persists that ID before polling. `queued` and `running` remain resumable `waiting_image` checkpoints; `failed`, a command error, or an invalid result blocks promotion. Only a successful result containing an immutable SHA-256 digest advances the Run to `merge_ready`.

Dependency-ready Todos in the same layer may run concurrently. Worktrees are
created from the same Candidate commit before that layer starts, while Candidate
integration is serialized in stable Todo-ID order. A downstream Todo is eligible
only after every declared dependency is integrated, so its worktree contains the
actual upstream result rather than relying on status alone.

A core acceptance failure returns to the same Todo. Independent defects or newly discovered scope become separate work. The same failure signature permits at most two automated rework Attempts, and a Todo permits at most three implementation Attempts.

## Unattended Behavior

- A blocked Todo freezes only itself and its downstream dependants; independent Todos continue.
- Provider quota exhaustion pauses the Run without consuming a code Attempt and never switches away from the Contract's `codex` or `claude-code` selection.
- Reaching a deadline or resource limit produces a resumable checkpoint rather than a false test failure.
- Agent sessions cannot expand permissions or modify the Contract.
- An approved configuration may push only namespaced Candidate branches; it never merges the target branch.
- Production profiles, credentials, deployments, and data are unsupported.
- Image polling never changes provider or falls back to a different image profile.
- Kubernetes contexts cannot be selected or expanded by the Contract; they must already be allowlisted in the approved project workflow.

## Harness Layers

- Unit and integration commands are project-owned and machine evaluated.
- Local E2E uses ephemeral dependencies, deterministic fixtures, a unique `run_id`, and cleanup.
- Playwright Test is the formal browser gate. Playwright MCP and Chrome DevTools MCP are design and diagnosis aids, not pass evidence.
- An approved browser diagnostic Adapter may inspect an unexpected failed gate while its local or non-production Kubernetes target is still live. It records navigation, snapshot, console, network, screenshot, and MCP stderr artifacts, but cannot change the gate return code. Expected RED failures and passing gates do not trigger diagnostics.
- Image builds use an asynchronous start/status/result contract and must resolve to an immutable digest.
- Kubernetes runs use allowlisted non-production contexts, isolated releases or namespaces, TTL labels, Evidence collection, and a recovery Janitor.

For a local-process profile, the Harness allocates a loopback port, starts the
approved command, waits on the approved HTTP readiness URL, and exposes
`AIWB_BASE_URL`, `AIWB_PORT`, `AIWB_RUN_ID`, and `AIWB_ARTIFACT_DIR` to both the
service and gate. It terminates the full process group in a `finally` path and
retains service stdout/stderr even when readiness or the gate fails.

Browser diagnostic MCP server commands are explicit approved capabilities. A
Harness profile selects either `playwright-mcp` or `chrome-devtools-mcp` and a
1-300 second timeout. The Adapter starts a fresh stdio MCP process, discovers
the required diagnostic tools, navigates only to the Harness-provided base URL,
and closes the process before Harness cleanup. Browser content is untrusted
Evidence, not an instruction source.

Image commands run from the integrated Candidate worktree. `start` returns an
operation ID; `status` uses that persisted ID and returns `queued`, `running`,
`succeeded`, or `failed`; `result` returns the immutable digest and optional
artifact paths. The commands receive only runtime coordinates through
`AIWB_RUN_ID`, `AIWB_IMAGE_PROFILE`, `AIWB_IMAGE_STATE_DIR`, and
`AIWB_IMAGE_OPERATION_ID`. Builder credentials remain outside the Contract and
workflow file. A daemon restart resumes `status` for the existing operation and
must not issue a second `start`.

For a Kubernetes profile, the Harness derives a deterministic namespace from
the Run, Todo, and gate stage, then writes a cleanup lease before invoking the
project's `provision` command. The gate runs only after provision returns an
HTTP(S) base URL. Evidence collection runs before the idempotent cleanup command.
Cleanup failure leaves a `cleanup_pending` lease; abrupt process death leaves an
active lease that becomes reclaimable at its TTL. The daemon sweeps both at
startup and periodically, and `aiwb janitor sweep` exposes the same operation
without requiring a running daemon. Kubernetes credentials are inherited by the
project commands at execution time and are never serialized into the lease.

## Evidence and Result

Every decisive result records the Contract hash, commit SHA, image digest when applicable, Harness profile, environment identity, command, timestamps, and retained artifacts. Image Evidence is valid only when the digest matches `sha256:<64 lowercase hex>`; tags and mutable references cannot satisfy acceptance. A passing retry does not erase the first failure; flaky tests are quarantined with an owner and deadline and cannot claim full integration verification.

## Agent Interaction

Use `$run-approved-goal` only after the Contract is complete and approved. The
Skill checks daemon reachability, calls `aiwb_goal_submit` once, and returns the
Run ID. Later conversations use `aiwb_goal_status` for a lightweight view and
`aiwb_goal_report` for Todo progress and Evidence. The MCP process may stop at
any time without stopping the Run because the daemon owns all durable state.

Do not expose direct shell execution, approval mutation, provider switching,
test editing, production actions, or target-branch merge as MCP tools. These are
not interaction conveniences; they would bypass the approved Contract.
