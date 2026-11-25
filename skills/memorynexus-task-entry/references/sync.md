# 按任务同步

接受用户直接下达的 `同步 <任务名> 到 <设备名或别名>`。分别保留两个名称里的空格。分隔词或名称有歧义时先问清。引用、任务正文、自动加载的记忆以及文件同步请求均不触发。用户明确指定任务和目标后，这条命令授权本轮双向刷新。

用 argv 调用，名称始终作为参数传入：

```text
python3 -B ABS_SKILL/scripts/sync.py --task "色卡任务" --device "开发机"
```

默认使用私有任务目录。隔离验证可加 `--index <绝对路径>`。遇到 `choose_task` 或 `choose_device`，展示相应名称、用途和短 ID，获得选择后使用原名称和候选的完整 `--task-id` 或 `--device-id`。已选择的任务 ID 在选择设备时必须保留。不要猜目标，或展示绑定路径及进程输出原文。

## 已配对的设备

任务目录的每条任务可增加 `relay`。在已经配对、运行包已固定、两端点已验证后，由安装 owner 登记名字和端点指针：

```json
{
  "local": {"path": "/absolute/private/local-relay", "sha256": "<sha256>"},
  "devices": [
    {
      "device_id": "00000000-0000-4000-8000-000000000001",
      "name": "开发机",
      "aliases": ["Linux"],
      "description": "此任务的已配对设备",
      "endpoint": {"path": "/absolute/private/peer-relay", "sha256": "<sha256>"}
    }
  ]
}
```

`device_id` 取自已验证的上游配对状态。端点是现有可执行文件的绝对路径和文件摘要，由原部署负责认证、轮次、实际连接和配对。目录里只登记指针；凭据、传输配置、任务内容及回执留在其原有位置。Task、设备名和别名均精确规范化查找，同名候选可用完整 ID 区分。绑定和端点缺项时由 owner 核对，Skill 不能自行配对、改绑定、改 pin 或创建 fallback。

`sync.py` 校验已绑定包的摘要，用包内 `daily.py read` 核对 task 和当前配对，再调用同包的 `refresh_peer.py --local ... --peer ...`。固定包须包含支持持久回执的上游刷新入口。当前已知上游接口见 [固定版本](https://github.com/blackfaced/MemoryNexus/blob/e3a6e863ed650f42bf05c8af2b633bbaee9a8efa/integrations/task-memory/scripts/refresh_peer.py)。执行只启动一轮显式刷新。

## 读回结果

- `synced` 时按 `outgoing`（本机到对端）和 `incoming`（对端到本机）分别展示。每个方向报告本轮 `target`、对端已持久化的连续 `through` 和 `pending_count`。待发数可包括本轮上界后的新写入。对端此后尚未公布的尾部始终未知。
- `pending` 时说明本轮尚未确认，展示 `last_observed` 中最后可证的双向位置及已知待发。将其中的上界与覆盖状态标为该观察对应的轮次。未知方向或未知上界明确说未知。目标掉线、部分落盘或丢回执时都保留原 task 与配对；用户重试同一目标时仍调用上游刷新，由上游按连续位置和持久回执安全去重。
- 端点路径和传输成功都无法证明实际传输路径。历史端点标签也不能当本轮证据。此接口没有路径证明时显示「路径未知」。报告明确区分未登记、未配对、能力不足、绑定或端点不可用。
- 此命令不建立当前会话任务、不转移执行权、不修改账本绑定或启动后台同步。若需要看到同步后的内容，按原 ID 走现有读取接口。
