# Archify

- Type: upstream skill
- Domain: coding
- Source: https://github.com/tt-a1i/archify
- Status: optional; existing local installation, upstream-owned
- Use when: a system, workflow, sequence, data-flow or lifecycle view needs an editable typed source, source links, path exploration or architecture comparison.

## Setup and evidence

For new adoption, use a fixed upstream version and record it in the selected project's setup. [Project-scoped installation policy](README.md#installation-policy)

On 2026-11-24 the existing shared installation moved from v3.2.0 to v3.3.0. The installed package matched the pinned `archify/` tree, `doctor` passed, and the packaged drilldown API sequence passed standard `finalize` with browser checks. The new release uses Apache-2.0. [Source record](sources.lock.json) · [Upstream release](https://github.com/tt-a1i/archify/releases/tag/v3.3.0)

On v3.2.0, a two-participant sequence passed `finalize` and browser checks. The packaged `async-job-roundtrip.sequence.json` exceeded the available height in all six tested viewport and theme combinations. That example was last tested on v3.2.0.

The local sequence trial needed one spacing repair after showcase validation
passed but browser containment failed; the repaired diagram passed all four
desktop viewport checks. Version 2.16's HTML attempted a Google Fonts request
and rendered with fallback fonts when blocked. Offline readability and zero
network requests are separate checks.

Read the installed Skill for the `finalize` command and verify the receipts for the requested output.

## Usage

Keep JSON source with the diagram. Validation checks the authored artifact;
the agent still verifies code facts, and Architecture Delta does not establish
impact or merge safety. Static exports can serve document figures directly.
See [diagram authoring](../workflows/diagram-authoring.md) before adding a second view.
