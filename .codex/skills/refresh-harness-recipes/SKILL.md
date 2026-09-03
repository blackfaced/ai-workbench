---
name: refresh-harness-recipes
version: 1
description: Audit or preview a source-backed public Harness Recipe Catalog refresh without applying upgrades.
---

# Refresh Harness Recipes

Use this Skill only for public Recipe Catalog maintenance. It does not mutate
approved projects or automatically upgrade tools.

## Audit

Run the deterministic bundled Catalog audit:

```bash
aiwb recipes audit
```

To audit one explicit Catalog artifact:

```bash
aiwb recipes audit --catalog /path/to/catalog.yaml
```

Report Recipe versions, official sources, review dates, stale findings,
verification state, and the Catalog digest.

## Refresh preview

Prepare a proposed public Catalog from official sources without including
private repository paths, code, configuration, policy, credentials, or private
Catalog entries. Then run:

```bash
aiwb recipes refresh \
  --proposed /path/to/proposed-public-catalog.yaml \
  --output /path/to/refresh-preview.json
```

The result contains validation evidence, a reviewable version diff, and a
separate tool upgrade plan. It does not mutate the bundled Catalog, any private
Catalog, or approved project configuration. Review and commit accepted Catalog
changes separately.
