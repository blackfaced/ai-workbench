# Ponytail

- Type: skill collection
- Domain: coding
- Source: https://github.com/DietrichGebert/ponytail
- License: MIT
- Status: optional project pack, review-only profile
- Use when: explicitly reviewing an existing diff for unnecessary complexity and deletion opportunities.

## Notes

The reviewed source is pinned to tag `v4.9.0`, resolved to commit
`0a4dd63ad4541f4f655c4108a295916f3c1d8fda`. AI Workbench exposes only the
upstream `ponytail-review` Skill:

```bash
aiwb setup --repo /path/to/repository --agent-target codex \
  --install-pack ponytail \
  --pack-profile ponytail=review \
  --apply
```

This profile is on-demand detection after implementation. It does not install
the always-on Ponytail doctrine, lifecycle hooks, intensity modes, or Caveman,
and it does not apply its own review findings.
