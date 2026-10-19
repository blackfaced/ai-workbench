# Matt project baseline dependency

`setup-matt-pocock-skills` is a passive project dependency. Its upstream metadata disables model invocation, so resolve and read it as a file; never invoke it through the model Skill registry or by name.

## Required project entry

After resolving the target checkout root, use exactly:

`<project-root>/.agents/skills/setup-matt-pocock-skills/SKILL.md`

The `.agents/skills` entry is owned by the workspace manager and may be a symlink to its immutable vendor release. Keep the project path as the entry point while inspecting its target and activation record for identity. Do not search user-global discovery directories or substitute `~/.agents/skills`, `~/.claude/skills`, `~/.trae/skills`, or another checkout when this entry is absent.

Require these files beside that entry before using it:

- `SKILL.md`
- `agents/openai.yaml`
- `domain.md`
- `issue-tracker-github.md`
- `issue-tracker-gitlab.md`
- `issue-tracker-local.md`
- `triage-labels.md`

## Source identity

The activated package must identify this source:

- Repository: `https://github.com/mattpocock/skills`
- Commit: `5c89081d4bbeb3d039a42093653f90bb698d780e`
- Source path: `skills/engineering/setup-matt-pocock-skills`
- Git tree: `ec07f82df54064d01aa1648670e81da41e2cbdc2`

Verify identity using the workspace manager's project activation record or immutable vendor target. Equal file contents, a matching directory name, or a user-global installation do not establish the package identity. If the project entry, a required resource, or identity evidence is absent or mismatched, report the baseline dependency as blocked and stop only baseline-dependent setup. Do not fall back to a global copy.

Read the validated `SKILL.md` and the resources it selects, then follow its explore, recommendation, confirmation and update process. When its maintained project outputs already match the repository and the tracker/domain decisions are unchanged, reuse those outputs without rewriting them. Record the project entry, verified source identity and whether the baseline was reused or updated in the setup result.
