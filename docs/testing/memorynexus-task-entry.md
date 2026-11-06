# MemoryNexus“读/记”入口固化验证

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
