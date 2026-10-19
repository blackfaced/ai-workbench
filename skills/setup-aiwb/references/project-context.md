# Project context setup

Keep a project understandable from its own directory while preserving the team's instructions and the owner's private preferences. Configure the client's native loader; do not add a second agent loop or a hook that repeats the entire policy on every prompt.

## Discover the project boundary

Resolve the actual repository root, current worktree, working directory and source revision. Inspect applicable parent/project instructions, existing native client configuration, local exclusion rules and the launch path before choosing files. Identify which content belongs to the team, this owner, another integration, or a previous managed setup. Report conflicting rules and their loading scope; moving a file alone does not resolve precedence.

The resulting context should reuse the maintained engineering baseline produced by upstream `setup-matt-pocock-skills`: authoritative tracker, applicable triage vocabulary, Domain Docs layout, and its project instruction pointers. Treat `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md` when present, `docs/agents/domain.md`, and the selected `CONTEXT.md` or `CONTEXT-MAP.md` layout as project-owned sources rather than recreating them. Add commit/MR conventions, relevant skills and links to maintained test/run/deploy documentation only where the target project requires them. Include only what this project needs. Discover unresolved facts from the project and its owner; do not copy another project's platform, business, account or machine details. Business knowledge and run evidence stay in the owning project's approved locations.

When adopting a reusable instruction pack, select the applicable rules from its authoritative source and record its revision and owner with the project setup. Preserve the source's maintenance boundary: project-specific choices remain project-owned, and generated content retains its source reference. Do not turn a selected pack or project convention into a new global default.

For runtime code, analyze and maintain [project error and observability conventions](error-observability.md) before finalizing its context: identify verified error adapters, diagnostic/measurement reuse points, consumer behavior and regression methods. Put a conditional pointer to the project-owned result in the effective context. For a configuration-only repair, reuse still-valid analysis or record why it is unaffected; do not perform unrelated code cleanup.

## Choose a native entry point

| Situation | Entry point |
| --- | --- |
| Personal repository whose shared instructions the owner wants to maintain | Its existing root `AGENTS.md`, with a small owned section or existing project convention. Preserve unrelated content. |
| Team repository requiring additional private instructions | The client's supported project-local additive instructions setting, leaving team `AGENTS.md` intact. Verify support and effective loading for the installed version. |
| Existing project-local configuration with instructions | Preserve the existing field and add only an identifiable owned section within it. Resolve conflicts rather than adding a duplicate TOML key or overwriting another owner's text. |

For Codex, the native project file is `.codex/config.toml`; for TraeX versions supporting it, it is `.trae/traecli.toml`. The additive field is a **top-level** `developer_instructions` string. Keep it before TOML table headers or use a structure-aware editor so it does not accidentally become a field of a preceding table. A TOML multiline literal string is convenient only when its content does not contain the terminating delimiter; validate the resulting TOML with an available parser.

These paths and semantics must be checked against the installed client. In verified Codex/TraeX versions, root `AGENTS.md` and project `developer_instructions` both reach the prompt for a trusted repository. This demonstrates loading, not permission to override team rules. Existing global `developer_instructions` can be replaced by the project config layer; inspect and preserve any still-applicable content rather than assuming string values automatically concatenate across config files.

`AGENTS.override.md` replaces `AGENTS.md` at the same directory level; it is unsuitable as an additive private file. `.agents/private/` has no automatic loading contract. Do not use `model_instructions_file` as an additive layer or fallback filenames as a way to load two instruction files. If the installed client cannot load a private additive configuration, report that client as unverified and choose an explicitly authorized native alternative; do not silently switch to global injection.

Project config can require a persistent trusted-project entry. Inspect the effective trust state without exposing unrelated secrets. Do not mark a parent directory, unrelated repository or all projects trusted. If this exact repository is not already trusted, show the exact root and trust change in the setup plan and use the client's supported trust flow only within the user's authorization. A command-line trust override may not enable loading project configuration; verify the persistent setting with the real loader.

## Apply without taking over team files

Before editing, record the current file type, target, owner and digest, and save a recoverable copy of every affected file. If an existing managed section has changed since the recorded setup, preserve the user edits and reconcile them visibly. Never follow a symlink and overwrite a different owner's target by accident.

For private context, use the repository's existing local exclusion convention or its local Git exclude file. Exclude only the new private files; do not add a blanket directory exclusion that conceals unrelated tracked configuration. Check `git status` and `git check-ignore` for the exact paths. Ignoring a file does not remove a tracked file from Git, so an already tracked native config needs an explicit ownership decision before adding private content. Keep credentials out of instruction text and setup evidence.

Update only the owned instruction section and necessary local exclusion entries. Preserve unrelated native configuration, hooks and trust records. Record the source, affected paths, hashes and restoration steps in the project's existing private setup record; use a small record beside the native config if none exists. This record is for configuration recovery, not a second task tracker. Repeating setup with unchanged inputs should produce no diff.

## Provision worktrees before starting clients

Untracked project configuration does not follow `git worktree add`. Prepare each new worktree explicitly through the existing worktree setup path before opening its client. Tracked project guidance follows its selected revision; private native config must be copied or linked from the chosen project-owned source. A link is appropriate only when that shared configuration applies unchanged to both worktrees and its target has a stable lifetime. A copy needs a recorded source revision/hash and refresh procedure. Neither choice permits replacing existing worktree configuration or changing files in active sessions without checking ownership.

Use the destination's real path when verifying context and trust. Validate a newly created worktree independently; do not infer that trust or configuration discovered in the main checkout will be inherited. Document the necessary provisioning step in the project's existing launch/worktree guidance. Other machines need their own authorized provisioning and verification; a local absolute symlink is not a portable setup.

For Botmux, retain role identity and transport configuration while taking engineering instructions from the target project. Inspect installed `botmux --help` and the relevant subcommand. Create the session with the prepared project/worktree as its working directory **before** the native client starts. A later prompt telling an already-started session to `cd` does not reload startup instructions. In versions exposing it, `session start --headless --bot ... --working-dir ... --prompt-file ... --json` supplies that directory; inspect the actual session metadata afterward. Do not assume `dispatch --bot-app` accepts `--repo`. Read the existing Botmux workflow when changing a project's normal launch path; avoid duplicating its orchestration in setup or roles.

For explicitly authorized direct terminal startup, follow [direct terminal startup](botmux-startup.md#direct-terminal-startup), reusing the same preparation logic and verifying the installed CLI argument contract. Preserve native installer entries and record which shell entry actually resolves the wrappers.

For an explicitly authorized automatic Botmux startup, follow the [local startup gate](botmux-startup.md). Register project sources and verified runtime scope, preserve existing bot settings, and run provisioning plus native loading checks synchronously before client exec. Async `session.start` hooks cannot establish this order. Missing or altered pinned configuration/rule sources and failed native loading block startup. Branch-sensitive analysis differences are recorded in the existing startup receipt and warn without blocking; inspect the current checkout before adopting those findings.

## Verify the effective context

Prefer the client's no-model prompt inspection when available: from the exact target directory, inspect `codex debug prompt-input` or `traex debug prompt-input` after checking that version's help. Use distinct harmless markers for team and private instructions in an isolated fixture or run-owned section, and verify both in the rendered input. Never print complete prompt/config dumps that can expose private instructions or credentials. Retain only necessary sanitized evidence.

Exercise the entry paths actually used by the project:

| Entry | Required observation |
| --- | --- |
| Direct startup | Exact cwd/client version; applicable team guidance and selected project context both present. |
| New worktree | Fresh worktree provisioned; loader observes its team guidance and private context from the recorded source. |
| Botmux, when used | Actual native-session cwd and selected client/identity; effective project instructions loaded before its first task. A successful session creation alone is insufficient. |

Check absence as well as presence: use an unrelated project to verify the private marker is not injected there. In an isolated fixture, omit the private worktree file and verify the loader does not falsely report it loaded. Repeat setup and confirm no duplicate instruction section, hook or exclusion entry. Use native evidence or persisted model input for Botmux; if unavailable, mark startup loading unverified rather than accepting the agent's self-report. Starting a paid/model-backed probe or sending a message must stay within the user's authorization; never send a group message merely to test loading.

If a migration also authorizes retirement of global rules, complete the project checks first, back up the old global state, then invoke the owning distributor's retirement path. Remove only proven owned entries, preserve third-party hooks/trust data even if they sit inside an old marker span, and prevent the source distributor from reinstalling the retired policy. Rerun context checks after removal. Existing sessions may retain old instructions; report their state and validate fresh sessions without interrupting active work.

Finish with the effective file paths, source versions, worktree provisioning command or maintained entry point, backup location, and pass/unverified results for each used client and startup path. Separate fresh installation, maintenance, and inaccessible-machine coverage.
