# Engineering principles instruction pack

This is a distributable instruction pack, not an automatically invoked Skill. `rules.md` is the canonical general policy; `digest.md` is its reviewed short projection; `review.md` and `debt.md` are companion procedures. Project/platform-specific policy remains with the consuming repository.

Consumers resolve all files from one full Git commit, never a mixture of mutable checkouts. `@RULES_DIR@` is rendered to the absolute installed companion directory. Preserve the existing content-addressed hook trust boundary. Update rules and digest together when their meaning changes; fixed-version consumption prevents version mixing but cannot mechanically prove a handwritten summary is faithful.

The first migration preserves the generic sections from dev-tracker `0c922c9`; numbering is retained for source traceability. Sections 6, 8 and 9 are work-environment policy and stay in dev-tracker. No second global automatic Skill installation is created.
