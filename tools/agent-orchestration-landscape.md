# Agent Orchestration Landscape

- Type: research note
- Domain: coding
- Status: reviewed recommendation
- Reviewed: 2026-08-25
- Sources: official documentation, official repositories, and published specifications only

## Recommendation

AI Workbench should stop building its own coding-agent loop.

For the current local, Codex-first product, use the stable **Codex Python SDK** as
the first coding-harness driver. Add only two more integration seams: the
**Claude Agent SDK** as the second native driver, and a generic **Agent Client
Protocol (ACP)** driver for the growing set of ACP-compatible coding harnesses.
Keep AI Workbench as a thin, harness-aware control and acceptance layer:

1. freeze the approved goal, exact models, permissions, commands, and base commit;
2. create and own the Git worktree;
3. start one selected-harness session and stream its typed events;
4. enforce an outer wall-clock timeout and cancellation;
5. run project-owned machine Harnesses;
6. persist only Run, Attempt, outcome, and Evidence references needed for audit and
   recovery.

Distribute AIWB's in-harness capabilities once as a portable **Extension Pack**:
one MCP server plus Agent Skills. Harness-native plugins, hooks, and commands may
wrap that pack for installation convenience, but must not become separate control
planes. Do not add a Kimi, Qwen, DeepSeek, OpenCode, Copilot, or OpenHands driver
unless AIWB actually needs to control it unattended and no sufficiently stable ACP
surface exists.

Do **not** put LangGraph, Temporal, or OpenAI Agents SDK between AI Workbench and
Codex by default. Each is capable, but each would add a second orchestration model
on top of a coding harness that already plans, invokes tools, delegates to
subagents, manages context, and streams lifecycle events.

The direct Codex SDK recommendation is supported by current first-party surfaces:

- OpenAI's Codex platform boundary assigns the agent loop, conversation, tools,
  sandbox, approvals, and event stream to Codex, while the host owns the business
  control plane, workspace, approval UI, and system-of-record writeback
  ([Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform));
- OpenAI's Symphony reference design is intentionally a thin orchestration layer:
  an issue tracker is the control plane, each ticket gets a workspace, and the
  outer service owns claiming, concurrency, retry, reconciliation, timeout, and
  observability while Codex App Server owns execution
  ([Symphony announcement](https://openai.com/index/open-source-codex-orchestration-symphony/),
  [Symphony specification](https://github.com/openai/symphony/blob/main/SPEC.md));
- the stable Python SDK controls the local Codex app-server over typed JSON-RPC,
  includes a pinned CLI runtime, and exposes thread creation, continuation, sandbox
  presets, streaming notifications, approvals, interruption, and steering
  ([Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk),
  [Python SDK repository](https://github.com/openai/codex/tree/main/sdk/python),
  [app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md));
- Codex itself owns subagent spawning, routing, waiting, follow-up instructions,
  and thread closure; project-scoped custom agents can freeze model, reasoning,
  sandbox, MCP, and Skill settings
  ([Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents));
- Codex non-interactive execution already emits JSONL events for threads, turns,
  commands, file changes, MCP calls, plans, failures, and token usage, and supports
  a JSON Schema for the final response
  ([Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)).

This means the current blocked-call shape is accidental integration debt, not a
reason to invent more orchestration. The SDK already offers the lifecycle seam
that a wrapper around `subprocess.run()` is trying to reconstruct.

The practical preference order is: native **Codex Python SDK**, then native
**Claude Agent SDK**, then the generic **ACP Driver**. Use direct Codex App Server
only when AIWB needs a feature the high-level SDK does not expose, and structured
CLI only for short one-shot or CI jobs.

## The boundary AI Workbench should own

Provider harnesses can decide *how an agent works*. They cannot decide whether the
result satisfies this repository owner's approved development contract.

Keep these AI Workbench responsibilities:

| Responsibility | Why it remains outside the provider harness |
| --- | --- |
| Setup and exact Admission | A provider session does not freeze the repository's approved base commit, machine commands, environment policy, or owner decision. |
| Approval grant | The owner needs one reviewable daytime setup and one bounded overnight grant, independent of the provider's incidental tool prompts. |
| Worktree and candidate ownership | Provider sandboxes protect filesystem access, but AI Workbench needs a provider-neutral Git artifact that the owner can inspect and keep. |
| Machine Harness and acceptance | Agent completion, self-review, and subagent consensus are not proof that tests, builds, or external non-production checks passed. |
| Minimal durable ledger | Process death still requires a durable record of which approved Run and Attempt were active and which Evidence objects were finalized. |
| Evidence retention and redaction | Raw provider events can be large or sensitive. AI Workbench should store bounded references and apply its own retention policy. |
| Lease, retry, and liveness policy | The outer service must still detect wall-clock or no-event stalls, interrupt the provider turn, reconcile its final state, and decide whether a retry is allowed. |

Stop owning these responsibilities:

- Test Designer -> Implementer -> Verifier or Planner -> Worker -> Reviewer as a
  bespoke durable state machine for every Todo;
- provider-independent representations of every plan, tool call, subagent, retry,
  handoff, or context-compaction event;
- a second agent retry loop around a provider harness's own loop;
- prompt protocols that imitate native structured output, event streaming,
  permission callbacks, thread resume, or subagent configuration;
- persisted “progress percentages” inferred from CPU usage, worktree dirtiness, or
  partial text.

AI Workbench should pass review requirements to the selected harness as approved
natural-language instructions. The harness may use native read-only reviewers or
other subagents, but AI Workbench should not add a provider-neutral review Attempt
or review/rework state machine.

## Capability comparison

Legend: **native** means the capability is part of the named runtime; **external**
means the application must supply another persistence, sandbox, or control layer.

| Option | Multi-role / subagents | Long task and resume | Live events | Approval and cancellation | Structured result | Repository isolation |
| --- | --- | --- | --- | --- | --- | --- |
| **Codex Python SDK** | Native Codex subagents and project custom agents; orchestration is agent-driven, not a deterministic DAG | Persisted thread resume is native; AI Workbench must still recover an interrupted outer Attempt | Typed app-server notifications; CLI/TS SDK also expose structured event streams | App-server approval requests plus `turn/interrupt` and `turn/steer`; outer wall-clock watchdog still required | Native JSON Schema final output | Sandbox presets are native; pass an AIWB-created Git worktree as `cwd` |
| **Claude Agent SDK** | Native subagents with per-agent prompt, tools, model, turns, effort, background mode, and permissions | Local transcript resume/fork is native; filesystem state is external | Async message iterator, partial streaming, hooks, subagent lifecycle, usage and cost | Tool callbacks/hooks and permission modes; `ClaudeSDKClient.interrupt()` works, but `query()` has no interrupt | Native JSON Schema output | Sandbox is native; SDK should receive an AIWB-created worktree path |
| **Generic ACP Driver** | Agent-owned; ACP carries the harness session rather than defining its internal roles | Stable session list/resume/close where the selected agent advertises them; capability probe required | JSON-RPC session updates and streamed content/tool events; exact coverage is agent-advertised | Standard permission requests and prompt cancellation; implementation quality varies by agent | No universal AIWB result schema; finish with a small AIWB-owned terminal projection plus machine Harness | Client supplies the session `cwd`; AIWB still creates and owns the Git worktree |
| **OpenAI Agents SDK** | Native agents-as-tools, handoffs, and code-driven orchestration | Serializable approval `RunState` and conversation sessions; crash-proof execution requires a durable integration | Semantic streaming, cancellation, hooks, and built-in tracing | Run-wide tool approvals can pause, serialize, and resume | Native typed `output_type` | Sandbox Agents provide resumable workspaces, but are beta and are not Git candidate management |
| **LangGraph** | Graphs and subgraphs can model supervisors, handoffs, and parallel agents | Checkpointers persist graph steps and resume by thread ID | Rich typed projections for messages, state, subgraphs, tasks, checkpoints, and interrupts | Generic interrupts; Python async node run/idle timeouts are currently alpha | Available through LangChain agents/provider strategies | No coding sandbox or Git worktree ownership |
| **Temporal** | Child Workflows and Activities can host agents; no coding-agent semantics itself | Strongest durable replay, retries, Signals, cancellation, and years-long execution | Event History, Visibility, and SDK/OTel integrations | Workflow cancel/terminate and Activity timeouts/heartbeats | Application-defined payloads only | No coding sandbox or Git worktree ownership |

| Option | Durable authority supplied | Provider lock-in | AIWB adoption complexity |
| --- | --- | --- | --- |
| **Codex Python SDK** | Conversation/thread history; AIWB remains the Run and acceptance authority | High at the harness adapter, low outside it | **Low** |
| **Claude Agent SDK** | Conversation/session history; external filesystem and business state | High at the harness adapter | **Medium** |
| **Generic ACP Driver** | Agent-specific session continuity behind a common client protocol; AIWB remains the Run authority | Low protocol lock-in; behavior remains harness-specific | **Medium** |
| **OpenAI Agents SDK** | Serializable approval state and sessions; durable execution needs an integration | Medium-high, highest with hosted OpenAI sandbox/tracing | **Medium-high** |
| **LangGraph** | Graph checkpoints can become a competing business-state authority | Medium; model providers are portable, graph semantics are not | **High** |
| **Temporal** | Full workflow Event History and durable execution authority | Low provider lock-in, high runtime/operational commitment | **Very high** |

## Findings by option

### 1. Codex SDK: best default for this repository

The Codex TypeScript SDK explicitly wraps the Codex CLI and exchanges JSONL events
over stdin/stdout. Its `runStreamed()` exposes tool calls, responses, and file
changes as structured events, supports per-turn JSON Schema output, persists
threads under `~/.codex/sessions`, and accepts an `AbortSignal`
([official SDK README](https://github.com/openai/codex/tree/main/sdk/typescript),
[execution source](https://github.com/openai/codex/blob/main/sdk/typescript/src/exec.ts)).

The Python SDK is a better fit for the current AI Workbench implementation. It is
documented as stable, ships a pinned Codex runtime, and talks to app-server over
typed JSON-RPC rather than scraping process output
([Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk),
[Python SDK](https://github.com/openai/codex/tree/main/sdk/python)). The app-server
protocol supports:

- structured item and turn notifications;
- client-handled command and file-change approval requests;
- `turn/interrupt` with an authoritative terminal `turn/completed` event;
- `turn/steer` for a live turn;
- explicit background-terminal listing and cleanup.

These are documented in the
[app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md).
The current Python implementation also exposes an approval handler, notification
routing, turn interruption, and steering
([Python API reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md),
[client source](https://github.com/openai/codex/blob/main/sdk/python/src/openai_codex/client.py)).

Important limits:

- a persisted thread is conversation continuity, not an exactly-once recovery
  guarantee for arbitrary shell or file side effects;
- Codex subagent orchestration is model-directed. AI Workbench should not treat its
  internal task graph as a deterministic acceptance authority;
- in non-interactive flows, a new approval that cannot be surfaced fails back to
  the parent workflow, so AI Workbench must admit a sufficient fixed permission
  envelope before the night Run
  ([subagent approval behavior](https://learn.chatgpt.com/docs/agent-configuration/subagents));
- SDK sandboxing does not create the desired Git candidate topology. AI Workbench
  should continue to create the worktree, then pass that exact directory to Codex.

Adoption complexity is **low** relative to the current code: replace the blocking
CLI capture adapter with a thin SDK session adapter and map only a few lifecycle
facts into RunLedger.

### 2. Claude Agent SDK: valid second native backend, not a common workflow model

Anthropic describes the Agent SDK as the same tools, agent loop, and context
management that power Claude Code, programmable in Python or TypeScript. It
includes built-in file/command tools, hooks, subagents, MCP, permissions, sessions,
Skills, plugins, file checkpoints, cost tracking, and OpenTelemetry
([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)).

The Python API distinguishes `query()` from `ClaudeSDKClient`: both stream
messages, but only the client supports interruption and automatic continued
conversation
([Python reference](https://code.claude.com/docs/en/agent-sdk/python)). Native
subagents can set their own model, effort, tools, permissions, turn limit, and
background behavior; Anthropic also documents deterministic caps for spawn depth,
concurrency, and spend
([subagents](https://code.claude.com/docs/en/agent-sdk/subagents),
[model guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5)).

Sessions can resume and fork, but their local transcript is not a durable copy of
the repository filesystem. AI Workbench still needs the worktree and acceptance
Evidence
([sessions](https://code.claude.com/docs/en/agent-sdk/sessions)).
Tool allow/deny lists, permission modes, hooks, and callbacks provide a native
approval surface, while JSON Schema, Zod, or Pydantic schemas provide validated
structured results
([permissions](https://code.claude.com/docs/en/agent-sdk/permissions),
[structured outputs](https://code.claude.com/docs/en/agent-sdk/structured-outputs)).

Adoption complexity is **medium**. Keep it as a provider-native backend with its
own event and permission adapter. Do not force Codex and Claude into a lowest-common-
denominator role state machine. Normalize only Attempt lifecycle, usage, outcome,
and Evidence references.

### 3. ACP: the generic third Driver, not another agent loop

The Agent Client Protocol is the right common control seam for vendor harnesses
that already expose it. It is JSON-RPC over stdio between a client and a coding
agent; the agent continues to own its model, tools, context, and execution. The
protocol now has stable session configuration, list, resume, and close surfaces.
Session Config Options let an agent expose model, mode, reasoning level, and other
selectors without the client hard-coding vendor fields
([ACP updates](https://agentclientprotocol.com/updates),
[Session Config Options](https://agentclientprotocol.com/announcements/session-config-options-stabilized)).

The curated ACP registry currently includes Kimi CLI, Qwen Code, OpenCode, Gemini
CLI, GitHub Copilot, and OpenHands, among others
([ACP agents](https://agentclientprotocol.com/get-started/agents),
[registry repository](https://github.com/agentclientprotocol/registry)). This is
enough coverage to justify one generic Driver plus declarative launch/capability
profiles instead of a code Adapter for each harness. AIWB setup should start the
declared command, inspect advertised capabilities and config options, set the
approved values, run a disposable-worktree smoke, and freeze the exact executable,
version, arguments, selected options, and probe Evidence into Admission.

ACP is a lowest common **lifecycle** contract, not a guarantee of identical agent
behavior. Resume, close, permissions, content blocks, and configuration must be
capability-probed; machine acceptance remains AIWB-owned. Native Codex and Claude
drivers remain worthwhile because their SDKs expose richer provider-specific
approval, sandbox, structured-output, and event semantics than a generic ACP
projection.

### 4. OpenAI Agents SDK: strong general orchestration, unnecessary in front of Codex

The Agents SDK supports two first-class multi-agent patterns: a manager calls
agents as tools, or an agent hands the conversation to another agent. It also
supports code-controlled chaining and parallel execution
([agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)).
Typed `output_type` schemas, semantic streaming, immediate or after-turn
cancellation, run-wide nested-tool approvals, serializable `RunState`, sessions,
and tracing are native
([agents and outputs](https://openai.github.io/openai-agents-python/agents/),
[streaming](https://openai.github.io/openai-agents-python/streaming/),
[human in the loop](https://openai.github.io/openai-agents-python/human_in_the_loop/),
[tracing](https://openai.github.io/openai-agents-python/tracing/)).

However, the core runner is not crash-proof by itself. The official docs point to
Dapr, Temporal, Restate, or DBOS for runs that span process restarts or long waits
([running agents](https://openai.github.io/openai-agents-python/running_agents/)).
Sandbox Agents add resumable isolated workspaces, but that surface is explicitly
beta
([Sandbox Agents concepts](https://openai.github.io/openai-agents-python/sandbox/guide/)).

This is a useful choice when Codex is one tool in a broader business workflow; the
Codex docs recommend exactly that composition through MCP
([Codex SDK guidance](https://learn.chatgpt.com/docs/codex-sdk),
[Codex with Agents SDK](https://learn.chatgpt.com/docs/mcp-server)). It is not the
smallest solution for an AI Workbench whose main job is running coding tasks.

Adoption complexity is **medium-high** and OpenAI lock-in remains **high** for its
best sandbox and tracing features. Do not adopt it as the default outer runtime.

### 5. LangGraph: capable graph runtime, but would duplicate RunLedger

LangGraph checkpointers save graph state at each step and enable human-in-the-loop,
fault recovery, time travel, and thread memory. SQLite and PostgreSQL checkpointers
are available
([persistence](https://docs.langchain.com/oss/python/langgraph/persistence)).
Subgraphs support multi-agent designs and per-invocation or per-thread persistence
([subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)). Its
event stream exposes messages, state, nested graphs, output, tasks, checkpoints,
debug events, and interrupts as typed projections
([event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)).

The cost is a new application-owned graph schema and replay model. Interrupt resume
restarts the interrupted node from the beginning, so pre-interrupt side effects
must be idempotent
([interrupt rules](https://docs.langchain.com/oss/python/langgraph/interrupts)).
Python node run/idle timeouts are useful but are currently alpha and async-only
([fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)).
LangGraph owns neither a coding sandbox nor Git candidate isolation.

Adoption complexity is **high** for this repository because its checkpoint state
would overlap with RunLedger, Todo state, Attempts, approvals, and recovery. It is
appropriate only if AI Workbench later becomes a general user-defined workflow
product. It should not replace the current coding-agent adapter.

### 6. Temporal: excellent durable infrastructure, too heavy for the default local tool

Temporal Workflows can survive infrastructure failure for years by replaying an
ordered Event History. External I/O, including LLM calls and file operations, must
run as Activities; Activities should be idempotent
([Workflows](https://docs.temporal.io/workflows),
[Activities](https://docs.temporal.io/activities)). Cancellation is durable, but
long Activities must heartbeat to receive cancellation and checkpoint progress
([Python cancellation](https://docs.temporal.io/develop/python/workflows/cancellation)).

Temporal provides no coding-agent loop, structured agent result, filesystem
sandbox, or Git worktree. Those remain application Activities. Its official
OpenAI Agents integrations are useful but still add a server, worker, task queue,
deterministic Workflow constraints, and Activity boundaries; the TypeScript
integration is explicitly experimental, while Python sandbox integration is
pre-release
([TypeScript integration](https://github.com/temporalio/sdk-typescript/blob/main/contrib/openai-agents/README.md),
[Python integration](https://github.com/temporalio/sdk-python/blob/main/temporalio/contrib/openai_agents/README.md)).

Even Temporal's own guidance says to start with one Workflow and Activities rather
than Child Workflows until there is a clear need
([Child Workflows](https://docs.temporal.io/child-workflows)). Adoption complexity
is **very high** for a single-user local workbench. Reconsider Temporal only if
AI Workbench needs multiple hosts, a remote durable service, or workflows that wait
days across deployments. It is not the remedy for a blocked local `codex exec`.

## Harness integration architecture

AIWB's integration unit is a **coding harness**, not an LLM model, inference API,
or model provider. A HarnessDriver drives session/thread lifecycle, the agent
loop, tools, permissions, events, cancellation, and workspace binding. The harness
owns its own model-provider configuration and protocol translation.

There are two useful integration surfaces, and AIWB should ship one component for
each:

1. **Drivers (external control plane):** native Codex App Server/SDK, native Claude
   Agent SDK, and generic ACP. AIWB uses these to start, observe, approve, cancel,
   and resume a harness Run.
2. **Extension Pack (embedded plane):** one portable MCP server plus Agent Skills.
   It exposes bounded policy, ticket, and machine-Harness actions *to* an already
   running coding harness without owning its agent loop.

Changing from Codex App Server to Claude Agent SDK is a Driver change. Selecting
Kimi Code rather than Qwen Code behind ACP is normally only a declarative launch
and capability profile. Changing the model selected inside either harness is
opaque harness configuration: AIWB may display and freeze the resolved choice at
setup, but must not implement its wire protocol.

### Driver and Extension Pack matrix

| Harness | Active-control surface | Portable extension surface | AIWB integration decision |
| --- | --- | --- | --- |
| **Codex** | Stable Python SDK and App Server with typed events, approvals, interrupt, steering, resume, and structured output | MCP and Agent Skills; hooks/custom agents remain optional harness-native wrappers | **Native Driver, required first** |
| **Claude Code** | Agent SDK async sessions with stream, permissions, interrupt, resume, subagents, and structured output | MCP and Agent Skills; Claude plugins/hooks can package or wrap them | **Native Driver, required second** |
| **Kimi Code** | Product `kimi acp` JSON-RPC stdio mode; Kimi Agent SDK is also available | MCP and Agent Skills; plugins can package Skills, MCP, hooks, agents, and commands | **ACP launch profile; no Kimi Driver** |
| **Qwen Code** | Stable `qwen --acp`; its own daemon also uses ACP internally | MCP and Agent Skills; extensions package both and natively load portable Agent Plugins v1 | **ACP launch profile; no Qwen Driver** |
| **OpenCode** | Listed in the curated ACP registry; also has a typed server SDK | MCP and Agent Skills/plugins | **ACP launch profile first; native Driver only if a proven missing ACP capability blocks unattended Runs** |
| **GitHub Copilot** | Official Copilot CLI ACP server is public preview; separate SDK also exists | MCP, Agent Skills, custom agents/tools | **ACP launch profile after qualification; no SDK Driver now** |
| **OpenHands** | ACP is experimental; separate Agent Server/SDK is much larger | MCP and Skills/context | **ACP launch profile for local use; reconsider native SDK only for remote-container requirements** |
| **DeepSeek Harness** | Official `@deepseek-ai/dsh-acp` automation bridge and `acp-agent` example, but the product is a developer preview and the ready-made bundle is explicitly demo surface | Native Cordis bundles can mount its MCP client and filesystem Skill provider, including shared `~/.agents/skills` roots | **Experimental ACP profile only; do not depend on its internal plugin API yet** |

The common denominator is now concrete. The official ACP registry lists Kimi CLI,
Qwen Code, OpenCode, GitHub Copilot, and OpenHands
([ACP agents](https://agentclientprotocol.com/get-started/agents),
[registry](https://github.com/agentclientprotocol/registry)). Kimi documents
`kimi acp` as its product subprocess entry point
([Kimi ACP](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-acp)),
and Qwen documents stable `--acp` plus an internal ACP bridge
([Qwen configuration](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/settings.md),
[Qwen architecture](https://qwenlm.github.io/qwen-code-docs/en/developers/architecture/)).
DeepSeek Harness has an automation-oriented ACP bridge with session, permission,
cancellation, and worktree `cwd` semantics, but its repository labels the overall
product developer preview and the assembled ACP bundle demo/reference surface
([DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness),
[ACP example](https://github.com/deepseek-ai/deepseek-harness/blob/master/examples/acp-agent/README.md),
[demo-bundle boundary](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/examples/README.md)).

The Extension Pack is equally portable. Kimi plugins can contain Skills and MCP
servers
([Kimi plugins](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html));
Qwen extensions package Skills and MCP and can directly load portable Agent
Plugins v1 packages
([Qwen extensions](https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/));
DeepSeek Harness provides a filesystem Skill provider and stdio/Streamable HTTP
MCP client as plugins
([DeepSeek config catalog](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/config-catalog.md)).
This validates **MCP + Agent Skills** as the cross-harness product surface. Native
plugin manifests, hooks, commands, and marketplaces are packaging conveniences,
not AIWB architecture.

The non-native options do have substantial first-party control planes: Copilot's
SDK provides typed events, resume, abort, and permission callbacks
([Copilot SDK](https://github.com/github/copilot-sdk)); OpenHands provides a
persistent Agent Server and remote workspaces
([Agent Server](https://docs.openhands.dev/sdk/guides/agent-server/overview));
OpenCode exposes a typed server SDK
([OpenCode SDK](https://opencode.ai/docs/sdk)); and Kimi provides a multi-language
Agent SDK
([Kimi Agent SDK](https://github.com/MoonshotAI/kimi-agent-sdk)). Those are escape
hatches, not reasons to write four Drivers now. GitHub already exposes an official
ACP server, albeit in public preview
([Copilot ACP](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server));
OpenHands labels its ACP product surface experimental
([OpenHands ACP](https://docs.openhands.dev/openhands/usage/cli/ide/overview)).
Start with ACP and promote one harness to a native Driver only when a concrete,
accepted requirement cannot be expressed or made reliable through ACP.

### Model-carrier evidence stays behind the harness

DeepSeek, Kimi, and GLM publish model-endpoint compatibility for several coding
harnesses. That proves the **harness may carry the model**; it does not create an
AIWB Driver. AIWB must not call those model APIs, translate Chat/Responses/
Anthropic traffic, or qualify a raw endpoint. It qualifies the selected harness
through its public Driver surface and freezes only the harness-reported model,
mode, and reasoning selections.

Examples of the correct boundary are vendor-side harness recipes, not AIWB
protocol work: DeepSeek publishes Codex and Claude Code integration guides
([Codex](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/),
[Claude Code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code));
Kimi publishes Claude Code and its own Kimi Code harness
([Claude Code](https://platform.kimi.ai/docs/guide/claude-code-kimi),
[Kimi Code](https://www.kimi.com/code)); and GLM publishes tool-integration
endpoints for existing coding tools
([GLM integrations](https://docs.bigmodel.cn/cn/guide/develop/others)). AIWB's
architecture remains the same when those recipes change.

HTTP compatibility is not coding-harness compatibility. AIWB therefore records
only **Harness qualified** Evidence: the selected harness must demonstrate its
actual tools, event stream, permission path, cancellation, resume, terminal
projection, and worktree behavior. A successful model endpoint request is neither
an AIWB integration nor overnight-Run evidence.

### Recommended harness-only design

Keep exactly two native Drivers plus one generic protocol Driver. Treat all
model/provider details as opaque, harness-owned session configuration:

```text
HarnessDriver
  codex  -> Codex Python SDK / App Server
  claude -> Claude Agent SDK
  acp    -> generic ACP client

ACPLaunchProfile (declarative data, not code Adapters)
  command + args + env allowlist + expected capabilities
  Kimi Code | Qwen Code | OpenCode | Copilot | OpenHands | DeepSeek Harness

ExtensionPack
  MCP server + Agent Skills
  optional thin install wrappers for native plugin/extension formats

HarnessAdmission
  driver + harness id/version + executable digest + launch/profile digest
  advertised capabilities + frozen ACP config options
  resolved model/mode/reasoning display + qualification Evidence
```

Implement Codex first, Claude second, and generic ACP third. ACP Session Config
Options can carry agent-advertised model, mode, and reasoning selectors; daytime
setup resolves them and Admission freezes their values
([ACP Session Config Options](https://agentclientprotocol.com/announcements/session-config-options-stabilized)).
Expose AIWB's bounded policy and machine-Harness actions through one small MCP
surface plus portable Agent Skills. Harness-specific hooks, commands, plugins, and
extensions are thin installation wrappers over that same AIWB authority, not
additional orchestration engines.

Do not create `DeepSeekDriver`, `KimiDriver`, `QwenDriver`, `OpenCodeDriver`,
`CopilotDriver`, `OpenHandsDriver`, a generic `ModelProviderConfig`, or an AIWB
Chat/Responses/Anthropic translator. Add a native Driver only after a concrete
unattended-control requirement is accepted, the generic ACP Driver cannot satisfy
it, and the harness offers a stable programmatic control plane.
Run a fail-closed **Harness qualification** during daytime setup. At minimum it
should verify through the harness's public control surface:

1. the exact Harness/version/profile starts and reports its resolved model/backend;
2. typed streaming or structured CLI events expose progress and terminal state;
3. approval, cancellation, and resume work without an unresolved prompt hanging;
4. structured terminal results satisfy the small `CodingOutcome` contract;
5. one disposable-worktree coding smoke succeeds using the harness's native tools.

Cache the result by Harness version and opaque profile/config digest. Show the
resolved model/backend as diagnostic information in `aiwb setup`, freeze the
qualification Evidence into Admission, and invalidate it whenever the harness or
profile changes. AIWB should not parse or persist the underlying API key or
wire-level schema; the harness process can receive its own secret reference through
the existing launch policy.

## Simplified target architecture

```text
Owner
  -> aiwb setup / approve
  -> immutable Admission (goal + models + permission envelope + commands + base SHA)
  -> AIWB Run
       -> create candidate worktree
       -> record AttemptStarted
       -> selected HarnessDriver session in that worktree
            -> native Codex | native Claude | generic ACP profile
            -> native planning, tools, context management, and optional subagents
            -> typed events streamed to bounded raw Evidence
       -> record AttemptEnded
       -> run approved machine Harnesses
       -> store Harness Evidence
       -> merge_ready | needs_human | failed
```

The normalized harness interface should be lifecycle-oriented, not a clone of
every harness's agent model:

```python
class CodingHarness:
    async def run(
        self,
        request: CodingRequest,
        events: EventSink,
        cancel: Cancellation,
    ) -> CodingOutcome: ...
```

`CodingOutcome` needs only:

- harness thread/session ID;
- terminal outcome and typed failure class;
- final structured report or a reference to it;
- usage/cost fields the harness actually reports;
- raw event Evidence reference;
- changed-worktree metadata needed before machine verification.

RunLedger should durably record `AttemptStarted` **before** starting the SDK turn,
then periodically update a bounded heartbeat such as last event timestamp and event
count. It should not persist a separate row for every harness subagent or tool
call. Raw event streams belong in bounded Evidence objects, not in the canonical
control schema.

## Harness profile and assurance simplification

Assurance requirements remain useful, but they should be natural-language input
to one harness-owned agent loop rather than provider-neutral role state. At setup,
AI Workbench should show and freeze the complete harness-native profile, including
the exact primary and internal-role models and reasoning efforts that the harness
exposes. For Codex, project-scoped custom-agent files already support per-agent
model, reasoning, sandbox, MCP, and Skill settings; AI Workbench can hash and
display those resolved files instead of reimplementing role execution
([custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)).
Subagents inherit the parent permission mode unless explicitly narrowed, so a
reviewer can be read-only while the one overnight grant covers the parent Run.

## Migration slices

1. **Replace only the Codex process seam.** Add a Codex Python SDK Driver that
   streams events, requires an explicit fail-closed approval handler, persists the
   thread ID, and interrupts on the existing timeout. Keep all current acceptance
   behavior unchanged.
2. **Remove the provider-neutral role flow.** Start one primary Agent Harness
   Attempt per Run and let its native loop plan, delegate, review, and rework.
   Remove Test Designer, Implementer, Verifier, Planner, Worker, Reviewer, and
   Todo-DAG execution states rather than retaining a compatibility mode.
3. **Reduce RunLedger facts.** Retain Run, Attempt, terminal outcome, checkpoints
   around Git/Harness operations, and Evidence references. Treat provider-native
   plans, subagents, and tool events as opaque Evidence.
4. **Dogfood one bounded ticket.** Compare wall-clock time, owner approvals,
   recovery behavior, and machine Evidence against the current flow before deleting
   compatibility code.
5. **Add the other two Drivers without broadening the core.** Implement Claude
   Agent SDK as the second native Driver, then a capability-probed generic ACP
   Driver with declarative profiles. If native parity forces a large common
   abstraction, keep Driver-specific event projections instead of expanding the
   canonical ledger.

## Revisit criteria

Do not add LangGraph or Temporal because a provider process is hard to observe.
Revisit them only when a requirement cannot be met by the native SDK plus the thin
AI Workbench boundary:

- choose **LangGraph** only for owner-authored, dynamically branching graph
  workflows whose graph state is itself a product surface;
- choose **Temporal** only for multi-host execution, remote workers, deployment-
  crossing waits, or service-level durability that the local daemon cannot meet;
- choose **OpenAI Agents SDK** only when the product becomes a broader multi-agent
  application in which Codex is one specialist rather than the primary coding
  harness;
- consider hosted Sandbox/Managed Agent products only after their beta surfaces,
  data boundary, retention, and cost fit the repository's local-first goals.

## Decision summary

The simplest credible design is not “AIWB orchestrates agents better than every
harness.” It is:

> AIWB admits and accepts coding work; the selected coding harness performs it.

This preserves the project's differentiators—reviewable setup, bounded overnight
authority, immutable Admission, isolated Git candidates, machine Harness Evidence,
and durable audit—while deleting the least differentiated and fastest-changing
part: a home-grown coding-agent runtime.
