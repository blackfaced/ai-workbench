# 0012 — Home Mac maintenance and explicit Profile selection

- Status: Accepted
- Date: 2026-09-12
- Domain: ops
- Extends: [0010](0010-environment-first-repository-scope.md)

The owner identified the active machine as the home Mac mini and requested local synchronization, retired-issue cleanup and home-machine validation. The home Mac is now accessible; the earlier deferral no longer describes this machine.

Add a separate `home-mac` Profile based on observed ownership. Preserve Homebrew cask Codex, app-bundled Codex, nvm Node, Homebrew Python/GitHub CLI and Kimi's binaries. Do not copy work-machine installer assumptions. First-party Skills use the existing shared-directory installer and recoverable file ownership rules.

When multiple macOS Profiles exist and no same-OS hostname mapping identifies one, require explicit `--profile`. The operating system alone cannot distinguish home and work. Existing Linux hostname selection and single-Mac-profile behavior remain supported.

Verification is bounded to existing-machine maintenance, installation idempotence, restore preview and native Skill discovery. Fresh installation, package upgrades, remote machines and model-driven workflow behavior are separate coverage. See the [validation record](../tools/environment/home-mac-validation.md).

Machine-level legacy cleanup is recoverable: preserve the old virtual environment, draft configuration, installation metadata and broken Skill aliases locally. Do not copy runtime data or client configuration into Git.
