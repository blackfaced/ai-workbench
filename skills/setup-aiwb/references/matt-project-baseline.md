# Matt project baseline dependency

`setup-matt-pocock-skills` is a passive project dependency. Its upstream metadata disables model invocation, so resolve and read it as a file; never invoke it through the model Skill registry or by name.

## Required project entry

After resolving the target checkout root, use exactly:

`<project-root>/.agents/skills/setup-matt-pocock-skills/SKILL.md`

The entry may be a complete project-local package or a link to a fixed vendor package, prepared directly by the project owner or by an optional manager. No workspace manager or activation registry is required. Do not search user-global discovery directories or substitute `~/.agents/skills`, `~/.claude/skills`, `~/.trae/skills`, or another checkout when this entry is absent.

## Verify without a manager

Run the bundled [read-only verifier](../scripts/verify_matt_baseline.py), using the exact checkout root as `--project`. Resolve the script relative to this Skill's own directory, not the target project's cwd:

```sh
python3 "$setup_skill_dir/scripts/verify_matt_baseline.py" --project "$project_root"
```

The script contains the fixed upstream repository, commit, source path and Git tree identity. It hashes the actual package's complete tree (names, bytes and executable modes), so it also detects missing resources, edits and extra files. It accepts a copied package or a link to a matching vendor release without a manager-specific receipt. A project link into a user-global discovery directory is rejected even if the bytes match. It does not write files, fetch sources, load client sessions or grant ownership for later updates.

For the current pin, the package contains `SKILL.md`, `agents/openai.yaml`, `domain.md`, `issue-tracker-github.md`, `issue-tracker-gitlab.md`, `issue-tracker-local.md` and `triage-labels.md`. Preserve upstream metadata and relative resources unchanged. A package name or equality with an unverified global copy does not establish identity; a match to the pinned upstream Git tree does. Existing manager records may supplement this check but their absence is not a failure.

## Prepare a missing package directly

If verification reports a missing project entry, continue with ordinary Git rather than asking which manager the owner uses. Resolve `project_root` and the fixed source identity from the verifier. When local dependency writes are authorized:

1. Obtain that commit from the stated upstream repository into a fresh staging checkout, or reuse an explicitly selected checkout containing that object. Confirm `git rev-parse '<commit>:<source-path>'` equals the pinned tree. Do not use an unversioned download or search global Skill copies.
2. Export exactly the package subtree with `git archive '<commit>:<source-path>'`; retain upstream license/attribution beside the vendor checkout or in the project's existing third-party notices, outside the hashed package. Keep the upstream body external to AIWB's maintained sources.
3. Create the project's `.agents/skills` parents only as needed and place the complete package at the exact entry above. Check with `lexists` before writing: an existing directory, file or dangling link is a conflict, not an overwrite target. Preserve managed links and user edits; if an existing owner manages the entry, use that owner's update/recovery procedure instead of taking it over. For a direct first install, retain the fetched commit and record the package path and verification output in the existing setup record. Rollback removes only newly created, still-matching files, never unrelated parents or edits.
4. Run the verifier again from the final project entry, then read that `SKILL.md` and its selected references. On repeat setup, a valid package needs no write, fetch or registry migration. Worktrees must have their own project entry; never substitute the main checkout's entry silently.

With read-only authority, show the missing package and this bounded preparation plan without writing. Network failure, damaged content or an unsupported target remains a concrete dependency gap; only baseline-dependent setup stops. Continue independent guide-only work and keep global installations untouched. Do not create another installer, manifest service or manager-selection step.

## Use the baseline

After a PASS, follow the upstream explore, recommendation, confirmation and update process within the user's existing scope. Reuse maintained tracker/domain choices and project outputs without rewriting them. Record the project entry, resolved package, verified source identity and whether the baseline was reused or updated. Native client discovery and model behavior still require separate evidence; verifier PASS proves the source package only.
