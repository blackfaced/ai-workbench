# 自测报告：〈需求 / 版本〉

> 模式：compose / update / audit。填写实际结果后删除本行及说明。未知写“未知”及原因；未执行写 NOT_RUN，证据不足另标 UNVERIFIED。默认保持一页可扫读，详细结果引用项目唯一验收记录；只有满足下方展开条件时才维护附录矩阵。

## 本轮结论

- 范围 / 需求与设计版本：
- 最终候选 / 环境：
- Case 结果：PASS 〈〉 / FAIL 〈〉 / BLOCKED 〈〉 / NOT_RUN 〈〉 / 未知 〈〉 / 未映射观察 〈〉
- 证据有效性：VALID 〈〉 / STALE 〈〉 / UNVERIFIED 〈〉
- 开放缺陷、证据冲突与获批例外：
- 向后兼容结论：〈旧行为与已知调用方是否逐项验证；未验证或获批迁移缺口〉
- 身份合同门禁：〈applicable=true / false / unknown；依据、权威证据、缺口、PASS / NOT_PASS〉
- 准入摘要：〈满足 / 不满足 / 待决定；项目接受者；依据〉

报告生成、执行器 `transport_status=completed`、会话结束、进程退出零或机器人声称成功均不等于 PASS，也不等于项目接受。

## 运行与来源索引

| 字段 | 实际值 |
|---|---|
| 需求、MR/PR、验收记录 | 〈来源、修订、项目唯一结果真源〉 |
| 设计版本 / Case ID 范围 | 〈test-design 或项目设计修订；稳定 ID〉 |
| 候选 / 基线 / 测试代码 | 〈SHA；脏树用 base + patch/摘要；部署物另记〉 |
| 环境 / Run / 时间 | 〈环境、Region、账号角色、run/attempt、时区〉 |
| 原始结果与附件入口 | 〈团队可访问链接；仅本机可访问则说明〉 |
| 报告模式 / Reviewer | compose / update / audit；〈审查者〉 |

### 执行来源

| Executor / Role | Source Type | Transport Status | Candidate / Environment | Attempt | 原始证据与局限 |
|---|---|---|---|---|---|
| 〈开发者、QA 助手、CI、Tester、人工等〉 | repo_test / qa_assistant / ci / manual / other | completed / interrupted / timeout / unknown | 〈身份〉 | 〈run〉 | 〈入口与缺口〉 |

角色标签不能替代独立性；同一执行者自查、或同一 QA 助手同时设计并执行，不自动计作独立 QA。代码 review 不计作测试执行。

## Case 摘要

优先链接项目既有验收记录，不在报告维护第二份完整矩阵。无法映射到稳定 Case ID 的结果列为“补充观察”，不计入覆盖或通过统计。

| Case ID | Design Revision | Attempt | Candidate / Environment | Raw Status | Canonical View | Evidence Validity | Actual Observation / Evidence | Reviewer |
|---|---|---|---|---|---|---|---|---|
| 〈稳定 ID〉 | 〈版本〉 | 〈attempt/run〉 | 〈候选 / 环境〉 | 〈来源原值〉 | PASS / FAIL / BLOCKED / NOT_RUN / 未知 | VALID / STALE / UNVERIFIED + 原因 | 〈实测与引用〉 | 〈审查者〉 |

每条结果的完整归一化链路为：需求/合同版本 → Design Revision → Case ID → Attempt → Candidate Identity → Environment → Executor / Role → Source Type → Transport Status → Raw Status → Canonical View → Actual Observation → Oracle Source → Evidence References → Evidence Validity → Reviewer。`Canonical View` 只用于汇总，不覆盖原始状态。记录缺失或 unknown 单列“未知”；skipped/error 必须按 Skill 的断言执行与阻断原因规则映射并保留理由。

## 身份合同核验

| 适用性 | 判断依据 | 权威证据 | 未决缺口 | 门禁结果 |
|---|---|---|---|---|
| true / false / unknown | 〈是否涉及身份、权限、资源归属〉 | 〈凭据来源到权威消费方的 effective principal、resource owner、权限与持久化效果〉 | 〈缺什么〉 | PASS / NOT_PASS |

`applicable=true` 但缺权威证据，或适用性为 `unknown`，不得通过；`applicable=false` 必须写明为何当前改动不涉及身份、权限或资源归属，理由缺失时也不得通过。同源 Mock、字段名一致、实现与测试共用同一逻辑都不能证明身份合同。

## 证据冲突与缺口

### 冲突

| Case / 候选 / 环境 / 时间窗 | 来源 A | 来源 B | 冲突点 | 当前更强来源与依据 | 未决影响 |
|---|---|---|---|---|---|
| 〈对象一致〉 | 〈证据〉 | 〈证据〉 | 〈差异〉 | 〈独立取数、独立判据与证据强度〉 | 〈对准入的影响〉 |

只有取数与判据相互独立且对象一致时才称独立验证；否则写补充观察或交叉线索。冲突未解决时不以多数票推导 PASS。

### 最小证据请求

| Case ID | 缺什么 | 影响哪条结论 | 建议执行者 | 最小补测范围 | 所需授权 / 恢复条件 |
|---|---|---|---|---|---|
| 〈ID〉 | 〈证据〉 | 〈结论〉 | 〈Tester / 项目执行器等〉 | 〈只覆盖缺口〉 | 〈条件〉 |

self-test-report 只记录请求，不启动测试、部署、数据写入、付费调用或额外 agent。

## 交付与访问

- 报告生成：〈已生成 / 未完成；入口〉。
- 发布状态：〈已发布 / 本地就绪、发布待办；授权依据〉。
- 目标读者与访问：〈读者；已验证 / 未验证 / 拒绝；检查方式与时间〉。
- 原始证据访问限制：〈作者能读、HTTP 成功和远端绝对路径均不替代读者访问证据〉。
- 本轮核验 / 复用 / 未验证：

---

## 按条件展开的附录

仅在多仓、多候选、多环境、历史失败与复测、向后兼容风险、付费/权限/持久化风险、多个执行来源冲突，或项目没有既有验收记录时展开对应部分；否则删除附录或只给原记录链接。

### 完整结果矩阵

仅当项目没有既有结果矩阵时使用；否则引用原记录。

| Case ID | Design Revision | Attempt | Candidate Identity | Environment | Executor / Role | Source Type | Transport Status | Raw Status | Canonical View | Actual Observation | Oracle Source | Evidence References | Evidence Validity | Reviewer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 〈ID〉 | 〈版本〉 | 〈attempt/run〉 | 〈候选〉 | 〈环境〉 | 〈执行者 / 角色〉 | 〈来源〉 | 〈传输态〉 | 〈原始值〉 | PASS / FAIL / BLOCKED / NOT_RUN / 未知 | 〈实测〉 | 〈独立判据〉 | 〈引用〉 | VALID / STALE / UNVERIFIED | 〈审查者〉 |

N/A 是适用性，不是执行结果；延期另列。历史 PASS + STALE/UNVERIFIED 不计作当前通过，不反写原始记录。首次失败、复测和最终结果分别保留。

### 向后兼容与影响面

涉及既有行为时必须填写；纯新增且无现有入口/共享依赖时写 N/A 及依据。

| 旧可观察合同 | 受影响调用方 / 模块 | 前后动作与实测值 | 特征 / 回归证据 | 兼容策略与回滚 | 状态 / 未验证边界 |
|---|---|---|---|---|---|
| 〈API、配置默认值、权限、数据、错误、副作用、交互或时序〉 | 〈按实际调用关系，不只写改动文件〉 | 〈旧候选与新候选〉 | 〈生产入口用例/日志〉 | 〈Adapter / Wrapper / Optional / 默认关闭 / 保留旧路径；回滚条件〉 | PASS / FAIL / BLOCKED / NOT_RUN；获批迁移缺口写批准位置 |

不得以新路径通过、编译成功或源码检查替代旧路径和兄弟模块回归；不得删弱旧行为断言来获得 PASS。

### 自动化、构建与关键证据

| 检查 / 准确命令或动作 | Case / 候选 / 角色 / Attempt | 实际结果 | 本轮执行或复用依据 | 原始证据 |
|---|---|---|---|---|
| 〈项目已有入口〉 | 〈身份〉 | 〈exit code、观察、通过/失败/跳过/未执行〉 | 〈时间或影响分析〉 | 〈链接〉 |

每组图片或日志注明 Case、候选、环境、展示状态、实际观察和证据局限。失败现象与原因分开；诊断不足时原因写“未确认”。

### 本次更新

- 预期 / 设计版本 / Case 集合变更：
- 新 Attempt、候选或环境及受影响 Case：
- 新增、替换、复用或转入历史的证据及原因：
- 本轮 audit 发现与修正：
