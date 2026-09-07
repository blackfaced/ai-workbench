# 0009 - Reproduce Development Environments (illustrative)

> Generic, fictional pattern for restoring a development environment on a new machine. Host names, tool versions, and paths below are illustrative placeholders, not observations of any real system.

## Status

Accepted (illustrative)

- Domain: ops, coding

## Goal

Provide a thin, portable entry point that locates a Python 3 interpreter and applies a minimal, declarative environment profile on a fresh machine. The goal is reproducible setup procedure, not cloning a specific host.

## Principles

- Distinguish "not installed" from "not visible in the current shell"; resolve a tool's effective path before assuming it is missing.
- Prefer one thin bootstrap script delegating to a stdlib-only implementation; do not require a specific package manager to be preinstalled.
- Keep host-specific values in per-host profile files; the shared logic stays generic.
- Use fictional host names and placeholder addresses; never record real serial numbers, internal host-query tools, or session state.

## Layout

    tools/environment/
      bootstrap.sh
      env.py
      profiles/generic-linux.json

## Notes

- This repository bundles no credentials, internal host queries, or session state.
- Environment-specific values belong in a private profile, not in version control.
