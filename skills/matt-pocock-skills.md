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

The selected `code-review`, `implement`, `diagnosing-bugs` and `pr` source revision is `49dd158d1076134a641b33efb035946536778336` in `mattpocock/skills`. Each is under `skills/engineering/<name>/`; retain its resources, metadata and attribution from that same commit. `setup-matt-pocock-skills` is independently pinned to `5c89081d4bbeb3d039a42093653f90bb698d780e` at `skills/engineering/setup-matt-pocock-skills/`; `setup-aiwb` composes with it for issue-tracker, triage and Domain Docs baseline setup without copying or maintaining its templates. These are fixed source references, not evidence that the Skills are activated or behavior-verified in any target project. Other Skills in the collection are not implicitly selected.

- [retro](https://www.aihero.dev/skills-retro) — explicitly review a difficult session and propose evidence-backed improvements to the agent's working environment. Optional follow-up for [deliver-spec](../skills/deliver-spec/SKILL.md#optional-session-retrospective); candidates wait for user selection and are not an acceptance gate. If selected, pin and activate `retro` for the target project through the project's chosen activation method; it is not installed by default.
