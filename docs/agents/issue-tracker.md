# Issue tracker: GitHub

Issues and PRDs for this repository live in GitHub repository `blackfaced/ai-workbench`.
Use the `gh` CLI for issue operations from within this checkout.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- Read an issue and its discussion with `gh issue view <number> --comments`.
- List issues with `gh issue list`, adding state and label filters when needed.
- Add or remove labels with `gh issue edit <number> --add-label "..."` and `--remove-label "..."`.
- Close an issue only when the requested workflow explicitly calls for it.

## Pull requests as a triage surface

External pull requests are **not** a triage request surface. Triage applies to GitHub Issues only.

## Skill interpretation

When an engineering skill says to publish to the issue tracker, create a GitHub issue in this repository. When it says to fetch a ticket, run `gh issue view <number> --comments`.
