# 家用 Mac mini 验证

- Domain: ops
- Date: 2026-09-12
- Profile: [home-mac.json](profiles/home-mac.json)
- Decision: [0012](../../decisions/0012-home-mac-maintenance-validation.md)
- Baseline: main `0a2408f`（Orchestrator 已退役），加本次家用 Profile 与兼容性修复。
- Scope: 当前机器维护、安装与原生发现。不是新机首装、模型任务或远端验收。

## 本机身份与工具

用户确认当前机器是家用 Mac。实测为 Mac mini、arm64、macOS 26.5.2。
登录与非交互 zsh 的下列工具解析一致：

| 工具 | 实测版本 | 安装归属 |
| --- | --- | --- |
| Codex CLI | 0.142.5 | Homebrew cask |
| 桌面内置 Codex | 0.153.4 | ChatGPT.app，bundle ID `com.openai.codex` |
| Kimi Code | 0.41.0 | Kimi 自有安装器 |
| Node | 22.23.1 | nvm |
| 默认 Python | 3.14.7 | Homebrew |
| 系统 Python | 3.9.6 | `/usr/bin/python3`，兼容性验证用 |
| GitHub CLI | 2.96.0 | Homebrew |
| ripgrep / fd | 15.0.0 / 10.4.2 | Kimi 自带 |

`uv` 与 Trae 未在两种 shell 中找到。家用 Profile 不要求它们，也没有新增安装渠道。
本次没有安装或升级上述软件包。桌面客户端提供的临时 pnpm 路径不作为家用机器的安装基线。

## 结果

| 检查 | 结果 |
| --- | --- |
| home-mac plan | 7 个第一方 Skills 可安装；没有归属冲突 |
| 首次 apply | 成功安装 7 个 Skills 及配套文件，保留备份 |
| 再次 apply | exit 0，无变更（幂等） |
| bootstrap --profile home-mac --check | exit 0；待改动 0、需处理 0、Hook 重复 0、Skill 发现错误 0 |
| Codex CLI 原生 skills/list | 51 项，7 个第一方 Skills 全部可见，重名 0 |
| 桌面内置运行时原生 skills/list | 52 项，7 个第一方 Skills 全部可见，重名 0 |
| kimi doctor | config.toml、tui.toml 均有效 |
| Kimi ACP 命令发现 | initialize / session/new 成功，7 个 `skill:<name>` 命令全部可见；模型 prompt 0 次 |
| restore --dry-run | exit 0，能列出本次安装的可撤销文件，未执行真机回滚 |
| 隔离回归 | Python 3.9.6 与 3.14.7 各 84/84 通过；含实际沙盒回滚 |

七个 Skills：`steelman-grill`、`setup-aiwb`、`implement-batch`、`reflect-bug`、`review-lessons`、`handoff-to-dev`、`collect-from-dev`。
Kimi 命令发现按 [ACP session setup](https://agentclientprotocol.com/protocol/v1/session-setup) 建立本地空测试会话，未发送 `session/prompt`。
这证明原生运行时加载，不证明桌面菜单交互或 Skills 完成实际开发任务。

## 发现与处理

- 旧逻辑把任何 Darwin 主机选成 work-mac。现有多个 Mac Profile 时，未匹配主机必须显式选择；Linux 主机映射保持兼容。
- Python 3.14 对旧 UTC API 发出弃用警告。改用带时区的标准库 API，同时保留存储格式并修正 epoch 0。
- 首次 check 发现 14 个已失去目标的旧 Matt Skill 符号链接。按原名归档链接本身后，完整 check 通过。
- 本地旧虚拟环境、未批准的仓库工作流草案、egg-info 已归档。检查范围内未发现 aiwb PATH 命令、LaunchAgent、MCP 注册或运行中的 aiwb 命令。
- GitHub 22 个旧 Orchestrator / tracked-graph issue 标为 wontfix、以 not planned 关闭并注明 ADR 0010；#78 保留，去掉已退役 Python 包的验收项。

## 后续与恢复

Kimi 的原生命令发现本次单独实测，尚未并入自动 check；其 `skill:README` 与目录卫生检查的口径差异已记为 [#94](https://github.com/blackfaced/ai-workbench/issues/94)。不修改上游 README 来掩盖该差异。

新机首装、软件升级、真实模型任务、远端交接仍未验证。工作 Mac 与 Linux 的既有报告不由本轮本机检查替代。

本地恢复说明位于 `.git/aiwb-home-mac-20260912/README.md`。原 README/Todo 修改保留在命名 stash 中；旧运行器产物与断链均为移动归档，可移回原路径。Skill 安装备份为 `~/.ai-workbench/environment/backups/20260911T174609Z`。

```sh
sh tools/environment/bootstrap.sh --profile home-mac --check
python3 tools/environment/env.py restore --backup 20260911T174609Z --dry-run
```
