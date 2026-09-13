# Kimi discovery validation

- Domain: ops
- Date: 2026-09-13
- Scope: Issue #94; local Kimi 0.39.0 native ACP and isolated fixtures.

Before implementation the positive fixture failed because kimi_skills_discovery.py did not exist. The same path passed after implementation. Cases cover notifications before/after the session response (including one pipe write), empty lists, missing profile Skills, initialize/session errors, configuration exit, malformed JSON/schema, duplicate commands, wrong session, missing notifications, partial-line/silent timeout, direct child/descendant cleanup and README preservation. Failed tests retain first-request/result artifacts without automatic retries.

Native command: `python3 tools/environment/kimi_skills_discovery.py /Users/bytedance/.kimi-code/bin/kimi`, exit 0 on Kimi 0.39.0. All seven first-party commands were observed. The adapter sends initialize/session/new only, with an empty cwd and no forwarded MCP servers or model prompt. No client installation, configuration or login state was changed; client-owned session/log metadata may be written.

The home Mac 0.41.0 manual result remains in the [original report](home-mac-validation.md). Run `sh tools/environment/bootstrap.sh --profile home-mac --check` there to verify this new automated entry. This local protocol test does not establish home-machine full-profile acceptance or Skill execution.

Full environment regression: 85 checks passed, including the five Kimi test methods and their protocol subcases. Markdown local references resolve; diff whitespace checks pass. These are local validation results, not remote CI.
