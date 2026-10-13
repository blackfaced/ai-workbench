# 0013 — Project-owned agent context

- Status: Accepted
- Date: 2026-10-13
- Supersedes: global AGENTS and recurring digest-hook distribution in ADR 0011

Global company workflow rules constrained unrelated personal projects, while Botmux roles repeated parts of the same workflow. A project directory must identify its own applicable tracker, commit conventions, knowledge sources, testing methods, and delivery workflow. A personal project does not inherit a company requirement merely because both run on the same machine.

`setup-aiwb` establishes and maintains this context and its existing integration-test guide. It discovers the target project's rules and uses the selected client's native loading mechanisms. Team-owned `AGENTS.md` remains intact. Private additions use a verified additive project configuration; `AGENTS.override.md` is not an additive layer, and `.agents/private/` has no implied native discovery contract. Trust and the effective instruction source must be checked, including the actual startup directory. Each new worktree needs explicit provisioning and verification when private configuration is not tracked.

AIWB continues to own reusable engineering instructions. Project-specific policy stays with the project or its authoritative owner. Projects may select a pinned instruction pack; setup records the source and revision instead of silently copying machine-global policy. The environment installer distributes the Skill, not company workflow into every client session. No new context router or agent runtime is introduced.

Botmux supplies identity, communication, and a correctly selected working directory. Its roles refer to the target project's workflow rather than embedding a second copy. A brief that tells an already-started client to change directories does not establish that project configuration was loaded at startup. Existing sessions and unrelated role customizations must survive migration.

Retire only owned global AGENTS blocks and repeated L1 hooks after project startup, worktree, and Botmux checks pass. The distributor must stop reinstalling them. Removal requires a read-only plan, ownership checks, recoverable backups, and conflict-protected restoration. Preserve third-party hooks and trust records even when a client has moved them inside our historical marker span. Keep migration evidence and report verified hosts separately from fresh-install or inaccessible-host coverage.
