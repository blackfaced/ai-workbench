# Skills

Agent skills and reusable instruction packs.

Skills are lightweight and opt-in: use one only when the owner requests it or a
narrow task clearly needs it. They are suggestions, not a mandatory workflow
framework.

Entries are either upstream packs recorded here for reference, or first-party
skills authored in this repository. Complete upstream workflows stay upstream;
first-party Skills may extend them or synthesize a small local doctrine when one
instruction authority is simpler than overlapping always-on Skills (see
`decisions/0003`).

## Install a first-party Skill

Use `$setup-ai-workbench` for project-local installation. The Agent must first
run the read-only inspection and show the selected Agent target, Skill, and
destination. Only after explicit confirmation may it apply the installation:

```bash
aiwb setup --repo /absolute/path/to/project
aiwb setup --repo /absolute/path/to/project --agent-target codex \
  --install-skill engineering-principles --apply
```

Use `claude-code` instead of `codex` for a Claude Code project. Installation is
complete when the command succeeds and the installed `SKILL.md` matches the
bundled source under `tools/agent-orchestrator/skills/`. Report the exact
project-local path. Do not change user-global Agent configuration or invoke the
installed Skill automatically.

For optional third-party packs, updates, or equivalent-doctrine checks, follow
[`setup-ai-workbench`](../tools/agent-orchestrator/skills/setup-ai-workbench/SKILL.md)
rather than copying a pack by hand.

## Index

- [Anthropic Skills](anthropic-skills.md)
- [mattpocock/skills](matt-pocock-skills.md)
- [andrej-karpathy-skills](andrej-karpathy-skills.md)
- [Ponytail](ponytail.md)
- [Agent Orchestrator Skill](agent-orchestrator.md)
- [engineering-principles](engineering-principles/SKILL.md) - first-party: simple, surgical, verifiable changes with an explicit stopping rule.
- [steelman-grill](steelman-grill/SKILL.md) - first-party: explicit, frontier-batched steelman extension for grilling.
