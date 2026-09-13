# 单 Issue 轻量试用

- Domain: coding
- 用途：安装 Skills 后，用一个小而可独立验收的 Issue 验证实际帮助。

## 选择入口

普通单 Issue 直接沿用目标仓库的实现、测试和评审流程。仅当测试入口缺失或过时时使用 `setup-aiwb` 核实并维护项目测试手册；已有可靠手册就直接复用。不需要额外的 batch、integrator 或确认仪式，外部操作仍遵循用户授权。

当一个 spec 有多个依赖子 Issue、需要隔离并行实施和统一集成时，由用户显式选择 [implement-batch](implement-batch.md)。单 Issue 也可显式选择它，但普通小修复不必承担这套编排。

> 检查当前 Issue 的实际情况；测试方法不清楚时使用 setup-aiwb，只询问缺失项。随后按本仓流程实现和验证，报告测试边界与剩余问题。

## 一次试用怎么完成

1. **选题与重验。** 选有明确验收条件的小 Issue，对照当前代码重验旧描述；依赖已存在就复用，不按过时描述重复安装或改造。
2. **测试边界。** 由目标仓库维护启动、隔离目标、测试命令和清理方法。分清本地 fixture、真实服务和真机；缺凭据时如实标记，不默认连接生产。
3. **实施与评审。** 沿用本仓测试方法和要求的独立评审轴；保留最小修改，已有实现先验证。AIWB 不再包一层相同流程。
4. **保留失败。** 若全量测试失败，先保留第一次命令、候选、环境与输出。单测、基线或降低并发只作诊断；即使通过，也不能覆盖原失败或证明 flaky 已解决。把证据补进已有问题，别自动 retry 到绿或顺手修无关代码。
5. **交付闭环。** 在用户授权内提交、推送、建 PR、更新 Issue；按项目门禁确认 CI 和合并结果。报告哪些行为实际执行、哪些仍未验收。没有发布权限时交付本地变更和证据，不宣称 PR/Issue 已闭环。

## 已发生的案例（2026-09-12）

[Study Buddy #75](https://github.com/blackfaced/study-buddy/issues/75) 的旧描述认为缺 Playwright；实查已有依赖，最终复用它，修正不可移植的浏览器路径与隐式测试目标。`setup-aiwb` 帮助建立项目测试手册，实现与独立 Standards / Spec 评审仍沿用项目流程。

[PR #237](https://github.com/blackfaced/study-buddy/pull/237) 已合并为 `6b5839efc99142fe15840c8b61cd4ba879326d38`，#75 已关闭。可复核的 [测试手册](https://github.com/blackfaced/study-buddy/blob/6b5839efc99142fe15840c8b61cd4ba879326d38/docs/testing/integration.md) 与 [验收记录](https://github.com/blackfaced/study-buddy/blob/6b5839efc99142fe15840c8b61cd4ba879326d38/docs/testing/issue-75-acceptance.md) 留在项目仓库，AIWB 不复制其部署知识。

该次默认并发套件出现不同失败点；单文件与降低并发诊断通过，首次失败与对照结果补进 [既有 flaky Issue #187](https://github.com/blackfaced/study-buddy/issues/187#issuecomment-5638771601)。CI 通过不代表本地并发不稳定已修复。这次是 setup-aiwb 的实际使用与隔离测试，不是 implement-batch 或 Kimi 执行验收，也没有生产部署或真机/外部模型验收。

## 报告证据层级

| 状态 | 证明什么 | 不能推出什么 |
| --- | --- | --- |
| installed | 受管文件已安装 | 客户端能加载 |
| natively discoverable | 指定客户端原生接口列出 Skill | Skill 能完成任务 |
| executed | 指定客户端在任务中实际使用 Skill | 任务结果正确 |
| isolated-tested | 指定候选通过隔离测试 | 真实服务、API 或真机通过 |
| live-accepted | 指定候选在约定真实环境满足验收 | 其他客户端、环境或后续版本通过 |

每项结论附候选、客户端、环境、命令/观察和证据位置；缺哪个层级就明确写未验证，不必为了填满表而增加测试。
