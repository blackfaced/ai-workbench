# MemoryNexus“读/记”入口固化验证

## 中文命令与理解 Lens 补测（2026-11-06）

模式：update。本轮交付中文列表、单条读取、更正、撤回、帮助及按需理解 Lens，保留原来的读、记、接上；没有新增服务、账本或调度。下方原有 #166 结果保留为历史，不用本次结论覆盖旧 Attempt。

功能候选为 `d9d8a1bd4ea6b04304f217564e966ff50151bacd`；本次发布报告的提交只改文档，不把其 SHA 套到先前实测上。理解规则固定在 MemoryNexus `891deb936c811a2e91d804b6ee28610b5210b0f8`，运行包仍使用原 pinned helper/binary。客户端实测身份分别记录，不将 Codex 的旧候选结果冒充最新候选重跑。

| Case / Attempt | 实际候选、来源与范围 | 观察 | 结果 / 有效性 |
| --- | --- | --- | --- |
| ENTRY-NAME / 2 | repo_test；本分支定位器，新旧可执行字节在后续说明修订间未变 | 10 个独立进程用例通过；新增任务列表不打开或暴露 binding，同名保留、空表与无效索引区分，保留原 7 项断言 | PASS / VALID |
| ENTRY-READ / 2 | Codex Desktop 全新无仓库聊天；Skill 为 `5acad26fcbf3b901123d6e254a051d97447b08bb` | 提示未给 Skill 名称或路径，第一条执行读取已安装入口；真实任务只读，26 项动作元数据覆盖帮助、列表、读取、Lens、隔离记/改/撤及兼容别名；隔离 task revision 5 → 8 | PASS / VALID 于该候选；最新说明修订未重跑 Codex |
| ENTRY-TRAEX / 1 | Traex 0.213.1；`d9d8a1bd4ea6b04304f217564e966ff50151bacd`；独立测试项目 | 原生 skills/list 唯一匹配且无解析错误；新会话提示未给 Skill 名称或路径，首个工具实际读取项目入口；28 项动作元数据、26 条成功 shell 命令覆盖同一套中文命令 | PASS / VALID，仅该项目 |
| ENTRY-WRITE / 2 | 上述 Codex 与 Traex 会话各自的独立合成写入；复用同一个隔离账本 | 每轮 record/correct/retract 均 accepted / synchronized，返回实际新旧 ID；撤回后整链均 retracted 且无正文，无关记录保留。Traex 轮次 revision 8 → 11，新写入来源为 traex，原 Codex binding 未改 | PASS / VALID，仅隔离数据 |
| ENTRY-LENS / 1 | 同机真实只读任务与隔离撤回后的新读取；固定上游规则 | 正文来源、遗漏与证据缺口保持可见；撤回后不重构原文，观察只在聊天展示，没有自动记入账本 | PASS / VALID 于所读有界记录；用户长期 usefulness 尚未验收 |
| ENTRY-PERMISSIONS / 1–2 | Traex 启动前的自动审批与参数核对 | 首次真实 state_root 写权限被拒绝；auto 模式权限范围不明也被拒绝；CLI 的 no-daemon/互斥权限参数发生启动失败，均在实际验证会话前保留失败记录 | BLOCKED / VALID 历史 Attempt，不改写为通过 |
| ENTRY-PERMISSIONS / 3 | 上述 Traex 成功会话 | 使用显式 workspace-write 与 never 审批策略；额外可写范围仅测试输出、隔离 state/data，不授予真实任务目录写权限。单条读的 ID-only 请求放私有临时目录并清理 | PASS / VALID |
| ENTRY-PRIVATE / 2 | 两个客户端执行后，由本聊天交叉核对实际文件摘要与 pinned 公共读接口 | 真实 task revision 仍为 2；真实账本、绑定和个人索引逐字节未变。Traex 最终两个 ID 经额外独立进程读回，均为 traex / retracted / 无正文 | PASS / VALID；同一开发流程的核验，不称独立 QA |
| ENTRY-REGRESSION / 3 | 既有环境套件；候选工作区的执行代码与最终候选相同，后续仅说明文字变化 | 363 项通过、3 项失败；work-mac / work-linux / home-mac 的旧 implement-batch plan 检查失败。在未改基线 `10a17708d9da4550a8b8ead4049661d236bfa1fd` 定向复现同三项（123 通过、3 失败），未改断言或修邻项 | FAIL / VALID；整体回归非全绿，未获豁免 |

身份合同 `applicable=true`：本次触及任务归属及写入客户端来源。核对既有绑定的真实 task ID、pinned binary/package、helper 收据和实际读回；Traex 使用独立 client binding，不能把 Codex 来源改名冒充。真实任务与隔离任务身份不同，所有写入均在后者。此证据支持本机单 owner 的命令映射与归属，不提供跨用户认证或跨机权限结论。

源码与报告可随分支共享；原机器证据留在 owner 本机的 `memorynexus-command-entry/` 受管工件中，未将任务正文、私有路径、实际任务/记录 ID、binding、ledger 或完整模型日志复制进 Git。远端读者可读此摘要，但未获得原始私有证据访问权。原始去正文机器 JSON 的 SHA-256：

- Codex：`636ffee70b59a9e04961783abed2612f857875db448af4191e73554708249ee1`。
- Traex：`5b8d0b58e15a4c37199ce4f405320cb5ed59dca9208941d78b4676dcb61166c8`。

功能观察不等于整体验收：当前环境回归仍有上述失败，未进行独立 QA。Traex 仅项目级启用，Codex 是此前已获准的单一个人全局入口；其他项目/机器、分散的独立用户消息回合、真实任务写入、真实业务消息路由、跨机接力与原会话历史合并均未由本轮证明。后续仅增加发布文档，不为此重复运行模型会话或全量测试。

## #166 原固化记录

2026-11-06；模式：compose。本页记录提交前候选的验证；源码与报告随同一提交交付，发布身份和合入状态以 Git 历史及 PR 为准。本机由原安装 owner 完成有备份的入口更新。
本报告是开发自测和客户端实测摘要，不是独立 QA 或其他客户端的验收。

## 范围与身份

需求：将已验证的本机“读任务名 / 记：原文”接线固化为 AIWB 可复用来源，保留同名先选、不知道路径也能接续的体验。
AIWB 只维护客户端 Skill 与只读名称定位器；MemoryNexus 原 helper、二进制、绑定、授权和账本语义不变。

候选基线 `06e01646678b80d4546bdadf29dd050533ca5a86`，分支 `codex/memorynexus-task-entry`。
提交前部署包以精确资源摘要标识，不以基线提交冒充新增内容：
`9e08e4bd4c9634980473d14e46693a94cdd126bacbf56f56f6ea5aea8c21b6b5`。
摘要为按路径排序的五个 `{path,sha256}` 条目之 canonical JSON SHA-256；四个 Skill 资源加仓根 Apache-2.0 LICENSE。
私有名称目录、任务绑定、账本、pending 和原始模型日志未复制入 Git；它们的实际路径与原始运行日志留在本聊天的持久工件。

## Case / Attempt 与结果

设计依据为本轮用户要求及 [配置合同](../../skills/memorynexus-task-entry/references/setup.md)。所有执行为本机 macOS；代码和断言由当前开发流程核对。

| Case | Attempt / 来源 | 观察与判据 | 结果 / 有效性 |
| --- | --- | --- | --- |
| ENTRY-NAME | 1 / repo_test | 7 项独立进程用例覆盖名称/别名、规范化、同名或别名冲突、未知项、重复 ID、缺失/非私有目录、名称作为数据；同名返回所有候选，不打开其 binding | PASS / VALID |
| ENTRY-RESOURCE | 1 / local checks | Skill validator、源码链接与分发闭包通过；已安装五个文件逐项匹配交付清单。安装后 setup 的 AIWB README 链接是明确的源导航例外，不是日常运行依赖 | PASS / VALID |
| ENTRY-READ | 1 / fresh native CLI | 新临时 Codex 会话只收到“读”加已登记任务名，无 binding 路径；实际读取新 Skill、定位器、绑定和 daily read，退出0，返回原任务/记录身份及版本2，无省略 | PASS / VALID |
| ENTRY-WRITE | 既有 Attempt 复用 / native CLI | 本聊天此前已用独立合成任务完成精确正文 → stage/apply → 实际 record ID/current/原文读回。固化前后 lookup.py 字节及 Skill 的完整“记”段落相同，未重复写真实任务 | PASS / VALID，明确复用 |
| ENTRY-REGRESSION | 1 / repo_test | 普通沙箱中365项通过、Kimi进程清理因禁止 ps 而无法完成；保留原日志，未改断言 | BLOCKED / VALID（环境限制） |
| ENTRY-REGRESSION | 2 / repo_test | 正常本机权限、临时 HOME 与合成仓库重跑同一既有套件：366通过、0失败 | PASS / VALID |
| ENTRY-PRIVATE | 1 / readback + digest | 原研究任务仍只有1条记录、版本2；名称目录与原获准文件逐字节一致；源码只含通用字段样例，没有个人任务名、ID或绑定路径 | PASS / VALID |

未把7项定向用例和366项环境检查相加为覆盖率。新回归未覆盖真实 Desktop 下一用户回合、真实同名选择回合、其他客户端/机器，均为 NOT_RUN。
入口是模型选择 Skill 的能力，不是一个确定性拦截所有聊天消息的 hook。

验证命令：

```sh
python3 /path/to/skill-creator/scripts/quick_validate.py skills/memorynexus-task-entry
python3 -B -m unittest discover -s skills/memorynexus-task-entry/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/environment/tests/regression.py
git diff --check
```

## 安装、恢复与证据边界

身份合同 `applicable=true`：本机单 owner 信任边界；先以此前已记录的逐文件摘要证明入口归属且无编辑，再备份并切换。
既有 daily helper 使用原 pinned Python/binary/package，返回身份与已授权绑定一致；这不声称独立认证屏幕前用户。
配置和数据的权威仍在原位置，无账本迁移、跨任务扫描、Profile 默认改动或其他 Skill 更新。

本机更新的完整交付清单、旧目录备份、精确命令与执行前资源身份、原始退出码/日志、fresh read 实际 JSON 核验留在 `aiwb-task-entry-evidence/` 聊天工件中。
原本机实现与隔离写入日志留在先前 `named-resume-evidence/` 工件；仓内不复制私人执行内容。
资源核对器首轮漏匹配 source-only 链接的锚点，随后只修正核对器、未改源或分发字节，最终闭包通过；保留了该核对说明。

恢复时先验证当前入口仍匹配本候选清单，再恢复原目录备份；若有后续用户编辑，先停下合并，不覆盖。
个人全局入口是用户本次明确选择的单一例外；其他项目继续按 AIWB 默认项目范围启用。
完整新机器安装尚未验证。源码与本报告的仓库交付不扩大上述客户端实测范围；个人目录、账本和原始日志继续留在原批准位置。
