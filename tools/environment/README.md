# tools/environment — 个人开发环境的安装 / 更新 / 检查入口

一份实现（`env.py`，只用标准库、Python 3.9 兼容）+ 一个薄壳（`bootstrap.sh`，只负责在新机器上找到
`python3` 并转发参数）。设计依据见 [`decisions/0009-reproducible-development-environments.md`](../../decisions/0009-reproducible-development-environments.md)。

## 三条命令

```sh
sh tools/environment/bootstrap.sh --profile work-mac            # 预览（默认只读）
sh tools/environment/bootstrap.sh --profile work-mac --apply    # 应用
sh tools/environment/bootstrap.sh --profile work-mac --check    # 检查
```

等价的直接形态（多一个 `restore`）：

```sh
python3 tools/environment/env.py plan    [--profile P] [--only ID ...] [--force]
python3 tools/environment/env.py apply   [--profile P] [--only ID ...] [--force]
python3 tools/environment/env.py check   [--profile P] [--only ID ...]
python3 tools/environment/env.py restore --backup <UTC 时间戳> [--dry-run] [--force]
```

- `--profile` 缺省时按 OS + hostname 判定（`Darwin` → `work-mac`；`Linux` + hostname 命中
  `work-linux.json` 的 `hosts` → `work-linux`）。判不出来直接报错退出，不猜。
- `--only ID` 把观测与写入都限制在该组件上，用于单项更新。
- `--force` 是**唯一的接管入口**：明知目标「不是本入口装的 / 安装后被改过 / 历史副本内容对不上」，
  仍然覆盖或删除。它不跳过备份，每个被动的文件照样进 manifest，`restore` 能原样撤回；
  `check` 故意**没有** `--force`——它的职责是如实报漂移，不是把漂移说成没事。
- 退出码：`plan` 恒为 0；`check` 有漂移为 1；`apply` 有「需要人处理」的项为 1 —— 这类项本身不产生
  写入，所以其余可执行的改动照常执行（若相反，`~/.local/bin` 不可见的机器会锁死：修它的受管块
  永远写不进去）。写入仍逐组件受各自的冲突检测约束。
- 三个动词共用同一份 Profile 解析与**同一次 observe**：`plan` 就是关闭写入的 `apply`，`check` 是
  `plan` 加只读断言。所以「预览说会改什么」和「应用真的改了什么」结构上不可能漂移，`apply`
  跑第二次必然无变更。

## 写入前的归属证明（config_block 与 skill 共用一条规则）

任何覆盖动作发生前，先回答一个问题：**现在磁盘上这份，是不是我上次留下的那份？**

- 安装记录里没有它 → 「不是本入口装的」，停手；
- 记录里有但 sha256 对不上 → 「安装之后有人改过」，停手。

两种情况都进 `需要人处理`，`apply` 以 1 收尾且不写。想接管就显式加 `--force`（仍备份）。
这条规则让「更新 Skill 把用户的手工修改冲掉」在结构上不可能发生。

**目标本身是符号链接时另有一条规则**：默认不接管。顺着链接写，改的是链接之外那个文件，而备份只存得下
「链接指向哪」—— `restore` 会一脸无辜地报成功，被改写的那份原内容却已经没了。`--force` 时改为**替换链接
自己**（备份 `kind=symlink`，`restore` 把链接原样接回去），绝不去动它指向的文件。

## 受管边界

Profile（`profiles/*.json`）声明 4 种组件，没有第 5 种：

| 类型 | 管什么 | 边界 |
| --- | --- | --- |
| `config_block` | 文本配置里 `# ai-workbench:<id> BEGIN/END` 之间的块 | 块外内容不读不改；块内被手工改过就停下报告；`insert_before_re` 命中不到时报错，绝不盲插 |
| `tool` | 一个受管可执行文件的**归属与身份** | 缺失且 Profile 登记了已验证的 `install_cmd` → 装；版本低于 `min_version` 且登记了 `update_cmd` → 更新，装完/更新完**重新探测版本**再判定；`install_via` 表示它由本次计划里的某个 installer 兜底；三者都没有就报「无已验证渠道」，交给人。不做渠道迁移、不承诺降级 |
| `skill` | 第一方 Skill 的一份正文 + 每客户端 frontmatter（可带 `files` 附带文件） | 渲染 = `clients/<client>.frontmatter.md` + `SKILL.md` 正文；`files` 用来带客户端专属的界面/策略描述（如 Codex 的 `agents/openai.yaml`）；依赖不满足就跳过并说明原因；`stale_copies` 见下 |
| `installer` | 包住一个已存在的安装器 | v1 只有 macOS 的 `brew bundle`，`--no-upgrade`：只保证「装了」，不隐式升级 |

### 为什么 Skill 只装一份

2026-09-07 用 `codex app-server` / `traecli app-server` 的 `skills/list` 实测：两个客户端都把
`~/.agents/skills` 与自家目录**合成同一个可发现集合**。所以「每个客户端各放一份」必然在两边都变成
重名。现在第一方 Skill 只写 `~/.agents/skills` 一份，Claude Code 用符号链接接进去。

`stale_copies` 负责清掉历史上散落的副本，判定规则是「删掉不丢东西」：

- 是符号链接 → 按链接删，**绝不顺着它 listdir/unlink 到真身**；
- 目录里每个文件都能在受管副本（含本次将要写入的形态）里找到逐字节相同的对应物 → 删（仍逐个备份）；
- 或者安装记录能证明这份就是本入口自己写下、之后没人动过的 → 删（旧 Profile 留下的每客户端副本走这条）；
- 否则整条 block，交给人；确认无所谓再 `--force`。

`check` 另有三项只读检查（不改任何东西）：

1. **hook 重复**：读 Profile `clients` 段声明的配置文件，按 (event, 归一化 command) 报重复。归一化会
   先剔除机器路径元数据（如 `~/.trae/l1/<hash>/`），避免把正常差异误报成漂移。
2. **Skill 发现**：目录级卫生（断链、缺 `SKILL.md`、frontmatter 能否解析、`name` 与目录名是否一致）+
   **按客户端可发现全集判重名**。可发现全集优先走客户端原生接口（`discovery_cmd`，即
   `skills_discovery.py <codex|traecli>` 调 `skills/list`），拿不到才退回 `discovery_dirs` 聚合扫描；
   **原生接口失败会判错，不会静悄悄当通过**。「失败」包含三种：起不来 / 超时 / JSON-RPC error，以及
   **响应成功但 `data[].errors` 非空**——那说明有 Skill 解析失败，这份清单是残缺的，照常输出剩下的等于
   把「少了几项」伪装成「就这几项」，所以整体判失败（退出码 6）并把错误原文报出来。超时用可中断读取
   实现（`select` + 截止时间，默认 45s，`AIWB_DISCOVERY_TIMEOUT` 可调），子进程 terminate → kill → wait
   收干净，服务端一直不出声也不会挂死。
   **去重口径（2026-09-07 用户拍板）**：指向同一真实目标的符号链接别名可以接受，不算重复；同名的独立
   副本**即使内容逐字节相同也继续报冲突**。
   三个概念分开报：安装目录数 / 客户端可发现数 / 本轮实际调用（后者需在客户端里看，本工具不驱动会话）。
3. **用户自定义 PATH 行**：只列出行号与原文。Mac 的 `~/.zshrc` 重复导出 `$HOME/.local/bin` 属用户
   自定义内容，**只报告，不去重、不改写**。

不受管、也不复制正文的东西：

- **codebase-memory 的 SessionStart 提示**：Codex（`~/.codex/config.toml` 内联 echo）与
  Claude（`~/.claude/hooks/cbm-session-reminder` 脚本）有两份不同正文，owner 都是
  **codebase-memory-mcp**。规则来源在它那里，本仓不复制、不改写这两份正文——改了会被它下次安装覆盖，
  也会造出第二真源。本入口只做过语义等价的整理：把 Claude 侧 4 个注册同一条命令的 SessionStart 组
  合并成 1 组（matcher `startup|resume|clear|compact`，与 Codex 侧一致）。
- **工作规则**（`~/.codex/AGENTS.md`、`~/.trae/AGENTS.md` 及其 hook 块）由外部规则仓的分发脚本维护，
  本仓不建第二份真源。
- **VibeBuddy / Trae CLI / Kimi Code / ChatGPT 桌面应用**自己安装的东西：只记录归属、检测冲突。

## 备份与恢复

备份 manifest 是 **v2**：不再只记「文件的旧内容」，而是逐条记录一次 apply 做了什么。

- 三种条目：`file`（含新建与删除）、`config_block`（记 `begin/end`、`previous_body`、
  `applied_body`、是否为它插过空行）、`symlink`（记 `link_target`）。
- 每条都记「安装前长什么样」与「安装后长什么样」，因此 `restore` 能分辨：
  - 安装前不存在 → 删掉它，连同本入口新建的目录一起收干净（首次安装可完整撤销）；
  - 安装前存在 → 还原旧内容，并打印 sha256 对照。
- **块级回滚**：`config_block` 只比对受管块的正文。安装之后你在同一个文件别处新加的行，
  `restore` 一个字都不会动 —— 这也是它不套用整文件 sha 判定的原因。
- **安装后被改过的目标默认跳过**并逐条报告；确认要覆盖再 `restore --force`。
- **安装记录跟着一起回滚**：每条 manifest 记录写入前那一版的 state 条目。首装撤销 → 销号；更新回滚 →
  **恢复上一版记录**。一律销号的话，「装 v1 → 更新 v2 → 回滚 → 再更新」的最后一步会把自己装的东西
  误判成「不是本入口装的」。
- v1 备份不再被本版 `restore` 接受（明确报错，让人手工比对），避免用旧语义猜新形态。
- 安装记录 `~/.ai-workbench/environment/state.json`：受管项 id → `{path, sha256_after_apply,
  version, owner, backup_dir, applied_at}`。**不存会话、令牌、客户端数据库、凭据。**
  被 `restore` 撤掉的组件会从记录里销号，下一次 `plan` 回到「待安装」而不是「被改过」。
- **能保证的是配置回滚**。外部软件能不能降级取决于它自己的安装器，本入口不承诺降级，只在 `check`
  里把版本差异报出来。

## 回归测试

```sh
python3 tools/environment/tests/regression.py
```

全程在临时 HOME + 临时仓库副本里跑，**不碰真机配置**，只用标准库。六组用例分别钉住：
① 写入前的归属/摘要校验；② restore 的块级回滚、首装完整撤销、安装后改动保护；
③ 按客户端可发现全集判重名（含原生接口失败必须判错）；④ 工具缺失要装、版本低要更新；
⑤ 历史副本清理不许丢东西、`--force` 接管后仍能原样撤回；⑥ 符号链接目标的接管与还原、更新回滚后
安装记录仍认得出自己、原生发现的解析错误要传播、超时要真的超时且不留孤儿进程。
任何一条不过即非 0 退出（当前 75 项）。CI 在 Ubuntu（Python 3.11 / 3.9）与 macOS（Python 3.11）运行同一套测试，不安装额外 Python 依赖。

## 当前能力范围（别把它当成新机搭建入口）

已验证的是**三台现有机器的维护**：漂移检查、受管配置与 Skill 的安装/更新/回滚、已有工具的版本更新。

**尚未覆盖新机首装**：Linux 侧 `codex`、`uv`、`rg` 的首次安装渠道还没取证登记（`install_cmd` 留空），
一台干净的 Linux 机器跑 `apply` 会在这三项上报「无已验证渠道，交给人」。要它成为完整的新机搭建入口，
得先在一台干净机器上实测出这三条渠道再登记。

## 每台机器的差异

| | work-mac | work-linux（dev8c / dev32c 共用） |
| --- | --- | --- |
| shell | `/bin/zsh` | `/bin/bash` |
| 功能性修复 | 无（`~/.local/bin` 已在 PATH） | `path-user-local-bin` 写进 `~/.bashrc` 的非交互守卫**之前** |
| 包清单 | `packages/macos.Brewfile`（node/uv/gh/pipx/python@3.11/fzf/wget） | 无：保留现有系统包与用户态安装 |
| `gh` | 只有 GitHub CLI 一份 | 两个组件分别断言 `/usr/bin/gh` 是 GitHub CLI、`/usr/local/bin/gh` 是内部主机查询工具；不改优先级、不卸载、不 alias，调用 GitHub CLI 时显式使用 `/usr/bin/gh` |
| `steelman-grill` | 一份装在 `~/.agents/skills`，`~/.claude/skills` 走符号链接；`~/.codex/skills`、`~/.trae/skills` 的历史副本已清 | 同样只装 `~/.agents/skills`；依赖 `grilling` 缺失时跳过并报原因（dev32c 正是如此） |
| `uv` 更新渠道 | `brew upgrade uv` | 按实际渠道分流：`~/.local/pipx/venvs/` 下的用 `pipx upgrade uv`，否则 `uv self update` |

Brewfile 只登记实测确认归 Homebrew 所有的 formula。**`ripgrep` 不在里面**（`rg` 归 Trae CLI 安装器），
`jq`（系统 `/usr/bin/jq`）和 `pnpm`（brew node 里的 corepack shim）同理——写进去就是新造一个多渠道冲突。

`tool` 的 observe 会在**登录 shell**（`-lc`）与**非交互 shell**（`-c`）两种上下文分别解析并分别报告。
本地的非交互上下文继承调用者环境，**不等于真实 SSH 会话**：Linux 机器的权威证据是
`ssh <host> 'command -v codex uv rg'` 与 `ssh <host> 'bash -lc "command -v codex uv rg"'` 都命中。
