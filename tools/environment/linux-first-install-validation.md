# Linux first-install channels — isolated validation

- Date: 2026-09-23
- Scope: disposable Debian 12 x86-64 containers on an existing Linux host. The final Profile
  smoke test mounted only the public Profile JSON and a test driver read-only;
  it installed into the container's empty home and used `docker run --rm`.
  No account sign-in, model request, or existing host installation was changed.
- Prerequisites: Python 3.11, Bash, `curl`, `tar`, `sha256sum`, an x86-64 Linux
  host, and access to the official release endpoints. The Docker daemon had an
  HTTP(S) proxy, but neither the host shell nor new containers inherited it.
  Direct release requests timed out; explicitly passing `HTTP_PROXY` and
  `HTTPS_PROXY` into the container made the official endpoints reachable.
  A missing or unreachable proxy remains an explicit install failure.

| Tool | Empty-container result | Profile channel |
| --- | --- | --- |
| Codex CLI | The [official standalone installer](https://learn.chatgpt.com/docs/codex/cli) installed `codex-cli 0.156.1` at `~/.local/bin/codex`. | Use the official installer non-interactively only when missing. It writes a standalone package under `~/.codex/packages` and edits the shell profile; existing standalone installs retain `codex update`. |
| uv | The [official pinned installer](https://docs.astral.sh/uv/getting-started/installation/) installed `uv` and `uvx` 0.12.18 at `~/.local/bin`. | Use the pinned standalone channel only when missing. Existing pipx and standalone installs keep their respective update paths. |
| ripgrep | The [upstream x86-64 musl release](https://github.com/BurntSushi/ripgrep/releases/tag/15.2.0) passed its published SHA-256 check and installed `ripgrep 15.2.0` at `~/.local/bin/rg`. | Use this release only when missing and on x86-64. Existing files supplied by another installer are left alone. |

The final smoke test executed each `work-linux.json` `install_cmd` unchanged,
then resolved its installed executable and checked its reported identity and
version. The environment regression suite covers a missing tool, a failing
installer, and an installer that produces the wrong identity; `apply` must not
record those failures as success. The ripgrep command deletes its temporary
download directory on exit. Container deletion cleaned all three installed
tools after validation. On a real host, the installed tools and the Codex
installer's shell-profile edit persist; this record does not claim a verified
uninstall or full rollback for them.

This is **isolated first-install-channel validation**, not a complete fresh
Linux machine bootstrap. Full Profile `apply` + `check`, account setup, and
model-driven behavior on a new host remain unverified. An unsupported CPU,
failed checksum, inaccessible release endpoint, or bad installed identity must
remain a visible failure; there is no silent alternate channel.
