# Diagram authoring

- Domain: coding
- Status: opt-in; archify retained, diagram-design under bounded trial
- Use when: a technical document or system explanation benefits from a diagram.

## Choose one view

Start with the reader's question and checked facts. Existing simple Mermaid,
text or tables may already answer it. For a technical proposal, use the owning
project's writing workflow; `tech-design-doc`, when available, owns its C4 and
review requirements.

| Need | Starting point |
| --- | --- |
| Editable system/behavior map, source links, paths or snapshot comparison | [archify](../skills/archify.md) |
| ER/schema, an additional visual type, document-sized or branded figure | [diagram-design](../skills/diagram-design.md) |
| Simple linear flow or field definitions | Text, table or existing Mermaid |

One view normally uses one tool. Produce both an explorable map and a summary
figure only when they answer distinct reading needs. Reuse the same verified
facts and record merged, hidden or omitted content; do not silently drop guards,
retry limits, ownership or asynchronous behavior to meet a visual budget.
There is no required conversion pipeline or shared intermediate format.

## Author and deliver

1. Read the chosen installed Skill and record its version/source. Follow that
   version's generation and verification commands; neither a catalog entry nor
   an upstream release upgrades the local package.
2. Choose output size, language and style for the destination. Keep company
   branding, code evidence and resulting diagrams in the owning project or its
   approved artifact location. The client owns the authoring and repair loop.
3. Preserve the editable source: JSON for archify, HTML and the referenced style
   for diagram-design. Keep source and exports together; change the source before
   re-exporting. When exporting for a document, specify the format explicitly.
4. Report artifact checks, browser/export checks and actual visual inspection
   separately. Verify Chinese labels and readability at the intended document
   width. An automated pass does not prove semantic correctness or aesthetics.
5. Embed a format verified with the destination and retain an accessible source
   or interactive-view link. A locally rendered image is not proof of successful
   publication to Feishu or another document host.

## Bounded adoption trial

Use synthetic, clearly labelled inputs: one Chinese request/retry sequence with
both tools, and one ER or database-schema view with diagram-design. Keep equal
facts for the paired sequence. Record versions, inputs, commands, failures and
repair count alongside the trial artifacts; make one semantic edit and recheck.

Accept an optional entry when those examples preserve meaning, remain readable
at document width, export offline with provisioned dependencies, and retain an
editable source. Keep broader adoption pending if it needs silent semantic
cuts or repeated hand-repair. Successful diagrams do not prove installer/native
discovery support: verify each selected machine separately before enabling a
permanent channel. Trial cleanup removes only its owned checkout and artifacts.
