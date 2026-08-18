# 0004 - Use Subscription-First Resource Boundaries Without Provider Fallback

## Status

Accepted

## Context

AI Workbench is intended to run approved development work unattended, often
through subscription-authenticated Codex or Claude Code CLIs. A Run still needs
optional safety boundaries so one bad loop cannot consume unbounded Agent
Attempts, wall-clock time, Harness time, or provider-reported tokens.

Those boundaries must not pretend that provider tokens are a reliable monetary
price. They also must not turn a subscription quota response into a failed code
Attempt when no code work occurred, or silently switch to another provider or
model.

## Decision

An approved Contract may omit `resources` entirely or configure positive
boundaries for:

- `agent_attempts`;
- `wall_clock_seconds`;
- `harness_seconds`;
- `provider_tokens`, counted only from usage actually reported by the selected
  provider.

The runner checks the relevant boundary before starting the next Agent or
Harness operation. Reaching a configured boundary creates a durable
`paused_resource` or `paused_deadline` checkpoint. A provider subscription or
quota response creates `paused_provider_quota` and retains any known usage, but
does not record a code Attempt for work that did not execute.

Resume is explicit through the shared daemon control plane. It starts a new
resource window from the durable checkpoint and preserves the Contract-fixed
provider plus every Role Profile's model and reasoning effort. Role profiles
inherit one default model unless the owner explicitly approves per-role values.
Daemon restart never resumes a paused Run automatically.
Independent Todos that were already admitted may reach a durable checkpoint;
dependents of the paused Todo remain frozen.

CLI, MCP, and reports expose the same structured stop record. Resource,
deadline, provider quota, Harness, final acceptance, and cleanup stops remain
distinct. Monetary cost remains unknown unless a future provider supplies a
reviewed, trustworthy price signal.

No resource boundary grants permission expansion, production access, provider
fallback, runtime model switching, test weakening, target-branch merge, or
deployment.

## Consequences

Users who rely on subscriptions can leave all boundaries unset and let the
provider stop naturally. Users who want tighter overnight control can review
the boundaries in `aiwb goal preflight` before approval and arrange explicit
resume windows without changing the Contract.

A low boundary may pause frequently, and provider-reported token totals may be
missing or provider-specific. That uncertainty is visible in Evidence rather
than converted into an invented cost estimate.
