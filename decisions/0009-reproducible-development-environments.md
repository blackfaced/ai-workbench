# 0009 - Reproduce and Update Personal Development Environments

## Status

Accepted (v1) — 2026-09-07 用户批准落地，并调整实施顺序：**当前工作 Mac → dev8c → dev32c**；家庭 Mac 暂缓，后续复用本轮已验证的方案，不计入本轮完成范围。

- Domain: ops, coding
- Evidence date: 2026-09-07（三台机器均为当日只读实测；家庭 Mac 未连接，全部结论标为未验证）
- Repository baseline: `aa483dda28ae717cb19493bcd8ab36f2c34934f6`
- 第一版 Profile 范围：`work-mac`、`work-linux`。`home-mac` 只保留占位与差异说明，不实现、不验收。

## Goal

把 AI Workbench 的主要用途明确为：在一台新机器上快速恢复个人需要的开发能力，随后用同一入口检查和应用更新。

目标机器包括工作 Mac、两台 Linux 开发机，以及使用 ChatGPT 桌面应用与 Kimi Code 的家庭 Mac。追求工具可找到、配置有来源、需要的能力可用，不复制整台现有机器，也不要求每台机器安装相同软件。

## Current evidence

下表为 2026-09-07 当日只读探测结果，取代此前的粗略记录。探测覆盖：系统与架构、非交互 / 登录 shell 的 PATH、工具解析路径与身份、Skill 目录与符号链接、非敏感配置结构、相关仓库状态。未验证：远端登录凭据、模型可用性、容器服务、真实开发任务。

| 机器 | 现场观察（2026-09-07 实测） | 对方案的影响 |
| --- | --- | --- |
| 工作 Mac `F7FLM93HYT` | macOS 15.6.1 (24G90) / arm64，登录 shell 为 zsh。Codex CLI 0.151.0 来自 npm 全局包（`/opt/homebrew/bin/codex` → `../lib/node_modules/@openai/codex/bin/codex.js`，**不是** Homebrew formula）；ChatGPT 桌面应用另自带 `/Applications/ChatGPT.app/Contents/Resources/codex`，应用私有、不在 PATH。Kimi Code 0.39.0 装在 `~/.kimi-code/bin` 并自带 `fd`；Trae CLI 的 `traex` 同时投放了 `~/.local/bin/rg`（Homebrew 未安装 ripgrep）。Homebrew 6.0.9 拥有 node 24.3.0、pnpm 9.0.0、uv 0.8.4、gh 2.96.0、jq。`python3` 在登录 shell 解析到系统 3.9.6（Homebrew 另有 python@3.11 / @3.12）。无 tmux。`~/.zshrc` 把 `$HOME/.local/bin` 重复导出 4 次 | 可以作为客户端验证机。同一工具确实存在多个安装渠道，必须先落定“安装所有者”再谈更新；系统 Python 与开发 Python 需要区分；受管入口必须能与既有用户自定义 PATH 行共存 |
| dev8c = `10.37.6.89` / `n37-006-089` | veLinux 2 (lyra) / x86_64 / 32C，home `/home/hancheng.hc`。`codex 0.130.0`、`uv 0.10.7`、`rg`、`traecli`、`traex` 均已安装在 `~/.local/bin`，**但登录 shell 与非交互 SSH 的 PATH 都不含该目录，因此全部不可执行**。根因已定位：`~/.bashrc` 的非交互 early-return 守卫出现在 PATH 导出之前，而 `~/.profile` 中的 PATH 因 `~/.bash_profile` 存在而永远不会被读取。`/usr/local/bin/gh` 是内部主机查询工具且先命中；真 GitHub CLI 2.87.3 在 `/usr/bin/gh`。Node 22.22.3（nvm）+ pnpm 9.0.0；Python 3.11.2；无 tmux / jq / fd / fzf。Skills：`~/.trae/skills` 78 项、`~/.codex/skills` 1 项、`~/.agents/skills` 27 项（`lark-*`，已被 trae/claude 以符号链接复用）。`~/.codex/config.toml` 存在（15 行，含规则 hook） | 第一优先是修复命令入口，而不是安装软件。必须严格区分“未安装”与“当前 shell 不可见”；`gh` 身份冲突必须显式解决 |
| dev32c = `10.37.68.191` / `n37-068-191` | veLinux 2 (lyra) / x86_64 / 32C。PATH 正常：`~/.local/bin` 已在非交互 PATH 内，`codex 0.130.0`、`uv 0.6.13`、`rg`、`tmux` 均可执行。只有内部 `gh`，**没有** GitHub CLI。Node 22.23.2，**无 pnpm**，无 jq / fd / fzf。`~/.codex/config.toml` 缺失，`~/.trae/traecli.toml` 存在（46 行）。Skills：`~/.codex/skills` 2 项、`~/.trae/skills` 5 项，`~/.agents/` 存在但无 `skills` 子目录。无 `~/code/ai-workbench`。有 8 个 `bmx-*` tmux 会话在运行（最早 09-04，最新 09-07 11:04） | 需要显式版本基线与可选前端工具配置；`uv 0.6.13` 落后于 dev8c，升级策略要显式；在途会话必须保留，不按存活时间清理 |
| 家庭 Mac | 用户确认为 macOS，使用 ChatGPT 桌面应用和 Kimi Code；本轮未连接检查，架构、应用版本、已安装工具、权限与账号状态**全部未知** | 不纳入第一版实现与验收。首次安装先检测，不从工作 Mac 假定其权限、账号、插件或全部工具 |

两台开发机的 `/usr/local/bin/gh` 实际是工作环境的主机查询工具，并非 GitHub CLI。新机检查必须验证工具身份；仅 `command -v gh` 成功不够。保留原命令，GitHub CLI 使用独立用户安装路径；现有 AIWB 集成可通过 `AIWB_GH_BIN` 指向准确的可执行文件。

本机安装的 `aiwb` 已确认是 pipx 的 editable 安装，源指向 `~/code/ai-workbench-worktrees/fix-runledger-connection-leak/tools/agent-orchestrator` —— 一个 `git worktree list` 标记为 prunable 的历史 worktree。正式安装应来自明确发布版本或固定提交下的稳定路径，不能依赖临时 worktree 的生命周期。`aiwb` 保持可选，环境入口不依赖它。

Skills 同样没有统一基线：本机偏向 Matt 系（`~/.agents/skills` 为共享真源，trae 与 claude 以符号链接复用），dev8c 存在另一套通用工程流程（78 项），dev32c 仅有少量专用 Skills。不能把其中一台的全部配置当成新机默认配置。

三台机器的工作规则真源内容摘要一致；现有规则分发已有独立的权威仓库和脚本，应复用其分发职责。本文不迁移或复制该真源。

## Supplementary audit: what changes the proposal

参考用户提供的“四环境 Skill / MCP 审计”，并针对会影响取舍的结论复验。该报告还涉及 Aime、Trae、Claude 和业务专属 Skills，覆盖范围与本次三台主机、家庭 Mac 规划不同；安装目录数不能直接比较为实际加载数量。

| 结论 | 本轮判断与处理 |
| --- | --- |
| 本机 Codex 的 SessionStart 提示重复 | 已复验并修正判断：重复**不在** Codex 内部，而在 Claude 侧 —— `~/.claude/settings.json` 用 4 个独立 SessionStart 组注册了同一条 `cbm-session-reminder` 命令（startup / resume / clear / compact）。此外 codebase-memory 提示存在**两份不同正文**：Codex `config.toml` 内联 echo 与 Claude 的 `cbm-session-reminder` 脚本。二者 owner 都是 codebase-memory-mcp。处理：受管入口只做语义等价的合并（4 组 → 1 组 matcher），正文分歧只报告不改写，避免在安装模板里另建第二真源 |
| `steelman-grill` 在 Codex 与 Trae 内容不同 | 已逐份读取确认，既有正文差异，也有元数据差异。正文真源定为 Trae 侧的完整版（含出处与作者信息）；Codex 侧缺少 `disable-model-invocation`，其“仅显式触发”语义必须落在 description 上 —— 这属于必要的客户端差异，予以保留 |
| `grilling` 家族和 `handoff` 家族可直接合并删除 | 当前上游明确区分访谈原语、无状态入口、会落盘入口；`handoff` 写交接文件，`claude-handoff` 会启动后台 Claude。属于有区别的功能。按客户端和用途选择，删除前检查依赖，不按名称相近下结论 |
| 缺少 `config.toml` 导致 Codex Skills 不生效 | 该推断不成立。本机 Codex 0.151.0 在全新 CODEX_HOME、无 config.toml 的条件下，实际发现临时项目 Skill，且没有解析错误。dev32c 的旧版本仍需独立验证，不能由文件缺失判死 |
| 不同客户端配置相同 MCP，或配置为 disabled，就是冗余 | 需区分客户端隔离、旧手工安装、当前插件安装和是否仍被引用。跨客户端有相同能力可能是必要的；禁用状态本身不构成删除证据 |
| 模型不同就应先全部升级，或旧 tmux 会话应直接结束 | 模型按任务、账号可用性与成本选择；会话年龄不能证明实际加载状态。dev32c 上 8 个 `bmx-*` 会话属在途任务，明确不清理 |

两份调查支持同一个优先级：修复真实入口问题和来源漂移，减少无条件流程指令，再检查选定能力的实际加载。Aime 全局规则和业务 Skill 退役事项目前仅作为另一份报告的发现，未由本轮独立验证或修改。

## Tool selection and instruction boundaries

- 新机默认保留开发必需的 CLI 与所选客户端原生能力；飞书、内部平台等集成由工作 Profile 按用途选择。
- 浏览器、文档和表格能力优先使用客户端已支持的插件。先检查已有能力，再决定是否增加手工 MCP，不把插件数量当作复杂度结论。
- 代码图工具作为有收益时才启用的可选项；跨文件关系追踪、重复查询可以评估它，字符串和配置定位使用直接搜索。当前仓库已有的工具优先规则仍有效；调整时修改其真正来源，不在安装模板里另加一条相反规则。
- 通用工程方法论不进入全局强制流程。Skills 主要补充项目知识、工具协议、用户明确选择的方法和产物要求；第一版 Profile 只列选中的 Skills 及其必需依赖。
- 权限按具体操作、目标和现有授权判断。可减少重复的只读确认，但不因为模型升级而整体放宽浏览器、内部平台或文件权限。

## Proposed repository role

README 的首要入口改为“新机安装 / 日常更新 / 环境检查”。

- `skills/`：第一方 Skills 的源码、明确选择的第三方来源与固定 revision、使用和兼容性说明。参考合集仍可保留为阅读资料。
- `tools/environment/`：轻量安装入口、机器类型配置、包清单和客户端配置模板。
- `workflows/`：新机上手、更新、账号授权与故障恢复说明。
- `decisions/`：记录规则与配置的唯一来源、公共和私有配置边界。
- `tools/agent-orchestrator/`：可选的无人值守实验工具，独立维护。环境安装不依赖其 Daemon、Contract、Admission、RunLedger 或 Harness Setup。

第一版实现的目录与命令：

```text
tools/environment/
  README.md
  bootstrap.sh          # 薄壳：定位 python3 并转发，供全新机器直接使用
  env.py                # 唯一实现，子命令 plan / apply / check / restore（仅标准库）
  profiles/
    work-mac.json
    work-linux.json     # 两台开发机共用；机器差异写在 overrides 段
  packages/
    macos.Brewfile
skills/
  steelman-grill/
    SKILL.md
    clients/
      shared.frontmatter.md   # 只装 ~/.agents/skills 一份，两个客户端聚合发现它
      openai.yaml             # Codex 侧界面 / 策略描述，随受管副本一起安装
  sources.lock.json
```

与初稿的差异有两处。其一，原计划的 `doctor.py` 取消，检查合并为 `env.py check`。理由是 Profile 用 JSON，而两台开发机都没有 `jq`；若 bash 与 Python 各写一份 JSON 解析，等于维护两份同构逻辑。现在保持“一份实现 + 一个薄壳”，`bootstrap.sh` 只负责在新机上找到 `python3` 并转发参数。

其二，原计划的 `templates/codex.toml`、`templates/kimi-code.toml` 不在第一版落盘。客户端配置由各自的安装器拥有；本仓再写一份模板等于为同一份配置造第二真源，与本文其余部分的取舍相反。受管入口只在带标记的块内写入，其余交给客户端原生流程。

`home-mac.json` 在第一版不落盘 —— 无法验证的 Profile 写进仓库只会变成第二份未经核对的事实。

沿用现有顶层分类，不增加新的顶层目录。Profile 是软件与能力的明确列表，不是可编程工作流 DSL。

## Profiles and local differences

| Profile | 第一版状态 | 默认用途与能力 | 按需选择 |
| --- | --- | --- | --- |
| `work-mac` | 实现并验收 | 本地开发工具、ChatGPT/Codex 客户端、Git/SSH、已有工作规则分发 | Kimi Code、Claude Code、浏览器诊断、工作专属工具 |
| `work-linux` | 实现并验收（dev8c、dev32c 共用） | 可在普通 SSH 会话使用的用户态 CLI、Codex、Git、Python 工具、搜索工具 | Node/pnpm、构建语言、终端会话管理、工作专属工具 |
| `home-mac` | 暂缓，未验证 | ChatGPT 桌面应用、Kimi Code、Git、基础终端工具、个人 Skills | 项目需要的语言、容器和诊断工具；Codex CLI 仅在确实需要其接口时安装 |

两台开发机复用同一份 `work-linux`。CPU 数量或 alias 名称不构成不同安装流程的理由 —— 实测两台都是 32C，`dev8c` / `dev32c` 只是习惯叫法。真正需要显式声明的本地差异只有下面四条：

| 差异项 | dev8c (`10.37.6.89`) | dev32c (`10.37.68.191`) | 处理方式 |
| --- | --- | --- | --- |
| 用户态 PATH 入口 | 缺失，`~/.local/bin` 对登录 shell 与非交互 SSH 均不可见 | 已可见 | 同一个受管 PATH 块，幂等写入；已生效的机器上应用后无变更 |
| GitHub CLI | 已存在 `/usr/bin/gh` 2.87.3，被内部 `/usr/local/bin/gh` 遮挡 | 不存在 | 显式路径 + 身份断言；不安装、不改内部 `gh` 的优先级 |
| pnpm | 已有 9.0.0（nvm 目录内） | 无 | 归入按项目需要的可选项，不因“另一台有”而安装 |
| tmux 与在途会话 | 无 tmux | 有 tmux + 8 个 `bmx-*` 在途会话 | 会话一律保留；tmux 归可选项 |

公共仓库只保存通用模板与软件来源。工作专属规则仓库、服务地址、SSH 主机映射、内部工具来源和私有文档入口保留在私有覆盖中。家庭 Profile 不依赖工作网络或工作规则仓库。

## Reuse existing installation mechanisms

1. macOS 软件使用 Homebrew Bundle 的声明式清单；桌面应用优先使用官方支持的安装和更新渠道。只管理选中的软件，不将本机全部 Homebrew 安装导出成默认清单。
2. Linux 优先保留现有系统包与用户态安装。需要系统权限的依赖明确列出，由用户或机器管理方处理；不把升级共享主机系统作为开发环境更新的一部分。
3. Python 开发版本和独立 Python 工具优先复用 uv；保留系统 Python。项目的 Python 版本由项目约束决定，不统一改写所有项目。
4. Node 和 pnpm 声明项目需要的版本范围和安装所有者。第一阶段不批量迁移已有 nvm/Homebrew 等管理器；先解决多个版本目录与非交互 PATH 的问题。新安装的同一工具只选择一个管理渠道。
5. 不先引入 Ansible、Nix 或新的自建常驻配置服务。第一版只编排已有安装器、固定 Skill 来源和少量配置写入；出现明确复杂度后再决定是否采用专门的配置管理工具。

每个受管工具都必须在 Profile 里写明 **安装所有者（owner）**，`check` 用它判断“同一工具是否正在被多个渠道安装”。本机的既有归属如下，作为第一版基线：`codex` = npm 全局 `@openai/codex`（ChatGPT 桌面应用内置的那份标为 app-bundled、不受管、不进 PATH）；`node` / `pnpm` / `uv` / `gh` / `jq` = Homebrew；`rg` = Trae CLI 安装器；`fd` = Kimi Code 自带；`traex` 及其别名 = Trae CLI 安装器；`aiwb` = pipx。已有归属只做记录与冲突检测，本轮不做渠道迁移。

Homebrew 的 Brewfile 是软件清单，不是任意历史版本的锁文件。记录实际解析和验证过的版本；固定 revision 适用于 Skills 和可固定的发布产物。配置回滚可以保证，外部软件降级能否完成取决于其安装器，不能承诺全机器精确回滚。

## Skills and client configuration

通用用户 Skills 只安装到一个共享发现位置：`~/.agents/skills/<name>/`。上游内容从固定 revision 安装到稳定目录，避免链接到临时 worktree。工作 Mac 与 dev8c 已在使用该布局（客户端目录以符号链接复用），dev32c 需要新建。

Codex 与当前 Kimi Code 都支持共享目录，但附加字段和运行能力不同：

- 共享 Skill 以 `name`、`description` 和可移植正文为基础；不要求另一个客户端具备 Codex 专用工具、插件 ID 或命令。
- Codex 的 UI/调用策略元数据保留在其支持的文件中。Kimi 专用字段、Flow Skills、Hooks 和插件由 Kimi 自己管理。
- Kimi Code 0.39.0 的本机实际配置在 `~/.kimi-code/config.toml`。新方案使用当前版本对应的路径，不沿用旧 `~/.kimi` 教程；旧安装只在明确迁移时处理。
- ChatGPT 桌面应用的插件、连接器与账号授权通过客户端支持的机制安装和核验。复制 `.codex/config.toml` 不代表桌面应用和插件已经配置完成。
- 不将完整 Skill 合集作为基线。每个所选 Skill 记录来源、revision、目录、目标客户端和实际可用性；客户端自带 Skills 交由客户端维护。
- 第一方个人 Skills 要纳入仓库真源，不能只存在于某台机器的全局目录。工作专属 Skills 保留在私有来源。

第一方 Skill 的正文真源落在仓库 `skills/<name>/SKILL.md`，客户端差异用同目录下的 per-client frontmatter 覆盖表达 —— 一份正文，多份元数据。`steelman-grill` 是第一个按此形态纳管的 Skill：正文取 Trae 侧完整版；Codex 侧因不支持 `disable-model-invocation`，把“仅显式触发”写进 description。

重叠的工程 Skills（`grilling` / `grill-me` / `grill-with-docs`、`handoff` / `claude-handoff` 等）按实际正文与依赖逐个判断，不按名称批量删除；第一版只把已确认需要的项纳入受管基线，其余保持现状不动。

通用 Skills 可以共用正文；各客户端的 MCP、Hooks、权限和模型配置分别使用原生格式。模型和 reasoning effort 在目标机器上检查支持情况，不假定一台机器可用的模型在另一台也可用。

MCP 按客户端和用途启用，`check` 只在**同一客户端内部**判定重复（手工配置与插件配置指向同一 server），不跨客户端比较，也不互相复制插件注册文件。

工作规则继续从现有规则仓库分发；家庭机使用个人规则。本仓不建第二份规则真源，也不复制规则正文。若以后要抽出跨场景共享规则，需另行明确唯一真源，再修改原分发脚本。

内部地址、SSH 主机映射、凭据一律不进入本仓库的公共配置。

## Installation and update experience

用户入口：

```sh
bash tools/environment/bootstrap.sh --profile work-mac            # 预览（默认只读）
bash tools/environment/bootstrap.sh --profile work-mac --apply    # 应用
bash tools/environment/bootstrap.sh --profile work-mac --check    # 检查
```

`env.py` 是同一入口的直接形态，四个子命令共用同一份 Profile 解析与状态观测：

```sh
python3 tools/environment/env.py plan    --profile work-linux
python3 tools/environment/env.py apply   --profile work-linux
python3 tools/environment/env.py check   --profile work-linux
python3 tools/environment/env.py restore --backup <timestamp>
```

`plan` 是关闭写入的 `apply`，`check` 是 `plan` 加上身份与实际发现断言。三者共用同一次观测，因此“预览说会改什么”与“应用真的改了什么”不可能漂移，`apply` 跑两次也必然第二次无变更。

更新使用同一个安装入口，按仓库中审阅过的新版本重跑，不另建升级工作流。已有明确安装/更新授权时，不再引入 Plan Approval、Apply Approval、Contract Approval 等多轮确认。

执行过程应做到：

1. 检测 OS/架构、当前工具身份与版本、所有者和配置差异。
2. 展示将新增、更新、保留或冲突的项；只修改此工具管理的文件或配置键。
3. 为将修改的配置与 Skill 入口保存备份和内容摘要；只替换已管理且未被用户另外修改的内容。
4. 按选定 Profile 调用现有安装器，安装到稳定路径。账号登录、系统权限和应用授权使用各客户端原生流程，不复制另一台机器的凭据。
5. 使用实际客户端检查能力，再输出缺失项或需用户处理的事项。

受管配置一律写在带标记的块内（`# ai-workbench:<id> BEGIN` / `END`）。块外内容不读不改；块内内容若被用户手工修改过（摘要不匹配），`apply` 停下并报告，不覆盖。

备份落在 `~/.ai-workbench/environment/backups/<UTC 时间戳>/`，manifest 为 v2：逐条记录 `file` / `config_block` / `symlink` 三类操作的**安装前**与**安装后**形态。`restore` 按时间戳整批回滚，`config_block` 只回滚受管块正文（块外新增内容一字不动），安装前不存在的目标改为删除并收干净本入口新建的目录；安装后被改过的目标默认跳过并报告，`--force` 才覆盖。安装记录只保存文件归属、版本、摘要和备份路径，不包含会话、登录令牌、完整客户端数据库或账号凭据。

## What check must prove

- 在新开的登录终端和普通 SSH 非交互命令中，目标 CLI 均可执行。
- 名称与工具身份匹配，特别是 GitHub CLI 的 `gh` 冲突。
- Skills 的实际发现结果没有重复名称、断链或解析错误；不仅验证文件存在。区分安装目录、客户端可发现列表与本轮实际调用，检查显式触发设置是否被目标客户端支持。
- 客户端能解析其配置；登录/网络/模型可用性作为不同检查项，不能由版本命令成功推断。缺少配置文件本身不作为失效证据。dev32c 的 Codex 0.130.0 已于 2026-09-07 实测：在干净 `CODEX_HOME`、故意不写 `config.toml` 的条件下，仍能发现项目级（`.codex/skills` 与 `.agents/skills` 两种布局都认）、user 级与 system 级 Skill，并明确报出坏 frontmatter；客户端自己输出 `... but skills still load`。至此“缺 config.toml 导致 Skills 不生效”在 0.151.0 与 0.130.0 上均已被证伪。
- 需要的 MCP 在对应客户端能够加载；记录安装来源和负责管理它的客户端，识别同一客户端内重复的手工配置与插件配置。不要将不同客户端的插件注册文件相互复制。
- SessionStart 等受管 Hooks 不重复；规则摘要比较先剔除明确的机器路径元数据，避免将正常差异误报为内容漂移。
- 环境安装不依赖历史工作区、自动启动 AIWB Daemon 或默认运行付费模型任务。

## Delivery order and acceptance

实施顺序：**当前工作 Mac → dev8c → dev32c**。工作 Mac 既是唯一能对既有安装做完整只读对照的机器，也是所有客户端的验证机；dev8c 排在 dev32c 之前，因为它的 PATH 入口缺陷是本轮唯一“已安装但完全不可用”的硬故障，修好它才能在 dev32c 上把 `work-linux` 当成已验证基线来复用。家庭 Mac 在三台完成后单独评估，本轮标为未验证。

每台机器的收口顺序固定为：`plan` → 人工确认差异 → `apply` → `check` → 重复 `apply` 验证幂等。

第一版成功的判据：

- 三台机器的新登录终端与普通 SSH 非交互会话都能找到目标工具，且工具身份正确（`gh` 必须区分内部工具与 GitHub CLI）。
- 重复应用相同 Profile 不产生变更；单项更新只修改对应受管项，用户自定义内容保留。
- Skills 实际发现结果无重复名称、断链或解析错误。
- 配置备份与恢复经过实际验证；无法回退的软件版本明确报告。
- `aiwb` 不再指向历史 worktree，且环境入口在 `aiwb` 缺失时仍可完成安装与检查。
- 家庭 Profile 与 `home-mac` 实现不在本轮范围内，明确标为未验证。

本轮明确不做：新的守护进程、通用编排框架、多层审批流程、自动 commit / push、默认启动付费模型任务、按存活时间清理会话、跨渠道迁移已有工具安装。

## Sources

- [OpenAI: Build skills](https://learn.chatgpt.com/docs/build-skills) — shared discovery paths and native metadata.
- [OpenAI: Plugins](https://learn.chatgpt.com/docs/plugins) — supported desktop and CLI installation surfaces.
- [Kimi Code: Agent Skills](https://moonshotai.github.io/kimi-code/en/customization/skills) — shared discovery paths and Kimi-specific behavior.
- [Kimi Code: Data locations](https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html) — current data root and separation of credentials and shared resources.
- [Homebrew Bundle](https://docs.brew.sh/Brew-Bundle-and-Brewfile) — declarative package installation/update.
- [uv: Installing Python](https://docs.astral.sh/uv/guides/install-python/) — managed Python versions without replacing system Python.

## 2026-09-07 复盘修订：审查发现的四个缺陷与处理

第一版落地后复查，发现四个与本文承诺不符的行为。它们的共同根因是**「受管」只做到了写入，没做到证明归属与撤销**。修订如下，每条都有临时 HOME 里的回归用例钉住（`tools/environment/tests/regression.py`，53 项）。

| 缺陷 | 根因 | 修订 |
| --- | --- | --- |
| P1 更新 Skill 会覆盖用户修改 | Skill 写入路径没走 `config_block` 那套摘要校验，直接渲染覆盖 | 两类写入统一到同一条规则：写入前必须证明「磁盘上这份就是安装记录里的那份」，否则进 `需要人处理` 且不写。想接管只能显式 `--force`（仍备份） |
| P1 restore 丢失安装后新增的配置、首装撤不干净 | manifest v1 只存「文件旧内容」，回滚 = 整文件覆盖；且没有记录「安装前不存在」这一形态 | manifest 升级 v2：逐条记录 `file` / `config_block` / `symlink` 的**安装前**与**安装后**形态。`config_block` 改为块级回滚（块外新增内容一字不动）；安装前不存在的目标改为删除，并收干净本入口新建的目录；被撤销的组件从安装记录里销号 |
| P2 重复 Skill 被重新引入，检查器却报告通过 | 检查按「每个客户端各自的目录」扫描，而实测 Codex / Trae 会把 `~/.agents/skills` 与自家目录**合成同一个可发现集合** | 判重名改用客户端原生 `app-server` 的 `skills/list`（`skills_discovery.py`），拿不到才退回多目录聚合扫描，且**原生接口失败判错而不是判过**。同时把第一方 Skill 收敛成 `~/.agents/skills` 单副本，历史副本由 `stale_copies` 清理 |
| P1 工具缺失或版本过低时只报告 | `tool` 组件当初只做身份断言，没有任何安装 / 更新渠道 | Profile 里为已取证的渠道登记 `install_cmd` / `update_cmd` / `install_via`，缺失就装、低版本就更新，**装完重新探测版本**再判定；三者都没有则报「无已验证渠道」交给人。没取证过的渠道一律不填，宁可报错也不猜 |

配套的两个判断：

- **单副本 + 符号链接**取代「每客户端各一份」。证据：2026-09-07 用 `codex app-server` / `traecli app-server` 的 `skills/list` 实测，Mac 上 `steelman-grill` 是 85 个名字里唯一的重名项，两个客户端各看到两份。合并后的 frontmatter 同时带 `author` 与 `disable-model-invocation`：Trae 认这个键，Codex 是否认未知，但用隔离 HOME 实测 Codex 不会因未知键丢弃该 Skill；「仅显式触发」的语义仍同时写在 description 里兜底。这一条**取代**上文「Codex 侧因不支持 `disable-model-invocation` 需保留客户端差异」的判断。
- **历史副本清理的判定标准是「删掉不丢东西」**，不是「目录看起来干净」。符号链接按链接删（顺着删会毁掉真身，这是实现初稿里的真实隐患）；普通文件要么在受管副本里有逐字节相同的对应物，要么安装记录能证明它是本入口自己写下且没人动过；否则整条交给人。

### 第二轮审查（同日）：又四条 + 范围收敛

第一轮修完后复查又复现四条，同样都在临时目录里取证。修法与回归见 `tools/environment/tests/regression.py`（现 75 项）。

| 缺陷 | 根因 | 修订 |
| --- | --- | --- |
| P1 接管符号链接后 restore 还不回原内容 | `open(path, "w")` 会**顺着链接**改写它指向的文件，而备份存的是「链接指向哪」；restore 于是报成功却什么也没救回来 | 目标是符号链接时默认拒绝接管；`--force` 改为**替换链接本身**（备份 `kind=symlink`，restore 把链接接回去），绝不动它指向的文件 |
| P2 更新回滚后丢掉管理记录 | restore 一律销号 | manifest 每条记录写入前那一版的 state 条目：首装撤销销号，更新回滚**恢复上一版记录**。否则「装 v1 → 更新 v2 → 回滚 → 再更新」会把自己装的东西认成别人的 |
| P2 原生发现的部分错误被吞 | 只读 `skills/list` 的 `skills`，没读并列的 `errors` | `data[].errors` 非空即判整体失败（退出码 6）并报出错误原文；不输出残缺清单 —— 「少了几项」不能伪装成「就这几项」 |
| P2 发现超时形同虚设 | 阻塞式 `readline()` 让外层 deadline 完全失效 | 改成 `select` + 截止时间的可中断读取（`AIWB_DISCOVERY_TIMEOUT` 可调），子进程 terminate → kill → wait 收干净；服务端一直不出声也不会挂死 |

两条边界随之写死：

- **能力范围**：当前只能称为**三台现有机器的维护入口**。Linux 侧 `codex` / `uv` / `rg` 的首次安装渠道尚未取证登记，干净机器上这三项会报「无已验证渠道」。称它为完整的新机搭建入口，得先在干净机器上实测出渠道。
- **去重口径**（用户拍板）：按客户端可发现集合去重。指向同一真实目标的**符号链接别名可以接受**；**同名的独立副本即使内容逐字节相同，也继续报冲突**。外部进程重建副本一事当前未复现，不因此停掉未知进程，等确认来源后再处理分发方。
