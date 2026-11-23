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

## 配置

代码里不写死任何地址。查找顺序：

1. `$CC_DISPATCH_CONFIG`
2. `<repo>/tools/cc-dispatch/config.json`（本机，已 gitignore）
3. `~/.claude/dispatch/config.json`

```bash
cp config.example.json config.json
# 编辑 config.json 填入自己的网关地址与模型
```

`auth_token` 可以直接写，也可以用 `auth_token_env` 指向一个环境变量名，避免明文落盘。
`base_url` 指向本机端口会被拒绝——那类地址活不过宿主进程。

## 用法

```bash
# 检查配置，不启动任何会话
./cc-dispatch check

# 新建后台会话并立刻开始
./cc-dispatch start <目录> <名字> <任务>

# 续跑已有会话（会核验目录归属）
./cc-dispatch resume <session-id> <目录> <任务>

# 列出后台会话：id / 状态 / 名字 / 目录
./cc-dispatch list

# 使用配置里另一个 provider
./cc-dispatch --provider alt start <目录> <名字> <任务>

# 调整后台会话的权限模式（见下节）
./cc-dispatch --permission-mode bypassPermissions start <目录> <名字> <任务>
```

`start` 返回短 id，会话随即出现在 `claude agents` 里。之后按名字用客户端的跨会话
消息工具继续对话，不必再走脚本。

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
而不是静默卡住。需要它自主完成更多操作时，按上表换成更强的模式。

## 边界

- **worker 必须是后台会话**。编辑器内嵌 agent（非终端入口）的会话不在 CLI 的会话
  体系里，收不到跨会话消息，也 `--resume` 不到。
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
python3 test_cc_dispatch.py
```

只依赖标准库，兼容 Python 3.9；在临时目录里跑，不碰真机配置，不联网。
