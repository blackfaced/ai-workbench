Investigate a bug that escaped development checks and record a useful lesson in the owning project. Reflection is not authorization to repair code, deploy, or rewrite global rules. Keep project incidents and knowledge out of AIWB and assistant-global memory.

## Reconstruct the escape

Read the bug report, reproduction, originating requirement/Issue, relevant implementation and tests, and available review/build/deployment evidence. Fix the affected version and environment before comparing behavior. Distinguish what actually ran at development time from checks that merely existed or passed later. If historical evidence is unavailable, record unknowns rather than inventing the former agent's reasoning.

Separate the code defect from the detection gap: omitted requirement, absent case, ineffective assertion, unrealistic fixture/mock, unexecuted gate, wrong deployed candidate, or environment mismatch are hypotheses to test, not labels to assume. Explain which boundary could have detected this behavior and what evidence supports that claim. A request to reflect does not authorize production reproduction or harmful test effects; use existing evidence and permitted isolated checks, and identify blocked reproduction explicitly.

Find the smallest meaningful prevention: a regression assertion, a real integration case, a candidate-version check, a setup-guide correction, or a bounded review trigger. Describe a check whose observable outcome would distinguish the faulty behavior; when safe and authorized demonstrate it against the affected version. Otherwise label the proposed check unverified. Avoid generic reminders to be careful or blanket test/complexity requirements.

## Record a project lesson

Reuse the project's lesson/incident convention and search related entries before adding one. Otherwise use `docs/lessons/README.md` as a small trigger index and `docs/lessons/<date>-<slug>.md` for the record. Respect repository artifact rules; if this default is forbidden, use its approved equivalent rather than silently writing an ignored location. Use [the lesson outline](references/lesson.md). Keep stable identifiers, source links, applicability, evidence confidence, current prevention, and last verification date. Link a repeat incident to its existing lesson and add the new evidence instead of copying the rule.

Capture observed facts, supported conclusions, unresolved hypotheses, and actionable prevention separately. Follow-up repairs belong in the project's Issue tracker under existing authorization; a lesson document is not another task-status authority. Do not claim a proposed guard is implemented. Record links to existing tests/guide/Issues when available, leaving inaccessible evidence explicitly unavailable.

Finish with the leak mechanism, evidence limits, lesson/index paths, and concrete prevention or repair reference. No automatic implementation, upstream Skill rewriting, global memory updates, or publication.
