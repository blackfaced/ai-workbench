# mattpocock/skills

- Type: skill collection
- Domain: coding
- Source: https://github.com/mattpocock/skills
- Status: optional upstream reference
- Use when: adding practical engineering skills for agent workflows, especially grilling, triage, domain modeling, and issue-driven development.

## Notes

Good reference for small, composable skills that keep the user in control of the process.
Review and select individual Skills, pin their upstream revision and activate only the intended projects/clients, directly or through an optional workspace manager. Follow the [installation policy](README.md#installation-policy); no all-Skills or user-global install is recommended. The environment tool records upstream ownership and does not install this collection. `setup-aiwb` includes a [standalone preparation and verification path](setup-aiwb/references/matt-project-baseline.md) for its selected dependency.

### Selected source handoff

The selected source revision is `5863806dd4e15c63174bee4e7515a4256792ecfa`. It covers `skills/productivity/grilling/` and the engineering packages `to-tickets`, `code-review`, `implement`, `diagnosing-bugs` and `pr`. The final three have the same Git trees as at the previous pin, `49dd158`. Keep each selected package's resources and the upstream license. The revised ticket writer uses the project's tracker instructions to attach child tickets and set blocking relationships.

`setup-matt-pocock-skills` uses the `GLOSSARY.md` and `GLOSSARY-MAP.md` convention at the fixed source revision in the source records. Reuse the project’s tracker, triage labels, and ADR locations when migrating its glossary. [Fixed source records](sources.lock.json) · [Upstream naming change](https://github.com/mattpocock/skills/commit/d80fa0f4ebe0c5714af0adf8670336065233ecc6)

### retro

Use `/retro` in Claude Code or `$retro` in Codex and name the session you want reviewed. It proposes evidence-backed improvements to the agent's working environment for you to select. [Upstream guide](https://www.aihero.dev/skills-retro) · [Optional follow-up in deliver-spec](deliver-spec/SKILL.md#optional-session-retrospective)

### writing-for-agents

Use `/writing-for-agents` in Claude Code or `$writing-for-agents` in Codex when writing or revising a Skill, `AGENTS.md`, or another document agents read. `retro` also calls this Skill for its writing guidance.

For project activation, use the complete packages from the fixed source records. Reuse an existing enabled entry if its package tree matches the pin. Place a missing package under `.claude/skills/<name>/` for Claude Code or `.agents/skills/<name>/` for Codex and verify both entries in the target checkout's Skill picker. [Fixed source records](sources.lock.json) · [Claude Code Skill locations](https://code.claude.com/docs/en/skills)
