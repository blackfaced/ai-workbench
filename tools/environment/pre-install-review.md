# Review an unfamiliar installer or MCP server

Use this short check before an optional installation. Record the answers beside
the task or Issue; it does not add an approval gate or change client permissions.

1. **Source and version:** identify the publisher, exact download URL, version
   or digest, and any redirects. Inspect a downloaded script or release metadata
   before execution. An unpinned `latest` URL needs a fresh check each time.
2. **Access:** identify filesystem writes, network destinations, and requested
   credentials. For an MCP server, also inspect the tools it exposes and the
   client permissions it will inherit.
3. **Ownership:** identify the installer that will own the executable and its
   update channel. Avoid silently replacing a binary managed by another tool.
4. **Persistence:** check for shell profile edits, hooks, MCP registrations,
   launch agents or services, and background processes.
5. **Removal:** identify the uninstall command and any data that it leaves
   behind. Back up user-owned configuration before changing it.

Read-only example (checked in a disposable Debian container on 2026-09-23):
the [official uv installer](https://docs.astral.sh/uv/getting-started/installation/)
resolved to `releases.astral.sh`. The downloaded script was 71,308 bytes and
named release `0.12.18`; inspection found `UV_INSTALL_DIR`,
`--no-modify-path`, and release downloads via `releases.astral.sh` or GitHub.
Only the script was downloaded and inspected; it was not executed in this
example. Before a real install, choose an isolated `UV_INSTALL_DIR`, decide
whether PATH changes are wanted, and check the version and download again.
