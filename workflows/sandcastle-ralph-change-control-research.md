# Sandcastle、Ralph 与变更控制对 AI Workbench 的启发

## 结论

AI Workbench 不应引入 Sandcastle 作为第二套编排内核，也不应复刻 Ralph
循环。当前不可替代的优势是：批准后的 `ExecutionSnapshot`、单一
`RunLedger`、Admission、租约与 fencing、Harness 机器门禁和可恢复的
Daemon。更有价值的下一步，是在这些边界内增加显式的变更控制契约。

## 三份材料各自解决什么

### Sandcastle：组合与隔离执行

Sandcastle 是 TypeScript 编排库，提供 Agent provider、sandbox provider、
worktree/branch strategy、生命周期 hook、有限迭代、session resume、结构化
输出，以及 planner/implementer/reviewer 等模板。它适合快速组装并行 Agent
流水线，但 workflow 语义主要由脚本和 prompt 持有。

可借鉴：

- provider 与 sandbox 分离的窄接口；
- schema 校验的 Agent 输出和只重试“重新输出结果”的低成本恢复；
- 显式 branch strategy、超时、取消、保留 worktree 和 iteration result；
- workflow template 作为示例，而不是框架内的隐式魔法。

不直接采用：

- 将 TypeScript 包接入 Python AIWB 会增加 Node 运行时和第二套生命周期、
  状态及恢复权威；
- `merge-to-head` 不符合 AIWB 不合入目标分支的边界；
- prompt 文件中的动态 shell 展开发生在 sandbox ready 之后，不能替代
  Admission 冻结的执行输入；
- completion signal 只能结束模型循环，不能证明验收通过；
- Docker/Podman/Vercel 隔离不应成为 AIWB 的默认前提。若以后确有强隔离
  需求，可把 Sandcastle 做成可选实验 Adapter，而不是核心依赖。

### Ralph：短反馈循环

Ralph 的核心不是一个框架，而是一种运行策略：单进程、每轮只做一个事项、
每轮重新分配较短上下文，依靠规格、计划、代码、测试和 Git 留下跨轮状态，
再用编译、测试、静态分析等快速 backpressure 纠偏。

可借鉴：

- 一个 Todo、一个可验证 slice、一个 checkpoint；
- 新上下文只接收当前 Todo、最近 checkpoint、失败 Evidence 和相关 diff；
- 每个 slice 先跑最小相关门禁，再进入更大的 Candidate 门禁；
- 将反复踩坑的稳定知识沉淀到项目指导中，而不是依赖会话记忆。

不直接采用：

- `fix_plan.md`、无限 prompt loop 或模型自选无限范围不应成为 AIWB 的状态
  权威；
- 不采用“多跑几轮最终一致”的正确性假设；
- 不允许发现相邻问题后自动扩大当前 ticket；
- 原作者明确将该方法定位为更适合 greenfield，并警告既有代码库风险。

### 附件建议：变更控制层

附件指出的缺口真实存在。AIWB 已冻结批准输入并限制测试路径、命令、资源和
生产环境，但还没有一个统一对象来表达和执行下面这些边界：

- 允许和禁止修改的代码范围；
- 哪类设计决定可以自行做，哪类必须停止并重新批准；
- 预期文件、最大文件数或 diff 上限；
- 新依赖、新公共类型、新配置、新后台生命周期等复杂度增量；
- Requirement -> Test -> Change -> Evidence 的映射。

## 推荐领域模型

在批准 Contract 中增加 `change_control`，并由 Admission 原样冻结到
ExecutionManifest：

```yaml
change_control:
  scope:
    allowed_paths: []
    forbidden_paths: []
  decisions:
    max_level: L2
    stop_on: [public_api, persistence_schema, external_dependency, new_runtime]
  diff:
    expected_paths: []
    max_changed_files: 8
    max_net_lines: 400
  complexity:
    allow_new_dependencies: false
    allow_new_config: false
    allow_new_background_processes: false
  traceability:
    required: true
```

执行前由 Agent 生成 schema 校验的 `ChangePlan`，只描述计划修改的文件、
预期决定、概念增量、风险和 Requirement/Test 映射。它不是授权，不能扩大
Contract。实际 diff 在每个 checkpoint 经过确定性检查：路径、依赖清单、
文件数、行数和明确的 stop trigger 超界时，Run 进入
`scope_change_required` 或 `change_budget_exceeded`，并保留 Evidence。

最终 Candidate 生成 typed `ScopeReviewResult`：

- `verdict`: pass / reapproval_required；
- `unmapped_requirements`；
- `unmapped_changes`；
- `unexpected_concepts`；
- `budget_violations`。

不要永久保存易漂移的精确行号作为主身份。优先使用 acceptance ID、test ID、
commit、path 和 symbol；展示时再解析行号。

## 成本控制

附件建议的独立“过度设计 reviewer”不应无条件追加到每个 Todo。当前
`AgentResult` 仍以自由文本为主，Verifier 的真正放行条件是机器 Harness；
再加一个不能阻断状态转移的 LLM reviewer 只会增加调用次数。

建议：

- 每个 checkpoint 都跑确定性变更预算检查；
- 普通变更只在最终 Candidate 做一次 typed scope review；
- 只有高风险或真实越界时增加独立 reviewer/rework；
- structured-output 格式错误只恢复原 session 重新输出，不重做研究与实现。

## 与当前 #43 的关系

先完成 #43 及 #46-#53 的 RunLedger 完整切换，不扩大正在进行的重写。
变更控制应作为后续独立 ADR/PRD：

1. Contract/ExecutionManifest 的 `change_control` 与 typed `ChangePlan`；
2. checkpoint 处的确定性 scope/diff/complexity gate；
3. Requirement-Test-Change-Evidence trace 与 typed `ScopeReviewResult`；
4. 只有在出现明确强隔离需求时，再做 Sandcastle optional Adapter spike。

后续设计确认采用 Planner、Worker、Reviewer 三个 Role Profile，并把测试编写、实现、测试执行、诊断和返工作为 Worker Assignment，而不是增加 Test Designer 等新角色。Ralph 的短上下文和快速反馈由 Development Doctrine、Change Plan、分层 Harness 和 RunTrace 约束；Planner 处理失败反馈及重新分配，Daemon 继续拥有状态转移和 Evidence。

另外，`tools/agent-orchestrator/skills/run-approved-goal/SKILL.md` 仍声称同一
Contract hash 会被去重并作为恢复；当前 README 和 #43 的语义是每次提交创建
独立 Run，除非显式 idempotency key。该文档应先做一个窄修复。

## Primary sources

- Sandcastle repository and README: <https://github.com/mattpocock/sandcastle>
- Sandcastle structured output ADR: <https://github.com/mattpocock/sandcastle/blob/main/docs/adr/0010-structured-output.md>
- Sandcastle templates: <https://github.com/mattpocock/sandcastle/tree/main/src/templates>
- Geoffrey Huntley, “Ralph Wiggum as a software engineer”: <https://ghuntley.com/ralph/>
