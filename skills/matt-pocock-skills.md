# mattpocock/skills

- Type: skill collection
- Domain: coding
- Source: https://github.com/mattpocock/skills
- Status: optional project pack
- Use when: adding practical engineering skills for agent workflows, especially grilling, triage, domain modeling, and issue-driven development.

## Notes

Good reference for small, composable skills that keep the user in control of the process.
AI Workbench can install an explicitly selected project-local profile through
`aiwb setup --install-pack matt --pack-profile matt=engineering`; it pins the
reviewed `v1.2.3` release resolved to `6acc160` and installs the dependency
closure of the upstream engineering router, not the full collection. Re-run the same profile with
`--update-pack matt` to replace its managed project copies from the current
reviewed pin. It never runs the interactive upstream setup automatically.
