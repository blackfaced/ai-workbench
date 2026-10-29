# MemoryNexus task memory

- Type: upstream Skill and local CLI integration
- Domain: coding
- Source: [blackfaced/MemoryNexus](https://github.com/blackfaced/MemoryNexus)
- Canonical path: `integrations/task-memory/memorynexus-task-memory/`
- License: MIT (`LICENSE` in the selected source)
- Status: opt-in source handoff; fixed revision and joint client acceptance pending
- Use when: a project owner wants Codex/Traex to read, remember, correct and close out an **existing** task through one explicit binding and a short intent.

## Source and ownership

Follow the [project activation policy](README.md#installation-policy). Ordinary projects do not enable this entry by default. [Source records](sources.lock.json) deliberately keep `revision: unpinned`, `verified: false` and no verified clients: the inspected #343 implementation is an uncommitted candidate, not a fixed source delivery. Its base commit does not contain the new package. Do not activate that candidate as its base SHA or present a local test snapshot as an upstream release.

| Owner | Files and responsibility |
| --- | --- |
| MemoryNexus version installer | CLI binary, complete script package, canonical Skill and relative resources; immutable version identities and installation manifest. AIWB references this package without copying the helper or Skill body. |
| Project's existing activation owner | Only the selected client discovery entries and their version references, with ownership/digest checks and recoverable backups. AIWB supplies the handoff convention; no new manager is required. |
| Target project | Existing task config, private binding/ledger and pending requests, reports, code/tests, handoff records and authoritative Issue status. Keep these outside AIWB; private memory/transport files stay outside Git. |

Before activation, record the full delivered source SHA and canonical path, MIT attribution, exhaustive resource inventory, installed package digest, binary build source SHA and binary digest separately. Retain the exact Python path/identity required by the upstream preflight. Record installed client versions with each observation, not a blanket “supported” label. A source-script digest is not the installed-package digest; obtain the latter from the upstream installation manifest.

The upstream `integrations/task-memory/install.py` selects the complete `scripts/` package and preserves document paths below `VERSION/package`. Keep canonical `references/`, shared `PROTOCOL.md`, bootstrap/repository-review companions, Codex/MiniMax entries, onboarding/current-knowledge contracts and `LICENSE` from the same source. Follow the selected source's resource manifest and verify relative references in the **installed** tree; copying or linking `SKILL.md` alone is insufficient. The upstream `references/daily-interface.md` owns exact helper invocation and `references/acceptance.md` owns its implementation evidence. An upstream test report is not project discovery or behavior evidence.

## Project entry and daily use

Use the owner's selected project root and existing native discovery entry. Preserve its rules and any same-name non-managed package; conflicts or user edits stop the update. Show the candidate package, entry paths, owner and recovery plan before activation. Retain existing global installations unchanged.

The effective project context should point to the selected canonical Skill and the **existing** private binding, with a short intent such as “接上这个任务，入口 `<binding>`”. It should also identify the approved report location and how its owner can access reports. Do not embed corrected answers or a copy of remembered task content in a handoff prompt. The client reads the upstream rules and context, verifies task identity, effective record IDs and omissions, and stops history-dependent work on failed or incomplete loading. Missing binding is not permission to initialize a substitute task.

Use the upstream content-level authorization and exact-target rules for corrections; a generic request to use memory does not supply confirmation. Keep current owner instructions distinct from historical checkpoints, development self-reports, self-tests and independent acceptance. Record a rejection with its source/evidence, repair, then independently recheck; a newer checkpoint does not turn a rejection into a pass. At handoff, make the current workspace writer explicit. At closeout, save and read back the checkpoint, link the project-owned report, confirm access and list uncommitted, unpublished and unverified work.

This entry does not require `deliver-spec` or a full multi-agent workflow. Reuse the [single-Issue route](../workflows/single-issue-trial.md), [self-test report](self-test-report/SKILL.md) and existing [run-record outline](deliver-spec/references/run-record.md) when applicable. MemoryNexus remains the task-memory authority; Issues remain the work-status authority.

## Version changes and recovery

Use the existing package/activation owners. A version switch or rollback changes only owned discovery entries and package references after verifying current ownership and user edits, with a recoverable backup. Check the selected package and its relative resource closure again. Keep the same task/config/ledger binding; ledger/profile migration or rebinding requires separate explicit authorization. Configuration rollback does not establish data downgrade. Preserve a pending write's pinned package and original bytes under the upstream retry contract rather than repinning it during an upgrade.

## Acceptance in the selected project

Record each stage separately in the project's existing acceptance record. Until an observed result exists, keep it unverified; no model self-report, directory presence or exit 0 substitutes for actual discovery/readback.

| Stage | Required observation |
| --- | --- |
| Acquisition and installation | Full source SHA, installed resource closure, package/binary identities and installer verification. In an isolated project, check fixed-version selection, unmanaged same-name conflict, user-edit protection and managed rollback without moving the ledger. |
| Native discovery | Codex **desktop App** and Traex each expose the canonical project entry; record exact client version, project root and discovered source. CLI discovery alone does not prove App discovery. |
| Actual invocation | Give only task entry and short intent; observe rule/context reads and correct task/record provenance. Classify prompt-only, wrapper and hook guarantees by what ran. |
| Same-machine roundtrip | Codex writes; Traex reads and precisely corrects under content-level authorization; the **original Codex desktop chat's next turn** explicitly rereads. Do not paste the corrected answer into its handoff. |
| Sessions and failures | Verify new session, new worktree and original conversation separately. Failed or truncated reads stay visibly unloaded/unsynchronized; the fresh-session bridge does not prove old-chat continuation. |
| Independent acceptance | Preserve attributed self-test, independent rejection, repair and independent recheck, each bound to its Attempt candidate/test/fixture/command/result/log. Never overwrite failed-run evidence. |
| Coordination | Count prompt pastes, missing-context requests, repeated confirmations and failure recovery, with observation window, time and unknowns; link the sanitized findings to [#107](https://github.com/blackfaced/ai-workbench/issues/107). Without a comparable baseline, cost reduction remains unassessed. |

[AIWB #155](https://github.com/blackfaced/ai-workbench/issues/155) and [MemoryNexus #343](https://github.com/blackfaced/MemoryNexus/issues/343) retain the joint gates. Do not close them on source/docs checks alone. Report maintenance, fresh installation and inaccessible-machine coverage separately. Experience lifecycle, cross-machine transport and Lens upgrades remain separate scope; this entry creates no scheduler, agent loop or second memory store.
