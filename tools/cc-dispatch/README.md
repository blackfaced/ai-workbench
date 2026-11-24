# cc-dispatch

派发 Claude Code 会话到其他目录，并在会话之间传递任务和结果。

## 它解决什么

`claude --bg` 的 worker 由常驻 daemon 拉起。daemon 在首次启动时继承启动它的那个
进程的环境变量，之后所有 worker 复用同一份。如果 daemon 是从一个把
`ANTHROPIC_BASE_URL` 指向本地转发代理的 shell 里启动的：

1. 该代理端口随原进程退出而失效；
2. daemon 仍把已死地址传给每一个新 worker；
3. worker 表现为 `Connection refused (ECONNREFUSED)` 无限重试，零输出。

任何「本地中转代理 + daemon 复用」的组合都会中招，与具体客户端无关。因此派发时
必须显式给出长期可达的 provider 配置，而不是继承。

第二个风险是续跑跑错仓。把 A 仓的会话在 B 仓目录 `--resume`，CLI 不报错，会话会
静默在 B 仓里运行——它仍以为自己属于 A 仓。本工具在续跑前核验 session 归属目录。

## 固定版本本机安装

安装 owner 为 AIWB，复用环境 installer 的本地所有权记录、原子写入和锁。
本入口只安装工具与用户明确选择的 Claude user-global Skill；不会改其他 harness、
项目上下文、信任或权限设置。这是本机跨仓工具的显式全局选择，不改变其他 Skill 的
项目级激活默认值。

先让待安装源码成为一个本地固定 commit，再把完整 40 位 SHA 填入命令；未提交修改
不会进入安装包。不需要 push。默认 plan，只读；显式 apply 才安装。

```bash
SOURCE=/absolute/path/to/ai-workbench
COMMIT='<full-40-character-commit-sha>'
python3 -I "$SOURCE/tools/environment/install_cc_dispatch.py" --source "$SOURCE" --commit "$COMMIT"
python3 -I "$SOURCE/tools/environment/install_cc_dispatch.py" apply --source "$SOURCE" --commit "$COMMIT"
python3 -I "$SOURCE/tools/environment/install_cc_dispatch.py" check --source "$SOURCE" --commit "$COMMIT"
```

source 必须是已有本地 Git 仓；只读固定对象，禁用 lazy fetch，不 clone/fetch、不跟随
`main`。导出固定白名单：工具入口、实现、README、配置示例、Skill 与 Apache-2.0 LICENSE。
每个文件保留 Git 模式并记录 SHA-256；不复制工作树内容或 gitignored 配置。

release 在 `~/.local/share/cc-dispatch/releases/<commit>/`；全局 wrapper
`~/.local/bin/cc-dispatch` 指向该 release，Skill 通过 `~/.claude/skills/cc-dispatch`
发现。将 `~/.local/bin` 放在 PATH 后可在任意 cwd 使用。wrapper 每次运行先校验
release 的文件集、SHA、模式、manifest 和符号链接边界；漂移直接拒绝。
installer 的 `check` 只校验安装身份，不读取 provider 配置或启动会话。
已有非本 owner 的入口/Skill 或用户编辑会阻止接管；先由用户处理冲突，不强制覆盖。
激活绑定观察时的 wrapper 摘要、Skill 链接目标与安装记录；写入 / unlink 前复验。
失败时仅补偿仍匹配本次写入的值，保留外来修改；这不是跨文件原子事务。POSIX 下
非协作编辑仍可能落在最后一次比较与 rename / unlink 之间，无法保证消除该窗口。
升级保留旧 release 和 `previous-installation.json`；可用旧 SHA 显式 apply 恢复，
前提是当前受管内容未漂移。源码仓仍须保有被选版本的本地对象。

## 配置

代码里不写死任何地址。查找顺序：

1. `$CC_DISPATCH_CONFIG`
2. `<repo>/tools/cc-dispatch/config.json`（本机，已 gitignore）
3. `~/.claude/dispatch/config.json`

全局安装仅从 `$CC_DISPATCH_CONFIG` 或 `~/.claude/dispatch/config.json` 读取凭据；
release 不含本机配置。仓内开发仍保留上述查找顺序。

```bash
mkdir -p ~/.claude/dispatch
# 在 ~/.claude/dispatch/config.json 配置自己的 provider；参考 config.example.json
```

`auth_token` 可以直接写，也可以用 `auth_token_env` 指向一个环境变量名，避免明文落盘。
`base_url` 指向本机端口会被拒绝——那类地址活不过宿主进程。

## 用法

```bash
# 检查配置，不启动任何会话
cc-dispatch check

# 新建后台会话并立刻开始
cc-dispatch start <目录> <名字> <任务>

# 续跑已有会话（会核验目录归属）
cc-dispatch resume <session-id> <目录> <任务>

# 列出后台会话：id / 状态 / 名字 / 目录
cc-dispatch list

# 使用配置里另一个 provider
cc-dispatch --provider alt start <目录> <名字> <任务>

# 调整后台会话的权限模式（见下节）
cc-dispatch --permission-mode bypassPermissions start <目录> <名字> <任务>
```

`start` 返回短 id，会话随即出现在 `claude agents` 里。之后用客户端原生列表核验
peer 地址与实际 cwd，再用跨会话消息工具继续对话；同名条目用返回标识消歧。

## 权限模式

后台会话没有终端，遇到权限确认弹窗时**没有人能按键**，会话会停在 `waiting` 直到
被杀掉。因此派发时必须显式指定权限模式，默认 `dontAsk`：

| 模式 | 行为 | 适用 |
| --- | --- | --- |
| `dontAsk`（默认） | 不需要授权的动作照常执行；需要授权的**直接拒绝**而不是卡住 | 大多数派发任务 |
| `acceptEdits` | 文件编辑自动接受，其余仍需授权 | 以改代码为主的 worker |
| `bypassPermissions` | 全部放行 | 沙箱或已完全信任的目录 |
| `plan` | 只读规划 | 先出方案再决定 |

选 `dontAsk` 时，worker 可能因某个动作被拒而完不成任务——它会如实报告被拒的动作，
而不是静默卡住。只有用户直接批准其他权限模式后才显式选择；派发消息不扩写授权。

## 边界

- **工具寻址与目标能力分开核验**。已测 `cli` 交互 / 后台样本可收发；已测 `sdk-ts`
  嵌入样本未收到消息且 transcript 不在本工具读取的 CLI 路径下，不能由本工具恢复。
  这不代表所有 `sdk-ts` 目标；`entrypoint` 仅作线索。本工具依赖 CLI transcript 与后台
  短 id，已测交互列表条目缺少该 id 是工具限制，不是原生路由禁令。逐目标核验原生
  地址、实际 cwd、版本和入站能力，分别取得送达、处理与匹配回报；发送 ACK 不算完成。
  交互权限弹窗由人处理。
- **创建/恢复与消息是两种操作**。未显式选择其他流程时，跨仓创建/恢复默认用本工具；
  已核验 live peer 地址与 cwd 后，后续消息可走原生工具。用户选择其他 harness 或指定
  Claude 原生通信 / 原生 resume 时沿用所选流程，缺少本工具不阻挡显式选择；
  同仓 subagent 和简单只读工作不需派发。授权边界见 [Skill](../../skills/cc-dispatch/SKILL.md#授权边界)。
- **运行中的 worker 不能 resume**。先 `claude stop <id>`，或 `claude attach <id>`
  进入它的终端继续。
- **未信任目录不能起 worker**。`claude --bg` 会直接拒绝；`resume` 走 `-p` 模式，
  跳过信任弹窗可以跑。
- **会话名不能含 `/` 或空白**。名字是跨会话消息的寻址键，带分隔符会难以定位。
- **`resume` 也校验目录存在**。目录不存在时报"目录不存在"，不会把 cwd 错误误报成
  找不到可执行文件。
- **worker 无响应时**先看 `claude logs <id>`。出现 `Connection refused` 说明环境
  被污染——不要手工 `claude --bg`，用本工具。若看到权限确认弹窗且状态是 `waiting`，
  说明用了过强的权限要求，杀掉后用 `--permission-mode` 调整。

## 测试

```bash
python3 tools/cc-dispatch/test_cc_dispatch.py
python3 tools/cc-dispatch/test_install_cc_dispatch.py
python3 tools/environment/tests/regression.py
```

只依赖标准库，兼容 Python 3.9；在临时目录里跑，不碰真机配置，不联网。
