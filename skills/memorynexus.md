# MemoryNexus task memory

- Type: upstream Skill and local CLI integration
- Domain: coding
- Source: [blackfaced/MemoryNexus](https://github.com/blackfaced/MemoryNexus)
- Canonical path: `integrations/task-memory/memorynexus-task-memory/`
- License: MIT (`LICENSE` in the selected source)
- Source revision: `e3a6e863ed650f42bf05c8af2b633bbaee9a8efa` (upstream main)
- Status: opt-in versioned package installed and verified on 2026-11-12. The isolated-project client results below apply to the earlier package.
- Use when: a project owner wants Codex/Traex to read, remember, correct and close out an **existing** task through one explicit binding and a short intent.

## Source and ownership

Follow the [project activation policy](README.md#installation-policy). The upstream installer created a separate versioned runtime from the [pinned main commit](https://github.com/blackfaced/MemoryNexus/commit/e3a6e863ed650f42bf05c8af2b633bbaee9a8efa), reusing the previously verified CLI binary. The installed launcher's `verify` command confirmed the source, interpreter, binary and package manifest. Existing task bindings continue to identify their original runtime. The CLI build source remains `9ceb4608fcf896bcf789e3fb26272965bbe73bbd`.

The earlier package came from commit `71f2d7e04a639fef728adb9ecbd2335179d66065` in [merged PR #348](https://github.com/blackfaced/MemoryNexus/pull/348). New client acceptance is tracked independently of those historical results in the [source records](sources.lock.json).

The [#155 acceptance record](https://github.com/blackfaced/ai-workbench/issues/155) covers one owner-selected isolated synthetic project on 2026-10-29. The owner confirmed the canonical source in the Codex Desktop Skill selector; actual execution was explicit and prompt-only. Traex performed the authorized correction, and the original Desktop conversation reread it on the next user turn. Observed runtimes were Desktop-bundled `codex-cli 0.165.0-alpha.1.2` and Traex `0.212.1`; the subsequently inspected installed Desktop App was `26.1023.51421` (build `22530`), not a version attestation for every earlier Attempt.

Reports remain with the owning project and its persistent local artifact location. Earlier failed runs and missing execution-time identities remain historical evidence limits, not retrospectively complete Attempt records. Maintenance and isolated fresh-install checks were observed on this machine; other-machine coverage was not performed. No comparable cost baseline exists, and no automatic hook or universal acceptance is claimed.

| Owner | Files and responsibility |
| --- | --- |
| MemoryNexus version installer | CLI binary, complete script package, canonical Skill and relative resources; immutable version identities and installation manifest. AIWB references this package without copying the helper or Skill body. |
| Project's existing activation owner | Only the selected client discovery entries and their version references, with ownership/digest checks and recoverable backups. AIWB supplies the handoff convention; no new manager is required. |
| Target project | Existing task config, private binding/ledger and pending requests, reports, code/tests, handoff records and authoritative Issue status. Keep these outside AIWB; private memory/transport files stay outside Git. |

Before activation, record the full delivered source SHA and canonical path, MIT attribution, exhaustive resource inventory, installed package digest, binary build source SHA and binary digest separately. Retain the exact Python path/identity required by the upstream preflight. Record installed client versions with each observation, not a blanket “supported” label. A source-script digest is not the installed-package digest; obtain the latter from the upstream installation manifest.

The upstream `integrations/task-memory/install.py` selects the complete `scripts/` package and preserves document paths below `VERSION/package`. Keep canonical `references/`, shared `PROTOCOL.md`, bootstrap/repository-review companions, Codex/MiniMax entries, onboarding/current-knowledge contracts and `LICENSE` from the same source. Follow the selected source's resource manifest and verify required relative references in the **installed** tree; copying or linking `SKILL.md` alone is insufficient. The selected `daily-interface.md` defines a bounded installed closure with 13 exact source-only navigation/evidence exceptions and a conditional source handoff for repository sample discovery. Honor those exact edges and stop that discovery if its handoff is unavailable; do not claim all transitive repository links are packaged or use exceptions for missing daily runtime resources. The upstream `references/daily-interface.md` owns exact helper invocation and `references/acceptance.md` owns its implementation evidence. An upstream test report is not project discovery or behavior evidence.

## Project entry and daily use

Use the owner's selected project root and existing native discovery entry. Preserve its rules and any same-name non-managed package; conflicts or user edits stop the update. Show the candidate package, entry paths, owner and recovery plan before activation. Retain existing global installations unchanged.

The effective project context should point to the selected canonical Skill and the **existing** private binding, with a short intent such as “接上这个任务，入口 `<binding>`”. It should also identify the approved report location and how its owner can access reports. Do not embed corrected answers or a copy of remembered task content in a handoff prompt. The client reads the upstream rules and context, verifies task identity, effective record IDs and omissions, and stops history-dependent work on failed or incomplete loading. Missing binding is not permission to initialize a substitute task.

Use the upstream content-level authorization and exact-target rules for corrections; a generic request to use memory does not supply confirmation. Keep current owner instructions distinct from historical checkpoints, development self-reports, self-tests and independent acceptance. Record a rejection with its source/evidence, repair, then independently recheck; a newer checkpoint does not turn a rejection into a pass. At handoff, make the current workspace writer explicit. At closeout, save and read back the checkpoint, link the project-owned report, confirm access and list uncommitted, unpublished and unverified work.

This entry does not require `deliver-spec` or a full multi-agent workflow. Reuse the [single-Issue route](../workflows/single-issue-trial.md), [self-test report](self-test-report/SKILL.md) and existing [run-record outline](deliver-spec/references/run-record.md) when applicable. MemoryNexus remains the task-memory authority; Issues remain the work-status authority.

## 按名称使用“读/记”

可选的 [AIWB 客户端入口](memorynexus-task-entry/SKILL.md) 提供中文的列任务、列记录、读/接上、记、改、撤、看理解与记忆帮助；完整语法以入口命令表为准。
AIWB 只拥有名称定位脚本及客户端意图接线，仍调用已绑定 MemoryNexus 的 `daily.py`，不复制其运行包或引入第二账本。
同名先选，未登记或读取失败不自动建任务；含指代的保存请求先展示精确摘要取得确认。

名称目录和 task/binding/ledger 均留在本机私有位置，不进入 AIWB Git。
本入口不加入默认 Profile；owner 明确选择的个人 Codex 新会话可按 [配置说明](memorynexus-task-entry/references/setup.md) 将该单一入口作为全局例外。
2026-11-06 的本机 Codex CLI 新会话已观察到按名读回，保存链路在隔离合成任务通过；这不扩展上文 #155 的 Desktop/Traex 证据。
后续已实测本机 Codex Desktop 全新聊天与 Traex 0.213.1 独立测试项目的自动发现和中文命令；真实任务只读，写入仅在隔离任务。客户端各自候选、失败历史、当前环境回归的三项既有失败及未验证范围见 [接入记录](../docs/testing/memorynexus-task-entry.md)。这些观察不扩展为其他项目/机器、真实任务写入或跨机接力验收。

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
