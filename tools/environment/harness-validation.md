# Kimi and MiniMax: project loading and worktrees

Domain: coding, ops

This procedure verifies a selected client's actual loading behavior. Active work and
remaining acceptance items belong to [issue #153](https://github.com/blackfaced/ai-workbench/issues/153).

## Prepare the checkout before opening the client

Select the exact repository or worktree root as the client's workspace. Prepare
project Skills from fixed source revisions using the [installation policy](../../skills/README.md#installation-policy),
preserving complete metadata and referenced resources. Global discovery does not
prove a project-local package or its dependencies are available.

Kimi Code 0.41.0 was verified with a project package in `.agents/skills`. MiniMax
Code 3.1.6 was verified with the same entry prepared **before the first session
in a new workspace**. Earlier MiniMax trials that created Skill roots after opening
the workspace did not expose the package, even in another session. Preparing the
package first is the verified procedure; the cause and hot-loading recovery of
those earlier failures remain unverified. Do not restart a client's active sessions
as a diagnostic shortcut.

Both versions loaded the selected workspace's root `AGENTS.md`. Keep team rules
under their existing owner. The installed `setup-aiwb-context` renderer currently
supports Codex and Trae; this observation does not add Kimi or MiniMax private
configuration adapters to it.

## Verify presence and absence

1. Use a disposable worktree from a recorded commit. Preserve the primary checkout's
   status and instruction-file digest. Avoid application databases and deployments.
2. Prepare a uniquely named, valid project Skill before starting the client.
   Append a harmless random marker to the disposable worktree's instructions.
3. Start a fresh client at that exact root. Inspect its native catalog and saved
   startup context. Kimi ACP advertises command names; MiniMax's saved model-call
   context records the injected catalog. Neither alone proves Skill execution.
4. Ask a bounded, read-only model probe to report the already loaded marker and
   Skill names without tools. Keep the marker value out of the user prompt. Compare
   the response with native input and tool-execution records.
5. Run an empty-directory control: global Skills may remain visible, while the
   project marker and project Skill must be absent. Remove the owned probe and
   verify another fresh session no longer receives it.
6. Record client version, source identity, exact workspace, observed and unverified
   results in the local evidence receipt. Publish only a sanitized summary. Restore
   owned fixtures and remove clean temporary worktrees.

An authentication error is a failed probe, not an empty Skill inventory. Repair
login through the client's normal flow and rerun the affected cases. Preserve the
first failure. Keep native worktree creation, untracked configuration provisioning,
Botmux startup and full `setup-aiwb` onboarding as separate acceptance items.
