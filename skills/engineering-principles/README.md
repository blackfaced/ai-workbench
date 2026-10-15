# Engineering principles instruction pack

This is a distributable instruction pack, not an automatically invoked Skill. `rules.md` is the canonical general policy; `digest.md` is its reviewed short projection; `review.md`, `debt.md`, `environment-identity-assumptions.md`, and `error-observability.md` are companion procedures. Project/platform-specific policy remains with the consuming repository.

Consumers resolve all files from one full Git commit, never a mixture of mutable checkouts. `@RULES_DIR@` is rendered to the absolute installed companion directory. Preserve the existing content-addressed hook trust boundary. Update rules and digest together when their meaning changes; fixed-version consumption prevents version mixing but cannot mechanically prove a handwritten summary is faithful.

When updating a consumer's pin, include every referenced companion and verify that the selected client's effective context reaches the rules and those files. An exporter with an explicit file list must update that list; source edits alone do not prove distribution or runtime loading.

Project onboarding uses `setup-aiwb` to derive project-owned error/observability conventions from verified current code, relevant fixes and tests. This pack supplies general criteria; exact helpers, codes, queries and project evidence stay with the target repository.

The first migration preserves the generic sections from downstream `0c922c9`; numbering is retained for source traceability. Sections 6, 8 and 9 are work-environment policy and stay in downstream. No second global automatic Skill installation is created.
