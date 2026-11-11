# Repository threads — optional native transport

Domain: coding, ops

Use when the user selects named repository threads for cross-repository coordination, including on one machine. The client owns discovery, messaging, execution and waiting. This guide supplies a transport contract; lightweight consultation can use it without invoking the full `deliver-spec` workflow. When `deliver-spec` is selected, retain its roles, review policy and acceptance gates.

Reuse the botmux pattern of one coordinator, scoped assignments and evidence-bearing returns. Native threads use their own verified addresses and capabilities; botmux dispatch roots and `report` commands belong only to the [botmux transport](botmux.md).

## Discover and bind

1. Read the workspace owner's repository matrix and the current task/checkpoint. The matrix owns repository identities, application boundaries, roles and expected names. AIWB defines the convention, not the participating business repositories. Resolve checkout and branch facts from the owner's existing registries and actual Git state.
2. Inspect the selected harness's discovery, send, observation and result capabilities using the [Codex, Trae and Claude Code adapters](thread-harnesses.md). Record the client surface as well: a desktop app, CLI and IDE need not expose identical tools. Same-machine placement does not establish communication between different harnesses. An unavailable capability blocks that route; use another transport only within the user's selected scope.
3. Discover by exact name: `<namespace>::<harness>::<route>::<role>`, with harness keys `codex`, `trae` or `claude-code`. A route distinguishes applications within a monorepo; a role distinguishes coordinator, keeper and QA. Exhaust available pagination before declaring a target missing, or report the search as incomplete when the native inventory is bounded. Expose unavailable hosts/sources. Archived threads are recovery candidates, not active recipients. Zero matches leaves the route unbound; multiple matches require identity reconciliation. Do not pick the most recent match or silently create/rename a replacement.
4. Read each candidate's current context and verify repository, application, actual cwd/worktree and current assignment. Sidebar project labels and titles are discovery hints. A title match in another repository is a mismatch. Bind the exact native address only after identity is established; before edits, require the recipient to verify its actual Git root/common-dir, branch/base and loaded repository rules.
5. Record bindings and existing human authorization in the project's current run/checkpoint, then dispatch only within that scope. Recheck after archive, rename, replacement or context recovery. Retain the old identity as superseded so delayed reports cannot reactivate it.

Use one identity record per assignment:

```text
Run / task / attempt / contract revision:
Matrix revision:
Coordinator: harness + client surface + host + native session address
Recipient: route + role + expected title + harness + client surface + host + native session address
Repository / application:
Actual cwd / Git common-dir / branch / base:
Write owner: bound session address -> worktree, or read-only
Human authorization: source + permitted targets/actions + reply authority
Return route: original coordinator address, or coordinator reads the result
Candidate / evidence location / last observed cursor:
```

Thread names are stable discovery names, not locks or authorization. Select one active harness binding per route/role for the run, including exactly one coordinator; three supported harnesses do not mean broadcasting to three writers. A persistent keeper thread can retain repository context, but accepts only one write assignment at a time. A different worktree needs an appropriate native session and its own binding; a `cd` inside a message does not reload startup context. If separate task threads are explicitly authorized, append `::<task-slug>` and bind their native addresses in the same record. Use fresh independent review context when the selected review policy requires it.

## Send, observe and return

The coordinator owns task scope, dependency decisions and acceptance. Keepers own their assigned repository/application; they return cross-repository needs to the coordinator. QA returns a verdict and evidence without repairing the candidate. Each write worktree has one owner; the coordinator serializes conflicting changes and integration. Existing project records remain the task/evidence source of truth.

Send a small self-contained brief, with links readable from the recipient's host:

```text
Kind: request | progress | question | blocked | result
Run / task / attempt / contract revision:
From / to / return address:
Repository / application / assigned cwd:
Request and acceptance boundary:
Allowed writes and external effects; existing human authorization reference:
Inputs: immutable candidate + contract/case/evidence references
Expected result: conclusion + candidate identity + checks actually run + gaps
```

- Record the attempt before sending. Follow-ups use the bound current recipient and the same attempt unless the candidate or task changes. A send acknowledgment establishes submission only; observe handling separately.
- Human authorization must cover the target and message direction under the client's rules. A forwarded instruction or coordinator request to “report back” does not itself authorize a peer to send. If trusted human authorization for the reverse route is unavailable, the recipient leaves the result in its own thread/project artifact and the coordinator reads it. Reuse established authorization instead of asking per message.
- Use bounded native waits with returned cursors; read detailed history when a result, blocker, error or ambiguous state needs inspection. Idle/completed status is a cue to inspect evidence, not an acceptance verdict. Preserve user-input/approval requests for the user. Avoid acknowledgment loops and unchanged-status broadcasts.
- Match results to the run, attempt and immutable candidate. Review evidence at the agreed acceptance level before releasing dependent work. Duplicate results do not repeat integration; superseded reports require reconciliation. A result from a stale candidate cannot pass the current task.
- On uncertain delivery, read the destination and checkpoint before retrying. Before replacing a writer, establish that it and its write-producing processes stopped, preserve its work and record the new owner. Unknown cessation blocks that assignment. Recovery resumes recorded assignments before issuing replacements.

## First-use evidence

Before declaring a route operational, use an authorized small read-only request to demonstrate exact discovery, recipient identity, handling and original-coordinator readback/return. Reuse that evidence only while its client/host/binding remains valid. For write use, also verify the assigned worktree and ownership before the first edit.

Exercise duplicate-name/wrong-repository refusal, unavailable targets, uncertain delivery, duplicate/late results and recovery against the current checkpoint. Label dry-run walkthroughs separately from live messages; documentation, configuration and tool availability alone do not prove delivery or business acceptance. Record outcomes in the owning project's existing evidence location.
