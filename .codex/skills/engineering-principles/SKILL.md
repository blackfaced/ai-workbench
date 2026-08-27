---
name: engineering-principles
description: >
  Apply repository-aware engineering principles when implementing, fixing,
  refactoring, or reviewing code: surface consequential assumptions, choose the
  simplest current solution, keep changes surgical, verify observable success,
  and stop when done.
---

# Engineering Principles

Use the least complexity that fully satisfies the current requirement. This is
not a shortest-code contest: clear code may be longer than a clever one-liner.

## Think before coding

Understand the requested outcome and trace the relevant existing flow before
editing. Surface assumptions, ambiguity, and real tradeoffs when they can change
the implementation. Do not turn repository-answerable facts into questions.

## Simplicity first

Descend this ladder and stop at the first rung that fully satisfies the current
requirement:

1. Does this need to exist?
2. Does the repository already solve it?
3. Can the standard library solve it?
4. Can the language, framework, or platform solve it natively?
5. Can an already-installed dependency solve it?
6. Is direct code clearer than introducing an abstraction?
7. Only then write the smallest custom implementation.

The ladder follows understanding; it never replaces reading the real call path.
Fix shared root causes once instead of patching each visible symptom.

### Complexity must earn its existence

Prefer less complexity, not merely fewer lines. Every new abstraction,
dependency, layer, configuration option, fallback, and extension point must map
to a concrete current requirement, test, or constraint.

For each non-trivial addition ask:

- What complexity am I adding?
- Why is it necessary now?
- What current behavior would break if I removed it?

If the last question has no concrete answer, remove the addition.

### Record deliberate compromises

When a deliberately simple implementation has a known ceiling that a future
maintainer cannot infer, leave a nearby `lazy:` comment naming why it is enough:

```text
// lazy: one process owns this cache; revisit only if workers become concurrent
// lazy: linear scan is sufficient below the documented bound -> #123
```

`lazy:` means complete and intentionally limited. It is not `TODO` (unfinished)
or `FIXME` (incorrect). Do not label ordinary simple code, and add an Issue
reference only when there is a concrete trigger worth tracking.

## Make surgical changes

Touch only what the approved change needs. Reuse established patterns and match
the surrounding style. Do not refactor, reformat, rename, or clean adjacent code.
Remove only debris introduced by the current change; report pre-existing or
adjacent improvements separately.

## Execute toward observable success

Translate the request into a checkable outcome. Leave one proportionate,
runnable verification for non-trivial behavior and report what was actually run.
Never trade correctness, clarity, or necessary coverage for a smaller diff.

## Stop when done

Once the requested behavior and verification are complete, stop. Do not add
future-proofing, optional variants, extra helpers, or a framework for possible
later work. A useful adjacent idea belongs in a separate finding or ticket.

Keep necessity review separate from correctness review. When requested, ask
only what code can be deleted or replaced by a lower ladder rung, return a
deletion list, and do not apply the findings automatically.

## Non-negotiable boundaries

Do not simplify away trust-boundary validation, data-loss prevention, security,
accessibility, explicitly requested behavior, an approved expand-contract stage,
or a seam explicitly required by the specification.

## Sources

This is a semantic synthesis, not a textual merge, of the reviewed
[Karpathy guidelines](https://github.com/multica-ai/andrej-karpathy-skills/tree/2c606141936f1eeef17fa3043a72095b4765b9c2)
and the implementation ladder from
[Ponytail v4.9.0](https://github.com/DietrichGebert/ponytail/tree/0a4dd63ad4541f4f655c4108a295916f3c1d8fda).
