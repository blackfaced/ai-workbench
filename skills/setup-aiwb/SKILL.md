Prepare or maintain a repository's integration-test guide using its actual development and deployment entry points. This is a Skill, not the retired `aiwb setup` CLI. Reuse the repository's existing guide, scripts, and CI before introducing a document. Default to `docs/testing/integration.md` only when no convention exists. For multiple repositories, each owns its setup steps; link across guides rather than copying deployment instructions.

## Inspect and write the guide

Read repository rules and the existing test/run/deploy documentation, package scripts, CI, deployment manifests, and relevant callers. Identify the tested system boundary and the source of each command. Inspect existing configuration and credential-provider availability without printing secrets; ask only for missing inputs or unresolved choices. Distinguish configured, reachable/authenticated, and behaviorally verified. Configuration presence is not proof of a working test environment.

Use [the guide outline](references/integration-guide.md) to record only applicable sections. Capture exact working directories, executable entry points or script links, prerequisite versions, variable names and retrieval methods, service dependencies, readiness checks, target identity, test commands, evidence collection, and cleanup. Mark inferred commands or unexecuted steps UNVERIFIED with the unresolved question. A guide can be complete as a draft without claiming its commands work.

For a frontend such as a project using `pnpm dev`, verify the actual script, port, ready signal, API routing, test-account source, and browser/test runner. For a backend deployed through a mono repo, Kubernetes, and Helm, locate the build/chart/values entry points, image identity, context/namespace/release, isolated workload, readiness, access route, and logs. These are inspection criteria, not universal commands or permission to deploy. Do not assume a separate Pod isolates shared databases, buckets, queues, or APIs.

Writing the requested guide is authorized setup work. If invoked as part of `implement-batch`, follow its execution-plan confirmation boundary before writing project artifacts. Present concrete operations, targets, side effects, costs when relevant, and cleanup before executing actions not covered by existing authorization. Reuse the batch confirmation instead of creating another approval ritual. Read-only discovery may precede it; deployments, real API calls, and test-data writes may not.

## Validate and maintain

After authorization, execute only the necessary setup/health checks within the agreed test boundary. Record the actual command, date, source commit, environment, outcome, and evidence reference for each verified path. Pin the deployed candidate to a commit/image digest or report identity as unverified; testing an old service does not verify the new implementation. Use named test resources and clean up only resources created by this run within authorized scope. Report remaining resources and cleanup failures.

Update the existing guide when verified facts change. Prefer links to maintained scripts over copying their contents. Preserve existing notes and evidence; keep credentials and session data out of the guide. Link the guide from the repository's existing documentation index or project guidance when authorized. The guide describes how to test; Issues remain task status authority and spec-specific cases/results live in their own acceptance document.

Report the guide path, verified and unverified routes, missing inputs, and next usable test command. Do not install global clients, restore the retired orchestrator, modify shared environments, or claim full integration acceptance merely because setup is healthy.
