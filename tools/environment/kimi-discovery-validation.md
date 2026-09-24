# Kimi discovery validation

- Domain: ops
- Date: 2026-09-13
- Scope: Issue #94; local Kimi 0.39.0 native ACP and isolated fixtures.

Before implementation the positive fixture failed because kimi_skills_discovery.py did not exist. The same path passed after implementation. Cases cover notifications before/after the session response (including one pipe write), empty lists, missing profile Skills, initialize/session errors, configuration exit, malformed JSON/schema, duplicate commands, wrong session, missing notifications, partial-line/silent timeout, direct child/descendant cleanup and README preservation. Failed tests retain first-request/result artifacts without automatic retries.

Native command: `python3 tools/environment/kimi_skills_discovery.py /Users/bytedance/.kimi-code/bin/kimi`, exit 0 on Kimi 0.39.0. All seven first-party commands were observed. The adapter sends initialize/session/new only, with an empty cwd and no forwarded MCP servers or model prompt. No client installation, configuration or login state was changed; client-owned session/log metadata may be written.

The home Mac 0.41.0 manual result remains in the [original report](home-mac-validation.md). Run `sh tools/environment/bootstrap.sh --profile home-mac --check` there to verify this new automated entry. This local protocol test does not establish home-machine full-profile acceptance or Skill execution.

Full environment regression: 85 checks passed, including the five Kimi test methods and their protocol subcases. Markdown local references resolve; diff whitespace checks pass. These are local validation results, not remote CI.

## Home-Mac fixture cold-start repair (2026-09-21, #99)

Base `0d7bfe2` reproduced the empty-list failure in a single 0.854s test.
New executable fixtures took up to 4.13s on first launch, while an explicit
existing Python interpreter took 24–28ms. Timestamp probes placed the delay
before the fixture body, not in ACP parsing; no particular macOS security
subsystem is asserted as the cause.

Red/green: the added CLI test for a non-executable Python fixture with a spaced
path first exited 2 (usage), then passed with explicit `-- command args...` argv
support. Existing binary invocation and the real 45-second default are unchanged.
All fixture runs now use the running interpreter, fresh per-attempt evidence,
exact expected protocol requests, and distinct protocol-error/timeout statuses.
Normal tests allow 5s; deliberate timeout cases retain 0.8s and verify process
cleanup, including descendants. No retries or warm-up runs were added.

Candidate `codex/fix-kimi-fixture-startup`: seven focused test methods pass;
full regression passes 85/85 on both home-Mac Python 3.14.7 and 3.9.6, run
alongside the native environment check. The home-mac check also passes: Kimi
0.41.0 advertises 37 commands including all seven required first-party Skills.
This covers existing-machine maintenance, not fresh install or model execution.
Original failure artifacts and diagnostic comparisons are retained locally.
Hosted CI remains a separate merge gate: check the associated PR's candidate-specific
results rather than inferring CI success from these local results.
