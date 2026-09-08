# 0011 — Generic rule source and distribution

- Status: Accepted
- Date: 2026-09-08

AIWB owns the reusable engineering-principles instruction pack under `skills/engineering-principles/`. dev-tracker consumes a full immutable Git commit, adds its own work-environment policy, and remains the sole distributor to global AGENTS and the digest hook. AIWB environment tooling observes ownership and conflicts; it does not duplicate this writer.

Migrate the generic meaning from dev-tracker `0c922c9` without simultaneous doctrine redesign. Preserve internal platform rules and project knowledge at their original owners. Keep the digest with its canonical full rules and review both together. Publish companion review/debt procedures from the same commit; render their paths into the installed package.

Failure to resolve the pinned pack must precede any client mutation. Keep content-addressed installed hooks, snapshot consistency, existing client customization, and explicit host trust handling. Pin upgrades are deliberate; neither workspace edits nor source-path overrides select another content version. No second automatic engineering-principles Skill is installed.
