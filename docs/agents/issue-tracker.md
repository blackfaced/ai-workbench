# Issue tracker: GitHub

Issues and PRDs for this repository live in GitHub repository `blackfaced/ai-workbench`.
Use the `gh` CLI for issue operations from within this checkout.

GitHub Issues are the sole active source of truth for AIWB project items and their status. Local files are not a second status authority: `todo/` retains personal evaluations and conditional reminders as historical notes, while `docs/testing/` artifacts are evidence only. Do not copy or reconcile project state into either location.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- When splitting an existing spec, attach each ticket with `gh issue create --parent <spec-number>`. Use `--blocked-by <ticket-number>` for an actual dependency. For an existing ticket, use `gh issue edit <spec-number> --add-sub-issue <ticket-number>`.
- Read an issue and its discussion with `gh issue view <number> --comments`.
- List issues with `gh issue list`, adding state and label filters when needed.
- Add or remove labels with `gh issue edit <number> --add-label "..."` and `--remove-label "..."`.
- Close an issue only when the requested workflow explicitly calls for it.

## Acceptance examples in specs and tickets

- When writing a spec, preserve the examples the user confirmed during grilling. Keep the concrete input or sequence of actions together with the expected observable result. Reference an existing case or fixture if it already captures the example. Mark any examples still awaiting a decision as open questions.
- When splitting the spec into tickets, reference the relevant spec example beside each acceptance criterion it illustrates, using an existing case ID or a link to the spec section. If the result can only be observed after several tickets are integrated, keep the example in the parent spec's final acceptance criteria and identify the tickets it spans.

## Pull requests as a triage surface

External pull requests are **not** a triage request surface. Triage applies to GitHub Issues only.

## Skill interpretation

When an engineering skill says to publish to the issue tracker, create a GitHub issue in this repository. When it says to fetch a ticket, run `gh issue view <number> --comments`.
