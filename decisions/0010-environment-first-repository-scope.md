# 0010 — Environment-first repository scope and orchestrator retirement

- Status: Accepted
- Date: 2026-09-07
- Domain: ops
- Extends: [0009](0009-reproducible-development-environments.md), replacing its decision to retain the optional orchestrator.
- Updates: the primary-purpose statement in [0001](0001-repository-scope-and-structure.md); artifact-based organization remains in force.
- Supersedes: runtime guidance in ADRs 0002–0008.

## Decision

The maintained product is a personal development environment entry point under `tools/environment/`. Its current verified target is maintenance of the work Mac and two existing Linux development machines. Complete fresh-machine bootstrap remains incomplete; the inaccessible home Mac is deferred.

The owner explicitly approved retirement of the unattended agent orchestrator. Remove its package, CLI/MCP entry points, daemon, dedicated tests, examples, repository Skills, workflow guide, and optional `aiwb` Profile installation entry. Remove the obsolete generated code graph so it cannot seed discovery with retired code. Do not introduce a replacement orchestration layer: clients own their agent loops.

Root documentation and agent guidance describe profiles, ownership, drift, application, and guarded restore. Skill catalogs and integration notes are optional references, not an implicit installation list or mandatory model workflow. Active work is tracked in issues; existing `todo/` notes are historical.

## Validation and CI

Environment plan/apply/check/restore retain their existing shared implementation and safety boundaries. CI runs the standard-library environment regression suite on Linux and macOS, including Python 3.9. Existing CI job names are retained to avoid unnecessarily changing required-check identities; their commands now verify the maintained environment tool. Runtime-specific dependency installation and evidence uploads are removed.

## History and installed copies

Historical ADRs remain with retirement notices. The last source version before retirement is [f54a9b3](https://github.com/blackfaced/ai-workbench/tree/f54a9b324afedc06a45603ca18cd521dbd903c3f/tools/agent-orchestrator).

This repository change does not uninstall existing `aiwb` packages, stop daemons, remove client MCP registrations, or delete runtime data on any machine. An editable installation that points at a checkout containing this deletion will no longer work. Machine-level retirement requires a separate inventory and cleanup; environment apply no longer installs or manages `aiwb`.
