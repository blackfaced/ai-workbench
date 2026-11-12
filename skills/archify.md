# Archify

- Type: upstream skill
- Domain: coding
- Source: https://github.com/tt-a1i/archify
- Status: optional; existing local installation, upstream-owned
- Use when: a system, workflow, sequence, data-flow or lifecycle view needs an editable typed source, source links, path exploration or architecture comparison.

## Setup and evidence

For new adoption, follow the [project-scoped installation policy](README.md#installation-policy) with a fixed upstream version and a project setup record, optionally maintained by a workspace manager; AIWB does not copy or update its package.
On 2026-11-12 the existing installation moved from 2.16.0 to v3.2.0 at commit `208acba8d412335185b2056fedf54b3405df43fb`. Its installed directory matched the upstream `archify/` Git tree and its `doctor` passed. The package identity is in the [source records](sources.lock.json).

The standard `finalize sequence` command passed validation, delivery, artifact and browser checks on a two-participant example. The packaged `async-job-roundtrip.sequence.json` exceeded the available height in all six tested viewport/theme combinations.

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
