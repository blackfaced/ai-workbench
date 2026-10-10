# Spec #366：测试设计与按规格交付验收记录

本文件是 AIWB 所属需求 [#366](https://code.byted.org/hancheng.hc/dev-tracker/issues/366) 的唯一当前验收记录，覆盖子任务 [#367](https://code.byted.org/hancheng.hc/dev-tracker/issues/367)、[#368](https://code.byted.org/hancheng.hc/dev-tracker/issues/368)、[#369](https://code.byted.org/hancheng.hc/dev-tracker/issues/369)、[#370](https://code.byted.org/hancheng.hc/dev-tracker/issues/370)。需求正文与状态仍以 Issue 为真源；不在此管理排期。报告只[索引本记录](spec-366-report.md)。证据目录中的客户端 fixture 是不可变历史快照，不能作为另一个当前结果台账。

## 范围、候选与接受责任

- 需求和旧设计基线：`16bfd98a6e312dbb1f34533254d9ff7e1f203038`。固定需求正文摘要见[证据清单](evidence/spec-366/manifest.json)，没有复制完整 Spec。
- #367 集成：`39e72e281a67fffba6e84b6b94be51a7ec69d114`；#368 集成：`f016c8a5eca43fa69c75a2fc3b7727f4f8f7b861`；#369 已接受的实现：`8d47e56f95ebe298cf0923087dbf4477879b7620`。
- #370 先提交再执行的测试候选：`79c94296eb1bdbfcee5d3f594719a07a5555b052`。相对 #369 仅增加试跑脚本及完整回归的一次调用，不改变安装器、Profile 或 Skill。随后的验收资料提交只增加 `docs/testing/`；不得把它的 SHA 倒填为此前测试身份。
- 实际运行：2026-10-10，本机 Darwin、Python 3.9.6；详细系统、文件 SHA-256 与 UTC 见 [identity.json](evidence/spec-366/370/matrix/identity.json)。三 Profile 是本机隔离 HOME 的配置回归，未代表在 Linux 或家用机器实际运行。没有服务端部署物。
- 本轮 worker 提供开发自测及报告；#367–#369 merger 提供代码审查；父 agent 观察原生客户端并接受对应子任务。没有独立 QA。最终代码审查、父 Spec 接受和 Issue 关闭仍由父 agent 负责；此记录不宣布整体最终接受。

## 需求 → 不变量 → 用例

以下组覆盖父 Spec 的全部 32 条故事；子任务验收条件按可判定合同归组，不按用例数量证明质量。

| 父故事 / 子任务合同 | 不变量与观察位置 | 用例及证据边界 |
| --- | --- | --- |
| 1–6、8–12 / #367 设计与质量审查 | 从真实需求与入口提出有依据的错误条件、数据、动作和断言；复用已有覆盖，缺材料不编造预期 | `TD-METHOD-01`：独立调用产出的 [design](evidence/spec-366/client-test-design/design.md) 与 [variants](evidence/spec-366/client-test-design/variants.md)；正常、无变更、完整设计、矛盾、缺 oracle/物料、Mock-only 输入；设计本身不产生执行 PASS |
| 7 / #367 身份边界 | 需要独立权威判据；同源 Mock 不足，未知 Owner 保留未决 | `TD-ORACLE-01`：客户端 [acceptance 快照](evidence/spec-366/client-integration/acceptance.md) 中明确合成的 `SYNTHETIC-OWNER-01`；验证方法如何处理缺口，不验证真实服务归属 |
| 13–14、21–25 / #369 顺序、记录与责任 | 已确认计划之后、派发之前使用方法；保留旧 ID/预期/FAIL；新增设计与执行状态分离，证据有效性单独处理；报告仅索引，parent 保持接受权 | `TD-RECORD-01`：同一实际客户端经旧入口更新既有 fixture，再从新入口做无变化复核；[before](evidence/spec-366/client-integration/before.md) → [after](evidence/spec-366/client-integration/acceptance.md) → [报告](evidence/spec-366/client-integration/report.md)；顺序与独立用法见 [deliver-spec](../../skills/deliver-spec/SKILL.md)、[说明](../../workflows/implement-batch.md) |
| 15–18 / #368 名称、旧调用及在途合同 | 一个规范正文，薄别名保持旧显式调用、旧资源和原授权/记录；改名不授予新副作用 | `TD368-CLIENT-AUTH-01` 及 `case_implement_batch_distribution`；安装后旧名委托与新名直读同正文，受限调用保持原授权；代码/文档迁移由已完成的 merger 内容审查佐证 |
| 17、19–20 / #367–#369 分发、兼容、保护 | 单独 test-design 与新旧定向安装均可用；三 Profile 的正文、附件、发现、幂等、旧安装升级、修改保护和 restore 合同成立 | `case_test_design_distribution`、`case_implement_batch_distribution`、`case_self_test_report_distribution`、`case_skill_install_with`、`TD368-UPGRADE-GUARD-01`；真实 CLI 与文件，受管归属 guard，不用 Mock 取代安装器 |
| 26 / 所有票的验证分层 | 安装、原生发现、实际调用、隔离入口验证与真实需求试跑分开 | 下方分层记录；真实客户端仅 Codex 受限应用，目录/发现成功不能推断完整工作流执行 |
| 27–29 / #370 检測对照 | 同一需求与 fixture：旧观察器漏过已知错误，增强断言检出，正确控制与新 HOME 复测通过 | `PILOT-LEGACY-DELEGATION-01`，设计和每次结果见下；不删除旧断言 |
| 30–32 / 资料归属、独立性与结论边界 | AIWB 是本次真实需求拥有者；资料留本仓，复用标准库测试；无 QA bot/Claw/新服务依赖；已知答案补测不外推未知缺陷发现能力 | 本目录及试跑脚本；外部 Dev Tracker/Botmux/远端机器/自动改规则不属于本次执行。未观察到通用方法缺陷，无自动规则修订 |

## PILOT-LEGACY-DELEGATION-01：设计与前置

需求是 #368 的真实旧入口兼容合同。旧设计固定于 `16bfd98` 的 `case_implement_batch_distribution`：实际 `apply --only implement-batch` 返回 0、已安装 botmux 附录与来源字节一致、实际 `check --only implement-batch` 返回 0。旧 fixture 仅装载一个 Skill；为适配已确认迁移，本实验装载当前四个相关真实组件，但旧观察语义保持三项不变。没有声称旧整份测试原封不动运行，也不要求历史设计预知未来改名。

增强设计来自实际安装后的 test-design 应用：[设计输出](evidence/spec-366/client-test-design/design.md) 与[调用观察](evidence/spec-366/client-test-design/observations.md)。该调用已读到预选题的已知错误假设，因此是对既有建议的审查与补足。它增加了规范正文身份、资源可达、误报控制和证据边界；不是无提示发现缺陷。

数据采用当前真实 work-mac 的四个相关 Component、完整源码附件与既有 Sandbox。`env.py`、Profile 和文件系统真实运行；客户端发现使用 Sandbox 的 shared 目录能力，无网络、模型或真实机器配置写入。输入数据已实际准备成功。没有业务凭据、服务账户或计费副作用。本地文件归属相关，沿用现有生产写入/restore guard；外部主体和业务资源 Owner 的核验不适用。

待检测错误：旧 Skill 首段的主委托链接指向不存在路径，安装内容仍与声明一致。仅在临时源副本替换这一处链接：[mutation.patch](evidence/spec-366/370/mutation.patch)。其它 section-anchor 备用链接仍存在；本实验只声称捕获错误的主委托引用，不能推出整个工作流完全不可达。候选仓库未被故障修改。

新增可观察断言：从实际已安装旧 `SKILL.md` 的主引用解析目标，要求目标可读、内容等于冻结候选唯一规范源与客户端 frontmatter 的组合，再要求其实际本地资源链接可读。字节关系证明分发身份，不证明模型遵守内容。错误观察器和正确控制使用同一组断言，不能为了得到失败改测试。没有“查到关键词就算通过”的断言。

复跑入口：

```sh
python3 tools/environment/tests/legacy_delegation_pilot.py --fault --output /tmp/aiwb-370-new-fault
python3 tools/environment/tests/legacy_delegation_pilot.py --output /tmp/aiwb-370-new-matrix
python3 tools/environment/tests/regression.py
```

输出目录必须全新，防止覆写首次证据。第一条预期返回 1，直接暴露检测器 FAIL；第二条预期返回 0，因为矩阵要求错误被检出且两次正确行为通过。默认无 `--output` 时成功清理隔离目录；完整回归包含同一矩阵。安装器、生产源和断言在这些运行间未变化。

## 原始结果与当前有效性

本表是当前结果源。PASS/FAIL 是对应断言的实际执行；VALID/STALE/UNVERIFIED 描述适用性，不能互相替代。历史失败和首次受控错误均保留。

| 稳定用例 / 运行 | 预期与实际观察 | 原始结果 | 当前有效性、角色与原始证据 |
| --- | --- | --- | --- |
| `case_test_design_distribution` / 367-red → green | 新组件最初三 Profile 缺失；加入组件后独立安装、正文/附件/引用与 check 通过。最终全量包含编辑保护与 restore | 首次 FAIL；后续 PASS | 首次仅为历史缺失，当前由 370 全量覆盖；[red](evidence/spec-366/367/red-install.log)、[green](evidence/spec-366/367/green-install.log)。#367 worker 自测 |
| `case_implement_batch_distribution` R1 / 368-red → green | 旧三项全过但三个 Profile 缺规范入口；修复共装选择后规范入口可用 | 首次 FAIL；后续 PASS | R1 已覆盖，不能独自证明 #369 新方法行为；[red](evidence/spec-366/368-red-old-only.log)、[green](evidence/spec-366/368-green-old-only.log)。#368 worker 自测 |
| `TD368-UPGRADE-GUARD-01` / exact-base | 固定 `39e72e2` 的旧 env.py/真实源、Profile → 旧 apply → 迁移 plan/apply/check → restore 完整 state → 旧 apply；三 Profile 通过，隔离项目 checkpoint 字节未变 | PASS | 历史 exact-payload 证据；[原脚本快照](evidence/spec-366/368-pinned-upgrade.py.txt)、[结果](evidence/spec-366/368-pinned-upgrade.log)。#369 后 Profile/正文有变化，不能把整条历史结果直接标当前；当前形态升级/还原/用户保护由 370 全量再次覆盖，未重做该历史 payload 的全部新组合 |
| `case_implement_batch_distribution` R2 / 369-companions、links | 首轮 81/12 缺两个配套 Skill，修复后 93/0；第二轮 105/12 缺已安装方法链接，修复后 117/0 | 两轮首次 FAIL；各自后续 PASS | [companion red](evidence/spec-366/369-red-install.log)、[green](evidence/spec-366/369-green-install.log)、[links red](evidence/spec-366/369-red-links.log)、[green](evidence/spec-366/369-green-links.log)；R2 兼容/共装最终由当前全量覆盖 |
| `TD-METHOD-01` / 实际独立应用 | 安装的 test-design 生成可操作设计，复用旧 ID，六个输入变体没有伪造执行通过，没有启动开发/部署 | PASS（观察到的设计行为） | VALID：test-design 内容未变；[design](evidence/spec-366/client-test-design/design.md)、[variants](evidence/spec-366/client-test-design/variants.md)、[observations](evidence/spec-366/client-test-design/observations.md)。Codex 原生 subagent 实际应用；其内部项目用例当时仍未执行，不将该观察 PASS 移给内部用例 |
| `TD-RECORD-01`、`TD368-CLIENT-AUTH-01`、`TD-ORACLE-01` / 369-client | 旧入口实际读规范→方法→报告规则，原位增强同一记录；原 R1 FAIL/PASS 原句和 ID 保留，R2 原始 NOT_RUN 与 STALE/UNVERIFIED 分离；合成未知 Owner 保持未决；新入口无变化复核不重建/重测/重授权 | PASS（受限设计阶段观察） | VALID：四个安装正文的哈希与本候选渲染值相同；[前后快照](evidence/spec-366/client-integration/acceptance.md)、[调用顺序/哈希](evidence/spec-366/client-integration/observations.md)、[父 agent 独立核对](evidence/spec-366/369-parent-acceptance.md)。不是完整 deliver-spec 执行或真实业务 Owner 验收 |
| 安装 / 原生发现 | 本机旧名定向 apply/check 通过；Codex 原生发现能列出新旧名称与 test-design；安装器自己没有驱动模型 | PASS | VALID：[apply](evidence/spec-366/369-native-apply.log)、[check](evidence/spec-366/369-native-check.log)、[选定名字的原生清单](evidence/spec-366/native-discovery-selected.log)。清单来自 #368，名字不变；#369 check 再次原生发现无错误。Trae 发现的零错误不能外推为实际调用 |
| `PILOT-LEGACY-DELEGATION-01` / 370-first-fault | 首次受控错误：旧三项 true；增强三项 false，主目标为 `../absent-canonical/SKILL.md`；CLI apply/check 均 0 | 检测器 FAIL，进程 rc=1 | VALID：预期的真实错误条件失败；[日志](evidence/spec-366/370/first-fault.log)、[命令与候选](evidence/spec-366/370/first-fault-run.json)、[安装/检查原输出](evidence/spec-366/370/first-fault/fault/result.json)；#370 worker 自测，07:21 UTC |
| 同 ID / 370-matrix-fault | 同候选再次注入单点错误；旧三项仍 true，增强在主委托处失败 | 检测器 FAIL | VALID：[原始结果](evidence/spec-366/370/matrix/fault/result.json)、[apply](evidence/spec-366/370/matrix/fault/apply.log)、[check](evidence/spec-366/370/matrix/fault/check.log)。这是要求检出的错误，不是待修复产品缺陷 |
| 同 ID / 370-matrix-correct | 正确源、全新隔离 HOME；旧三项和增强三项全部 true | PASS | VALID：[结果](evidence/spec-366/370/matrix/correct/result.json)及同目录 apply/check；没有观察到所选正确控制上的误报 |
| 同 ID / 370-matrix-repeat | 再换新 HOME 重复正确版本；所有观察再次 true | PASS | VALID：[结果](evidence/spec-366/370/matrix/repeat/result.json)及同目录 apply/check。两次正确对照只说明本场景稳定，不声称统计效果 |
| 370-matrix 实验门禁 | 要求已知故障被检出，同时正确与复测通过；3 次运行、每次 3 个旧观察和 3 个增强观察 | PASS，rc=0 | VALID：[汇总原输出](evidence/spec-366/370/matrix.log)、[执行身份](evidence/spec-366/370/matrix-run.json)。不把故障中的预期 FAIL 隐藏进总通过数 |
| 环境全量 / 370-regression | 必需 `python3 tools/environment/tests/regression.py`，既有合同仍通过，增加一个 pilot 实验门禁 | PASS，339/0，rc=0 | VALID：[完整输出](evidence/spec-366/370/regression.log)、[精确候选/命令/时间](evidence/spec-366/370/regression-run.json)。07:22:11–07:22:48 UTC，#370 worker 开发自测；包括真实 CLI 三 Profile 配置与隔离客户端协议，未驱动真实模型 |

## 历史全量、复用与缺口

#367 全量 191/0、#368 全量 266/0、#369 全量 338/0 是对应阶段自测结果，保留[367 尾段](evidence/spec-366/367/regression-tail.log)、[368 尾段](evidence/spec-366/368-regression-tail.log)、[369 尾段](evidence/spec-366/369-regression-tail.log)。完整原日志的 SHA-256 记录在清单；归档的是明示摘录，不能声称保存了全部历史输出。当前全量 339/0 是新执行结果，避免把较早测试数和版本直接套到当前版本上。#368 最终 legacy anchors 之后曾重跑受影响的迁移 case；当前全量又覆盖此路径。

#369 第一次全量在受限沙盒中为 337/1，原因是既有 Kimi 子进程清理的 `ps` 可见性不足：[原始失败尾段](evidence/spec-366/369-regression-sandbox-tail.log)。随后原代码和测试在获准进程检查权限下为 338/0，没有绕过测试。#370 直接在相同已批准权限下运行 339/0；没有抹去前次环境失败，也没有把环境失败计为本次受控故障。

已安装四个正文在本轮只读复核与候选渲染值相同：legacy `f70e764c…`、canonical `21d7558c…`、test-design `e03a54a8…`、self-test-report `7ce37b97…`，完整值见客户端 observations。#370 没改这些源，因此 #369 的原生设计行为证据可复用。原生调用的实际模型继承父配置，但工具没有暴露型号，故保持“未经验证”；不推测费用或模型版本。

仍未执行：其它客户端的实际 Skill 应用、Linux/家用机器原生安装、本次完整 deliver-spec 从计划到交付的模型运行、外部业务服务/资源 Owner、Botmux 离线接班及跨机器恢复。前四者超出本次选定客户端/场景的证据覆盖；后三类不属于本 Spec。合成 Owner 用例内部仍是 NOT_RUN/缺独立判据，设计方法正确保留缺口不等于服务验收通过。没有把这些项目计入通过率。

## 方法结论、资料与访问

本次真实需求的主委托引用错误能够漏过旧安装观察，而增强断言已检出；正确行为两次通过。故障由题目选择阶段已知并注入，只能结论“这一检测缺口已补齐”。它不是实际线上缺陷，不证明普遍发现未知缺陷，也不以 339 或用例增加量证明方法更有效。备用链接和模型自行恢复路径未纳入错误条件结论。

测试源、物料与原始证据属于 AIWB 自己的 #368 需求，留本仓符合项目归属边界。`manifest.json` 列出每份原始摘要、存储摘要与脱敏/摘录规则；替换本地 HOME、临时根和主机名，原始断言、结果、候选与内容摘要保留。客户端调用文件是执行者当时的产出/观察和父 agent 核对，不是原始会话 transcript 的完整导出；其中工具输出 ID 用作本次会话回溯。没有新增长期服务或第二份业务用例库。

报告和证据已本地生成，尚未发布；本机作者已逐项读取必要文件并校验摘要，团队读者可访问性未验证。相对链接适用于本仓检出；没有推送授权，也不把本机路径当成团队共享地址。最终代码审查与整体验收仍待父 agent 完成，未在此宣布零缺陷或整体完成。
