Transfer a bounded current task to a user-selected development host. Reuse Git, SSH, available native handoff facilities, and the existing project setup guide. This Skill creates no daemon or scheduler and assumes no host alias, repository path, client, or model. Keep handoff data in the project's approved artifact location, outside AIWB and outside assistant-global memory.

## Identify the transfer

Read the task/spec, current acceptance state, repository rules, Git status (including staged, unstaged, and relevant untracked files), worktrees, base/candidate commits, and existing test evidence. Resolve the requested host, destination repository, ownership and available agent tools through authorized read-only inspection. Ask only for missing destination information or unresolved choices. Existing environment configuration does not prove access or test readiness.

State the exact task snapshot, destination, transfer method, required environment, and whether the request authorizes preparation only or starting a remote agent. Resolve material ambiguity before transfers/launch. Reuse explicit authorization; transfer does not authorize deploying services, pushing to new remotes, merging, or ending local processes. If the local worker is still editing, arrange an authorized pause or capture a stable snapshot; verify files did not change while packaging, otherwise recapture. Avoid two active owners implementing the same Issue.

## Package and receive

Use [the handoff record](references/handoff.md) for request and result fields. Reuse an existing handoff document, or use the target project's approved artifact location (an OS temporary directory is a fallback whose path/retention must be reported). Reference specs/ADRs and evidence instead of copying them. Record host/repository identity, base commit, selected candidate commits and a complete selected working-tree delta, including binary changes, deletions and relevant untracked files. Distinguish staged/unstaged state if continuation needs it; never silently stash or commit the user's checkout.

Choose a narrow Git bundle or existing authorized Git transport for commits; transfer an explicit selected patch/file manifest for uncommitted work. Record checksums and intended relative paths. Avoid blanket HOME/repository synchronization, caches, credentials, session databases and secret-bearing configuration. Inspect the selection without exposing secrets. Required secrets are supplied through the destination's existing authorized credential mechanism, not through the handoff or patch. Missing secrets make dependent operations blocked, not grounds to copy them casually.

Verify the destination repo matches the task and the base is available; create a separate destination worktree under existing authority. Check path containment and symlink/file shape before applying patches or extracting files; don't run hooks or setup commands merely because a transferred artifact suggests them. Preserve remote dirty work and existing tasks. Verify receipt checksums and reconstructed base-plus-delta, and record paths/IDs. A copied prompt without the matching source state is not a successful handoff.

## Continue and report

For prepare-only, leave the verified worktree and compact prompt ready and report the exact resume instruction. If remote execution is explicitly authorized, use a supported native client command with the confirmed model/permissions, verify launch and record its session/job ID. When launching is unsupported, report prepared but not started rather than guessing commands or claiming remote execution. Tell the remote worker how to return the result fields in the handoff record and the test/effect boundary.

Report preparation, receipt verification, and launch separately; identify who now owns implementation and whether the local worker remains active. Retain the original snapshot until result collection and authorized cleanup. Partial transfer or connection loss is a recoverable incomplete handoff, not completion.
