# 来源与适用范围

核对日期：2026-10-15。以下为作者经验、项目实践与语言标准说明，不代表本 Skill 已通过模型效果评测。

| 来源 | 采用内容 | 适用边界 |
|---|---|---|
| [Matt Pocock writing-for-agents](https://github.com/mattpocock/skills/blob/main/skills/productivity/writing-for-agents/SKILL.md) | 信息层次、同概念聚合、单一事实源、裁剪 | 上游负责正文；其 agent 指令专属规则仅用于相应文档。 |
| [Karpathy 原帖](https://x.com/karpathy/status/2105819303471976479)（2026-10-02） | 用具体语言要求和合适媒介降低理解成本 | 个人经验；帖中“80%”是风格提示，不是可测的 STE 合规等级。 |
| [GitLab agent 文档指导](https://docs.gitlab.com/development/documentation/ai-instruction-files-documentation/) | 指令具体、配判断示例、在新会话验证；规范一处维护 | 不引入 GitLab 的完整审查与发布流程。 |
| [GitLab AI 内容规范](https://docs.gitlab.com/development/documentation/styleguide/#ai-generated-content) | 每节提供新信息、事实可核查、使用现有合适页面 | 同一规则仍可在其他位置作必要摘要，避免复制完整定义。 |
| [Diátaxis 使用指南](https://diataxis.fr/how-to-use-diataxis/) | 从局部阅读问题改进文档 | 体裁判断不自动授权重组目录。 |
| [ASD-STE100 官方 FAQ](https://www.asd-ste100.org/STE_faq.html)及[标准介绍](https://www.asd-ste100.org/about_STE.html) | 短句、单句单主题、主动表达、术语一致、步骤条件前置 | 完整 STE 包含英文写作规则和受控词典；中文借鉴原则不等于合规。 |

STE 官方说明允许在其他写作场景借用部分原则。完整英文合规需要按用户指定标准版本逐项核验；本 Skill 不复制标准全文或词典。研究、决策与验收文档仍须保留理由、限定条件和证据，不能为简化表达删掉它们。

验证本 Skill 时，用同一原文和变更请求，在新会话比较采用前后的事实误改/遗漏、无关结构变化、重复定义、摘要冲突与人工返工；篇幅只作辅助指标。测试在离线副本进行，不默认发布或改动原文。
