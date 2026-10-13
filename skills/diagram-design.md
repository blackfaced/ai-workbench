# Diagram Design

- Type: upstream skill
- Domain: coding
- Source: https://github.com/cathrynlavery/diagram-design
- Status: opt-in; local sequence/schema authoring trial passed, installation unverified
- Use when: ER/schema and other additional diagram types, document-sized figures or a project style profile materially improve the explanation.

## Setup and evidence

The 2026-10-13 trial uses upstream Skill 2.6 at commit
`0a8ea20ae69b33a5edce6018eedd3a9d26e90c1c` in an isolated checkout.
This is not evidence that a client's installer or discovery works; source records
remain `verified: false` for managed installation.

Both synthetic examples passed packaged offline self-check, repository geometry
checks and local Chrome rendering; SVG and PNG were produced without network
requests. A timeout-label edit passed again. This covers those examples only,
not all visual types, cross-platform fonts or publication to a document host.

For adoption, choose one upstream/client-supported installation owner and verify
native discovery before recording the channel as accepted. Keep one canonical
package; aliases may point to it. AIWB does not vendor the Skill or add it to
every machine profile.

## Usage

Read only the selected type and its required references. Resolve the project's
style profile before authoring; keep project branding and diagram sources with
their owner. For offline output choose system fonts and run the packaged
`self_check.py --offline`; PNG export also needs a provisioned Playwright/browser.
Packaged self-checks and the upstream repository's geometry/render gates cover
different things: report which actually ran.

Keep editable HTML with exports. Prefer a direct figure over redrawing an
existing archify view solely to change tools. See
[diagram authoring](../workflows/diagram-authoring.md).
