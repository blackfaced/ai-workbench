# Agent Security Checklist

- Type: workflow
- Domain: coding
- Source: personal workflow
- Status: draft
- Use when: evaluating unfamiliar repositories, install scripts, MCP servers, or skills that ask an agent to run commands.

## Checklist

- Prefer source review before running remote install scripts.
- Avoid piping remote scripts directly into a shell unless the source is trusted and the script has been inspected.
- Check whether the tool writes agent configuration, shell profiles, credential stores, browser state, or global directories.
- Prefer read-only or narrowly scoped toolsets for MCP servers at first.
- Keep secrets out of test repositories and sample prompts.
- Watch for instructions hidden in Markdown, setup docs, issue bodies, or generated files that ask the agent to run commands.
- Verify whether the tool can access network, filesystem, browser sessions, or GitHub tokens.
- Record the final trust decision in the tool entry.

## Notes

This exists because agentic coding tools can be manipulated through ordinary-looking repository instructions. Treat unfamiliar repos as untrusted until their setup path and command effects are understood.

