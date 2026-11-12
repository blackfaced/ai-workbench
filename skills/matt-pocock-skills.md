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

`setup-matt-pocock-skills` has its own pin at `5c89081d4bbeb3d039a42093653f90bb698d780e`. Its existing project verifier and this repository's `CONTEXT.md` convention remain the basis for setup. Project activation and client behavior are verified separately for each selected package.

- [retro](https://www.aihero.dev/skills-retro) — explicitly review a difficult session and propose evidence-backed improvements to the agent's working environment. Optional follow-up for [deliver-spec](../skills/deliver-spec/SKILL.md#optional-session-retrospective); candidates wait for user selection and are not an acceptance gate. If selected, pin and activate `retro` for the target project through the project's chosen activation method; it is not installed by default.
