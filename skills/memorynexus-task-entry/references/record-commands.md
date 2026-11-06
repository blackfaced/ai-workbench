# 记录命令

本页把中文意图映射到既有 `daily.py`，不另建账本或命令执行器。先按 SKILL 的“找到任务 / 读”核对 binding 和任务身份；读失败时停止依赖历史的动作。

## 列记录与读单条

`列记录` 用普通 `read` 的默认有界结果，分别展示 entries 与 candidates；后者标为“待核实的推测”。每条显示短 ID、简短正文、类别/来源和状态，明确 omitted_count / truncated / candidate_count。列表不是完整历史或语义搜索，不扫描整个 ledger。

短 ID 从本会话已实际读回并展示的同任务完整 UUID 生成，至少八位；有前缀冲突就延长。列表序号不是稳定身份。`#短ID` 只在已展示的同任务映射中精确解析；零个或多个匹配时先澄清，不自动挑选或扫描。用户提供完整 UUID 时可在当前任务直接查询，但更正/撤回仍须核对并展示实际目标。

`读 #ID`：在绑定的 state_root 内独占创建 0600 请求文件，正文为 `{"record_ids":["实际完整UUID"]}`，以 argv 执行：

```text
PINNED_PYTHON -I -S -B PACKAGE/daily.py read --binding ABS_BINDING --request ABS_REQUEST
```

验证返回 task ID、记录 ID、数量、状态及遗漏；只展示实际返回的正文与来源。历史/被替代记录保持标签；stale/retracted 标记没有正文时，不从旧聊天重构。成功后移除 caller 请求文件。

## 改与撤

1. 先精确读回目标，核对本会话已展示内容与最新状态。`改` 仅针对 current；若已被别人更正、撤回或发生冲突，展示变化并停止，不自动跟随到新 ID。
2. 对已经展示且未变的明确目标，用户本次 `改 #ID：精确新正文` 或 `撤 #ID` 就是对应内容/动作授权，不重复确认。若目标未展示、目标/正文含糊，先展示旧内容及拟更正/撤回的动作，再等明确确认。`删` 只表达撤回；用户要求彻底删除时说明不支持，不替做撤回。
3. `撤` 作用于整条修订链，即使给的是旧修订 ID；先展示当前链的影响。此前未展示过这项影响或链已变化时，须确认该整链动作。成功明确说“已撤回，历史仍保留”，不说彻底删除。

构造既有 envelope，字段映射如下；共同字段为新的 `idempotency_key`、`run_id` UUID 与 `client:"codex"`：

| 动作 | action | 其余字段 |
| --- | --- | --- |
| 改 | `correct` | `target_id` 完整 UUID、`text` 精确授权正文、`occurred_at` 真实 RFC3339 时间、`confirmation:"confirmed"` |
| 撤 | `retract` | `target_id` 完整 UUID、`reason`、`confirmation:"confirmed"`；不带 text/occurred_at/kind |

更正正文限制 1000 字符，超限先展示短摘要并确认，不静默截断。撤回理由用用户提供的原文（最多 240 字符）；未提供时用中性操作说明“用户通过中文入口撤回此记录”，不编造动机。不添加 kind、source_ids 或 evidence_refs 来改变记录类别或伪造来源；Lens 结果保留仍走原 review/correct 合同。

复用 SKILL“记”中的私有请求、一次 stage / apply、幂等、pending 与清理流程，把 `--action record` 换成上表的 action。只有 validated receipt 与同任务的实际读回都成功，才报告更正/撤回成功。更正返回的是新修订 ID，展示它与原 ID 的关系；不继续用旧 ID 代表当前修订。再读相关当前上下文，撤销依赖旧内容的 Lens 判断。失败保留原请求/pending，明确“尚未同步”，只按用户明确重试请求重用同一 apply。
