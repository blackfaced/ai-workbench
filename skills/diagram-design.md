# Diagram Design

- Type: upstream skill
- Domain: coding
- Source: https://github.com/cathrynlavery/diagram-design
- Status: opt-in; fixed-package installation and TraeX project discovery verified on one development machine
- Use when: ER/schema and other additional diagram types, document-sized figures or a project style profile materially improve the explanation.

## Setup and evidence

The accepted source remains Skill 2.6 at commit
`0a8ea20ae69b33a5edce6018eedd3a9d26e90c1c`. The 2026-10-13 isolated
sequence/schema trial is historical authoring evidence only.

On 2026-10-30 the TraeX system `skill-installer` downloaded the fixed revision.
All 283 upstream package files matched the source checkout; the upstream MIT
license was included separately. The intact package was transferred to a stable
user-owned directory on one development machine and backed up under
`~/Documents/skills/diagram-design`. One project-owned `.agents/skills` symlink
activates it. Upstream owns the content; the project owner maintains the link.

TraeX 0.212.1 native `debug prompt-input` showed no entry before installation,
one readable entry after installation and on repeat, and no entry in an
unrelated project. `verified: true` and `clients: ["trae"]` cover this installation
channel and project discovery only. These were no-model probes; a new model
session, other clients/machines, and activation in newly created worktrees were
not tested. Restart the client or open a new session to refresh its skill list.

An English synthetic schema was generated on that development machine. Packaged
offline self-check, upstream repository geometry checks and official SVG export
passed; Mac Chrome visual review passed. The development machine's browser could
not start without `libgbm.so.1`, and Python Playwright was absent, so packaged PNG
export was not run. This is not verification of all diagram types or fonts.
Editable sources, exports and full evidence remain with the
[owning project](https://code.byted.org/hancheng.hc/dev-tracker/issues/414).

For adoption, follow the [project-scoped installation policy](README.md#installation-policy)
with a fixed upstream version and one workspace activation owner, and verify
native discovery in each intended project. Keep one canonical package; aliases
may point to it. AIWB does not vendor the Skill or add it to every machine profile.
This source record does not enable automatic installation or upgrades.

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
