# Native thread harness adapters

Use with the [repository thread procedure](threads.md). `codex`, `trae` and `claude-code` are distinct address spaces. Record discovery, submission, handling and result evidence separately for each directed route. The interfaces below were inspected on 2026-11-07; read current tool schemas/help before use. Interface presence is not a live delivery result.

## Codex

Prefer the selected surface's existing tools. Codex Desktop exposes:

| Need | Operation | Binding/check |
| --- | --- | --- |
| Discovery | `list_projects`, `list_threads` | Recent results are a sample; paginate history for the relevant host/source. |
| Context/results | `read_thread` | Read turns and referenced evidence; summaries alone are insufficient. |
| Messaging | `send_message_to_thread` | Exact returned `hostId` + `threadId`; human authorization for that target, including replies. |
| Observation | `wait_threads` | Up to eight Codex targets with latest `afterCursor`; `timeoutMs: 0` is a snapshot. Use bounded waits. |
| Creation/naming | `create_thread`, `set_thread_title` | Follow explicit user intent; unresolved routes do not authorize creation or repurposing. |

Codex CLI 0.162.0 additionally exposes `codex agents` and `codex queue --thread <UUID-or-exact-name> --message <text>`. Bind a discovered UUID before queueing. Its generated app-server schema includes `thread/list`, `thread/read`, `thread/turns/list` and `thread/name/set`; `searchTerm` is a substring search, so enforce exact title equality after discovery. The CLI queue interface does not establish visibility in a particular Desktop host or prove final result delivery.

## Trae CLI / TraeX

Use `traecli` / `traex`, verified by `--version`; a `trae` executable may be the IDE launcher. Inspected Trae CLI 0.213.1 exposes:

- `traecli dashboard`: native session/agent view, not a machine-readable list command.
- `traecli queue --thread <UUID-or-exact-name> --message <text>`: submission to an existing session. Use the bound UUID; inspect help for the installed version.
- Generated app-server schema: `thread/list` with cursor/cwd/archive/substring filters; `thread/read` with `threadId` and `includeTurns`; `thread/name/set` with `threadId` and `name`.

Use an existing authorized native tool or app-server connection for list/read/name operations, validating the version's handshake, response shape and pagination. Schema generation is an offline interface check; it is not an established connection. The inspected Trae schema does not expose Codex's `thread/turns/list`; do not borrow that method or Desktop's `wait_threads`. Observe through verified native status/events or bounded readback, retaining the last observation. Queue acknowledgment alone leaves completion unknown.

For either CLI, `app-server generate-json-schema --out <temporary-dir>` can verify available protocol methods without starting a model session. Do not start a new daemon or invent a transport client solely because the schema exists. Existing native services remain client-owned; this workflow adds no scheduler.

## Claude Code

Use native `ListAgents` (also `/list-agents`) to discover peer sessions and `SendMessage` to message the verified address. Human-set `--name` / `/rename` names support discovery; distinguish same-named peers using the identifiers returned by the native listing. A `claude agents` view, resumable session ID or agent-team teammate is not by itself proof of independent-session messaging. [Official tools reference](https://code.claude.com/docs/en/tools-reference).

Claude Code 2.1.319 exposes `claude agents --json` to list active interactive/background sessions without a TTY; `--all` also includes completed background sessions. `claude logs <id-or-name>` reads a background session's recent terminal output. Prefer its bound ID over partial-name matching. These shell entrypoints can support discovery and background-result inspection from another harness; they do not establish a generic shell send command or access to every interactive transcript. An empty successful list proves no listed active sessions, not missing messaging support.

Cross-session messaging on macOS/Linux requires at least 2.1.224; provider/configuration restrictions can require newer versions. Check actual tools and inbound settings as well as version. Reply messages and project artifacts carry results; the feature does not expose another session's whole conversation. Where supported, `SendMessage.notify_when_idle` provides a one-shot completion cue (2.1.236+ at both ends), after which the coordinator still checks the candidate evidence. Held/refused messages remain undelivered. See [availability and delivery](https://code.claude.com/docs/en/cross-session-messaging).

If a required feature is absent, report the precise capability/version gap. Use an existing supported artifact readback route within scope; do not treat `claude --resume` as sending to a live peer or silently upgrade/configure the harness.

## Six read-only routes

The **sender** runs the destination CLI in its own session. The coordinator binds both sessions and reads the answer from the destination. Use a fresh random challenge for each direction and attempt. For example, ask the recipient to reply with a short prefix plus the last four characters of the challenge. Keep the expected answer out of the request.

| Sender → destination | Send from the bound sender | Read back from the bound destination |
| --- | --- | --- |
| Codex → Trae | Run `traecli queue` for the Trae UUID | Trae `thread/read` with `includeTurns: true` |
| Claude Code → Trae | Run `traecli queue` from Claude's Bash tool | Trae `thread/read` with `includeTurns: true` |
| Trae → Codex | Run `codex queue` from Trae, requesting one-time approval if required | Codex Desktop `read_thread` on the bound host and thread |
| Claude Code → Codex | Run `codex queue` from Claude's Bash tool | Codex Desktop `read_thread`. **Human continuation was required** when the receiving turn stopped during configuration loading. |
| Codex → Claude Code | Open `claude attach` on the bound background session in an interactive terminal | Read the incoming challenge and subsequent Claude answer from that session |
| Trae → Claude Code | Open `claude attach` from Trae with a persistent terminal, requesting one-time approval if required | Read the incoming challenge and subsequent Claude answer from that session |

### Queue and one-time approval

Set the destination UUID from discovery and prepare the probe text before invoking the appropriate command. Pass the message as a single argument.

```sh
codex queue --thread "$codex_uuid" --message "$probe"
traecli queue --thread "$trae_uuid" --message "$probe"
```

Retain the returned target and queue receipt. If the sender's sandbox prevents the managed launcher from accessing its registry or connecting to the destination service, inspect the error and check whether submission occurred. When the user has authorized this direction, use the sender's normal approval interface to request **one execution** of the command against the bound target. For an existing Trae test session, an interactive on-request entry is `traex -s read-only -a on-request resume <trae-uuid>`. Preserve read-only repository scope and include the exact destination and operation in the review. If a confirmation is pending, keep the prompt available and tell the user where to approve it. Record the review outcome and the command result separately.

### Attach and submit

1. Resolve the background session through `claude agents --json`. Run `claude attach <background-id>` in a PTY that the sender can both read and write. Use the background ID accepted by the CLI and verify the displayed session against the binding.
2. If attach times out, check whether the same control service is reachable on the host and from the sender's sandbox. A host-side success and sandbox-side refusal point to an access boundary. Retry through the one-time approval interface when authorized. Attribute a daemon exit to a specific cause only when its diagnostics support that conclusion.
3. Inspect the live prompt. Preserve an existing draft. If styling makes a suggested prompt look like typed text, verify the input state against the session's native view. Enter the probe, reread the input line, then submit once. Keep the PTY open through these steps. If the sender has a single tool call for terminal I/O, perform the interaction within that reviewed call.
4. Read the Claude-authored reply paired with the submitted challenge in the target session. The attached terminal or `claude logs <background-id>` can provide the exchange when both messages are visible. Record this route as terminal attachment. Claude peer messaging uses a separate interface.

### Confirm delivery and recover an interrupted turn

Read forward from the destination's pre-send cursor or turn boundary. Mark the direction **PASS** when the bound sender's invocation and the bound destination's incoming challenge and matching assistant reply can all be identified. A queue receipt means queued. An attach screen means connected. Probe text in a prompt draft or an expected answer quoted in instructions leaves the result pending.

For **Claude Code → Codex**, a queued message can reach Desktop while its receiving turn fails during configuration loading. Inspect the target history and queue before retrying. Once the target can run, have the user continue the **same Codex conversation**, then read its next assistant turn. Record a matching answer as **PASS with human continuation** and preserve the interrupted attempt. When the queue is simply waiting for an active turn to finish, wait for the next turn first.

Keep repository mappings, actual session addresses, challenges, receipts, approval decisions and target replies in the owning workspace's run record.
