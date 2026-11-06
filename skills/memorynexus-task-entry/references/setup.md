# 配置与来源

## 用法和边界

- `读 任务名`：唯一匹配直接读取，同名先选。
- 已读回唯一任务后，`记：原文` 保存这条明确指定的内容。
- `记一下刚才的讨论` 先预览精确摘要，用户确认后保存。

AIWB 只维护触发词、名称/别名定位与客户端接线；`lookup.py` 不读取绑定或账本。
MemoryNexus 的 `daily.py`、CLI、私有 binding 和 ledger 仍由其原安装 owner 管理。
本入口不加入默认 Profile，也不管理模型、调度或跨机同步。

## 安装与升级

按 [AIWB 安装约定](../../README.md#installation-policy) 选择固定版本和客户端范围。
一般项目按项目启用；若 owner 明确要求在任意新 Codex 聊天按名称接续，可仅将本入口作为个人全局例外安装到 `~/.codex/skills/memorynexus-task-entry/`。
此例外不改变其他 Skill 的项目激活默认值。

交接仓库地址、完整源 SHA 或不可变包加内容摘要、下面的资源清单、仓根 Apache-2.0 LICENSE 与验证范围。
未提交的工作树不是已发布版本，不能以基线 SHA 冒充本次新增字节。

本 Skill 的完整资源为 `SKILL.md`、`scripts/lookup.py`、`references/setup.md`、`references/task-index.example.json`。
本页的 AIWB 安装约定是源仓导航，安装后按记录的固定源查阅；日常运行只需要本 Skill、名称目录和既有 MemoryNexus 绑定/运行包。
升级前比较目标的已登记摘要；无归属或有用户编辑时停止。备份原文件与清单，验证新资源完整后切换，保留备份用于恢复。
不复制个人目录进 Git，不修改 binding 或自动替换仍有 pending 请求的运行包。

## 私有任务目录

默认文件为 `~/.local/share/memorynexus/task-index.json`；目录0700、文件0600。
以 [字段样例](task-index.example.json) 为模板，替换为已存在的真实 task ID 和 binding 绝对路径；样例本身不可用作任务绑定。
核对 binding.task_id 和原 task config 一致后再登记；owner 必须明确授权登记该任务。
目录只保存名称、别名、用途与绑定指针，不保存任务正文、聊天、凭据或第二份记忆。
允许不同 task ID 使用同名/别名，查找会返回选择列表；同一 task ID 重复登记报错。
名称按 Unicode NFKC、大小写与空白规范化后精确匹配，不做模糊语义搜索或扫描其他目录。
未知任务不自动新建；读取失败不更换账本。没有已加载任务的“记”先问目标任务。

## 运行合同和验证

使用 owner 提供且验证过的 MemoryNexus 版本包及 pinned Python/binary/package 身份。
已验证兼容的 helper 合同见固定上游源
[日常接口](https://github.com/blackfaced/MemoryNexus/blob/71f2d7e04a639fef728adb9ecbd2335179d66065/integrations/task-memory/memorynexus-task-memory/references/daily-interface.md)。
该上游运行包保留 MIT 许可证，AIWB 不重分发其实现；它的版本身份与本适配层源身份分别记录。
`read` 以及 `stage --action record` / `apply` 的 schema、授权、幂等和 pending 语义由原合同负责，本 Skill 仅映射用户意图。

源内可执行 `python3 -B -m unittest discover -s skills/memorynexus-task-entry/tests -v`。
安装后先验证原生发现，再用仅含短任务名的新会话实际读回；明确正文的保存仅在隔离任务验收，保留实际 ID/状态和读回证据。
同名查找测试只证明定位器返回选择，真实用户选择回合另记。
CLI 新会话不等于 Desktop 原会话下一轮或其他客户端已验收；本机、其他机器与新安装覆盖分别报告。
