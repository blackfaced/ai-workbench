# Archify

- Type: upstream skill
- Domain: coding
- Source: https://github.com/tt-a1i/archify
- Status: optional; existing local installation, upstream-owned
- Use when: a system, workflow, sequence, data-flow or lifecycle view needs an editable typed source, source links, path exploration or architecture comparison.

## Setup and evidence

Use the upstream installation channel; AIWB does not copy or update its package.
On 2026-10-13 the work Mac had 2.16.0 from the `skills` CLI, and `doctor` passed.
The installer records a skill-folder hash, not a pinned Git commit; see
[source records](sources.lock.json). This proves local package readiness, not
fresh installation, other-machine availability or diagram quality.

The local sequence trial needed one spacing repair after showcase validation
passed but browser containment failed; the repaired diagram passed all four
desktop viewport checks. Version 2.16's HTML attempted a Google Fonts request
and rendered with fallback fonts when blocked. Offline readability and zero
network requests are separate checks.

Read the installed Skill before running commands. The inspected upstream 3.0
uses `finalize`; local 2.16 uses `validate` / `deliver` and separate visual checks.
Keep upgrades separate from authoring and verify the version's own receipts.

## Usage

Keep JSON source with the diagram. Validation checks the authored artifact;
the agent still verifies code facts, and Architecture Delta does not establish
impact or merge safety. Static exports can serve document figures directly.
See [diagram authoring](../workflows/diagram-authoring.md) before adding a second view.
