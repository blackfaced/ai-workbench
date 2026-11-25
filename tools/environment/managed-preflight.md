# Managed configuration preflight

Domain: coding, ops

Use `managed_preflight.py` before asking for credentials or identifiers already
owned by a project's managed configuration. The project chooses explicit source
paths and required fields. The helper reads those sources in its current process,
reports field presence, and makes no network calls or configuration changes.

## Run in the task's execution environment

Run from the actual worker environment. A successful check on another machine
does not prove that the worker can read the same file, mount or environment variable.
Choose sources from project instructions and existing provider configuration;
the helper does not search home directories. Relative paths are resolved against
the profile file, and explicit compatibility symlinks may identify a managed file.

Create a private profile outside Git. This neutral example selects a single source:

```json
{
  "version": 1,
  "sources": [{
    "id": "service",
    "type": "json",
    "path": "credentials.json",
    "fields": [
      {"name": "key-id", "keys": ["profiles", "test", "key_id"]},
      {"name": "secret", "keys": ["profiles", "test", "access_token"], "secret": true}
    ],
    "recovery": "unverified"
  }]
}
```

```sh
python3 -B tools/environment/managed_preflight.py --profile /private/preflight.json
```

For `type: environment`, omit `path` and give each field exactly one key, such as
`["EXAMPLE_SERVICE_TOKEN"]`. Only the current process environment is checked.
Field names and paths come from the profile; values and parser errors are never
returned. Keep secrets out of profile labels, command arguments and evidence names.
JSON paths select object keys; array-index traversal is not supported. Use `-B`
to suppress interpreter bytecode caches as well as the helper's own zero-write behavior.

## Interpret evidence and decide whether to ask

| Status | Meaning | Next step |
| --- | --- | --- |
| present | Every selected field has a nonempty value | Use the existing authorized consumer; authentication remains unverified |
| missing | The selected file or a required field is absent or empty | Discover identifiers through the existing owner; inspect secret recovery separately |
| unverified | Read denied, invalid JSON, unsupported file or unreadable profile | Resolve that evidence gap before asking for credentials |

The helper opens only regular files and bounds each JSON read to 1 MiB. Presence
does not establish type correctness, account ownership, permissions, connectivity
or usable authentication. A masked value returned by a list API is not a usable
secret. Obtain a usable secret only through the existing authorized provider; do
not create credentials or widen permissions as a preflight shortcut. Derive
storage locations from authorized project configuration or existing resource
records before asking the user for addresses.

`recovery` is an explicit owner-supplied observation: `available`, `unavailable` or
`unverified`. A missing secret yields `use_managed_recovery`, `ask_user` or
`resolve_evidence` respectively. Missing identifiers yield `discover_identifiers`.
Collect the `question_sources` into one question after all applicable sources have
been checked. State the checked scope and missing facts; prefer secure provider
setup rather than asking the user to paste values into chat. This command does
not send a question or execute a recovery procedure.

If an authorized authentication check already returned invalid credentials, the
profile may supply `authentication: invalid` and a private
`authentication_evidence_ref`. `valid` also requires such a reference. These are
owner observations, reported as `supplied_authentication`; the helper neither
reads that reference nor verifies authentication. Unknown is the default. File
absence or parse failure never becomes an authentication failure.

Exit 0 means all selected fields are present and no recovery/question action is
pending. Exit 2 includes missing/unverified input and pending recovery. It never
means that a business request or end-to-end test passed.

## Keep native skill discovery separate

Use the client's existing discovery path and the
[native loading procedure](harness-validation.md#verify-presence-and-absence).
Installed files, registry entries, optional injection settings and agent prose
are separate observations. None alone proves a skill appeared in the native
catalog or was used by a particular running session.

For a required skill, retain the client/version, canonical source, actual cwd,
session/attempt, observation time and original native catalog reference. Check
the current input and first activity when accepting a running task. Missing skill
evidence stays unverified or refuses that task; a fresh-session probe cannot fill
in an older session's state. The credential helper always reports
`native_session_verified: false` and does not implement another client adapter.

Keep project paths, provider recovery commands, storage record lookups and test
accounts in their owning project. Project guides link here and add only their
specific source and recovery facts.
