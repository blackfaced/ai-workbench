# codebase-memory-mcp

- Type: MCP server
- Domain: coding
- Source: https://github.com/DeusData/codebase-memory-mcp
- Status: evaluating
- Use when: exploring unfamiliar or large codebases where structural code discovery should happen before file-by-file reading.

## Assessment

This is highly relevant to this workbench. It turns a codebase into a persistent knowledge graph and exposes code-intelligence tools such as graph search, call tracing, architecture summaries, impact mapping, and code search.

Best fit:

- Large or unfamiliar repositories.
- Review tasks where call paths, route ownership, and affected symbols matter.
- Architecture exploration before editing.
- Multi-service projects where cross-service links matter.

Useful default rule:

> Prefer graph tools for code discovery first; fall back to grep or file reads when searching strings, configs, docs, generated files, or when graph results are incomplete.

## Evaluation Plan

1. Index one familiar repository and one unfamiliar repository.
2. Compare against normal `rg` plus file-reading flow on the same task.
3. Measure whether it reduces irrelevant file reads and improves first-pass architecture understanding.
4. Verify how it handles Rust, TypeScript, Python, routes, generated files, and non-code assets.
5. Check how intrusive its agent configuration changes are.

## Risks

- It reads the full codebase and writes agent configuration files, so installation should be reviewed before use.
- It may create false confidence if the graph is stale or misses dynamic language behavior.
- It should not fully replace targeted string search for error messages, config keys, shell scripts, docs, or exact literals.

## Verdict

Promising enough to keep as a priority tool. Treat it as the default code-discovery accelerator only after local evaluation confirms indexing quality and config safety.

