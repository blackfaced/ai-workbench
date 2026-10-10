# 实际 Skill 调用自观察

- 日期：2026-10-10，原生 Codex subagent `/root/invoke_test_design`，职责为设计与质量审查；不是实现 worker，也不是最终验收执行者。
- 模型：继承父 agent 默认；工具未暴露实际型号，因此型号未经验证，没有声明模型或成本。
- 入口：明确读取 `$HOME/.agents/skills/test-design/SKILL.md`，SHA-256 `e03a54a87495687a0839bf38018260e0b227581eefa155abf29cda803cbb16b5`；模板 `$HOME/.agents/skills/test-design/assets/design-template.md`，SHA-256 `856972094edb0ac0998c6ad8f8ac95152391dbf98e91e639fef9bc6ce8060888`。读取动作发生在本会话工具轨迹，不只在最终自述中。
- 应用过程：固定 #368 输入→查看已有验收及旧回归→按实际入口追到选择/分发/归属/还原→保留旧 ID→写错误但合理的结果、独立合同、可重复动作和证据边界→审查六个输入变体。
- 代码图：只读列出现有索引；没有当前 aeb6/39e72e2 索引，只看到旧工作树，未重新索引，使用当前固定 Git 对象及只读文本读取。
- 既有建议暴露：额外读到了项目 `pilot-plan.md` 的已知委托失效假设，已向父 agent 报告。输出保留其 PILOT ID，明确是 Skill 对既有设计的审查和补足，不标作无提示发现。
- 实质输出：安装后入口解析不能由旧 apply/check/botmux 三项替代；路径可读仍需排除错误旧全文；fresh install 不能代替旧受管安装升级与恢复后的下一次操作；本地文件证据不能代替真实客户端遵从权限与历史的证据。
- 权限：仅父 agent 授权的资料读取与 `$RUN_ARTIFACTS/client-test-design/` 设计文件写入。没有代码编辑、安装操作、项目测试运行、部署、issue 变更、额外 agent 或付费模型调用。
- 输出位置：同目录 `design.md`、`variants.md`、`observations.md`；临时交接件不是长期验收真源。父 agent 负责选择并移入项目批准记录，保持唯一结果源。
- 覆盖界限：证明一次真实 Codex 原生 subagent 使用安装后 test-design 处理真实需求及边界输入；不证明原生自动发现，不证明 deliver-spec/implement-batch 调用，不证明完整交付流程，不证明迁移或检测对照已执行通过。
