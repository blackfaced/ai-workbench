# andrej-karpathy-skills

- Type: skill collection
- Domain: coding
- Source: https://github.com/multica-ai/andrej-karpathy-skills
- Status: reviewed source incorporated into first-party doctrine
- Use when: auditing the provenance or refreshing `engineering-principles`.

## Notes

The reviewed `karpathy-guidelines` source is pinned to commit
`2c606141936f1eeef17fa3043a72095b4765b9c2`. AI Workbench no longer installs
it as a separate project pack. Its durable ideas are semantically incorporated
into the first-party `engineering-principles` Skill alongside the minimal
implementation ladder.

```bash
aiwb setup --repo /path/to/repository --agent-target codex \
  --install-skill engineering-principles \
  --apply
```

Skip installation when `AGENTS.md` or another Development Doctrine already
provides equivalent rules. Project instructions remain authoritative when they
overlap.
