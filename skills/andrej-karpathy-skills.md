# andrej-karpathy-skills

- Type: skill collection
- Domain: coding
- Source: https://github.com/multica-ai/andrej-karpathy-skills
- Status: optional project pack
- Use when: a repository lacks equivalent guidance for explicit assumptions, simple designs, surgical changes, and verifiable goals.

## Notes

The reviewed pack exposes only `karpathy-guidelines`, pinned to commit
`2c606141936f1eeef17fa3043a72095b4765b9c2`:

```bash
aiwb setup --repo /path/to/repository --agent-target codex \
  --install-pack karpathy \
  --pack-profile karpathy=guidelines \
  --apply
```

Do not also append its `CLAUDE.md` to a repository that already carries the
same rules in `AGENTS.md` or another Development Doctrine. The Skill stays
optional; project instructions remain authoritative when they overlap.
