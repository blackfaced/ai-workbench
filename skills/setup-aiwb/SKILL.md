Prepare or maintain a repository's integration-test guide from its actual scripts and development/deployment paths. Reuse the existing guide; use `docs/testing/integration.md` only when no convention exists. Each repository owns its setup facts. This Skill is not the retired `aiwb setup` CLI and does not accept the business feature.

## Inspect and agree on execution

Read repository rules, test/run documentation, package scripts, CI and relevant deployment definitions. Identify the tested boundary and command sources. Inspect configuration names and credential-provider status without printing secrets; distinguish configured, reachable/authenticated and behaviorally verified. Ask only for missing inputs or consequential choices.

Use [the integration-guide outline](references/integration-guide.md), omitting inapplicable sections. Link maintained scripts rather than copying them. Capture working directories, prerequisites, variable names/retrieval methods, dependencies, candidate identity, start/health/test commands and cleanup. Mark unexecuted or inferred paths UNVERIFIED; a complete draft is not verified setup.

Writing a requested guide is authorized setup work. When invoked by `implement-batch`, use its confirmed plan before creating artifacts or executing checks; do not ask again for unchanged authority. Present targets, side effects, costs and cleanup for additional operations. Read-only inspection does not authorize installs, deployment, billable calls, data writes or shared-environment changes.

## Prove the feedback path

After authorization, exercise the path in the intended worktree/environment:

1. **Start and identify:** use the repository's supported command; identify the served commit or complete dirty patch, process and endpoint.
2. **Reach:** check an actual HTTP/API response and, for frontends, browser navigation. A Ready log or an installed browser is insufficient.
3. **Exercise:** run one representative baseline interaction/API assertion using usable test data. Prefer sanitized known-good fixtures; state which dependencies are simulated. Missing new-feature behavior is implementation work, not a reason to demand that feature already pass setup.
4. **Recover:** record the owned stop/restart or development rollback path and evidence location. Execute recovery only when authorized; otherwise mark it unverified.

Record commands, date, candidate, environment, observations and sanitized evidence. Leave one repeatable smoke command or linked procedure; reuse existing tooling rather than creating a parallel test framework. Report unavailable prerequisites and the next usable check. Setup success proves a feedback path, not final spec acceptance.

For frontends, prefer the repository's local dev command, such as `pnpm dev`; verify port, API routing, account/data source and browser/test runner. For backends, prefer an isolated Kubernetes development Pod with incremental file/artifact copying when supported. Use the repository's build/chart/values procedures and verify context, namespace, Pod/container, image, copy destination, activation, readiness and access. Surface unsupported paths and agree on an alternative. A separate Pod does not isolate shared databases, queues or APIs.

## Maintain the development entry point

Establish one service owner. Keep changing worktree/candidate, process/session, URL/port, access method and review-window details in the linked run record. Other workers keep their own worktrees; the owner updates the served candidate through the agreed integration path, reloads/restarts and verifies identity/readiness before further checks. A stable URL is not a stable version.

An authorized **WIP preview** can precede build/QA success: label known failures and unverified boundaries, provide concrete actions, and record human feedback separately from automated results. Preserve useful failing states during the agreed review window unless unsafe. Preview access neither waives final gates nor requires a human sign-off unless agreed. Public exposure requires explicit authority. Record stop instructions and retained resources; keeping a service available does not imply monitoring.

For incremental Pod updates, record the base image digest plus copied candidate/patch and affected paths. Preserve configuration/credentials; handle deleted files explicitly within owned paths. Verify activation after required compile/reload/restart, then rerun affected checks. After Pod recreation, reapply the recorded patch or rebuild before reusing evidence. Development-Pod results do not accept an untested release image.

Update the existing guide as verified facts change and link it from project documentation when authorized. Keep spec cases/results in the acceptance document and Issue status in the tracker. Clean only run-owned resources within authority; report failures or retained resources. Finish with guide location, verified/unverified paths, missing inputs and the next command. Do not install global clients or revive the orchestrator implicitly.
