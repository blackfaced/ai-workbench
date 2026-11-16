# Science Explainer Video

- Type: skill
- Domain: learning
- Owner: personal, first-party
- Tracking: [blackfaced/ai-workbench#192](https://github.com/blackfaced/ai-workbench/issues/192)
- Source: [完整技能包](science-explainer-video/SKILL.md)，基于作者提供的 `science-explainer-video.zip` 修订；导入摘要及资源清单见 [来源登记](sources.lock.json)。原 ZIP 摘要不代表当前修订包。
- Evaluation: 2026-11-16 修复合成问题并补充科学核验、短视频流程与依赖检查；客户端发现和完整 Manim 成片仍未验收。
- Use when: 将数学、算法、AI 或 CS 概念做成讲解脚本、分镜、动画或视频。普通文字问答无需自动进入视频制作流程。

## 使用与启用

按 [安装策略](README.md#installation-policy) 在选定项目和客户端启用，固定包含完整目录的提交。当前可让 agent 直接读取 `SKILL.md`；自动发现需在启用后的新会话单独验证。本次不新增全局安装或默认 Profile 项。

示例请求：

> 使用 science-explainer-video，给零基础观众解释梯度下降，目标 60 秒、9:16、中文；先交付旁白稿和分镜。

保留整个目录：`references/` 提供风格、科学核验、分镜和制作流程，`assets/` 提供 Manim 模板及可运行科学例子，`scripts/` 提供依赖检查、合成与抽帧，`tests/` 提供真实媒体回归。没有必需的外部 Skill 依赖。

仅做脚本/分镜不需要渲染环境。需要制作时，按 [技术管线](science-explainer-video/references/code2video-pipeline.md) 检查所选路线的 Python、FFmpeg/FFprobe、Pillow，以及 Manim/字体/TeX。检查器不会安装软件。

## 修订内容与兼容性

- 合成：逐片统一规格后拼接；修正软字幕输入顺序和短字幕截断画面；受控临时文件名避开路径转义问题。输出检查通过后才替换目标，拒绝覆盖输入。
- 字幕区：`--bottom-strip` 从“增加输出高度”改为“在目标画布内留空间”，旧命令现在保持指定分辨率。画面会等比缩小到内容区，需重新检查构图。
- 科学内容：增加断言来源、适用条件、独立验证和类比边界。模幂示例纠正二进制位数与乘法次数混淆，并与 Python `pow` 对照。
- 短视频：默认 60 秒竖屏，长版默认 5 分钟横屏；提供时间连续的 60 秒示例和总计 300 秒的扩展。旁白需实际试读校准。
- 指令：缩短触发描述，风格库按需读取；按用户已授权范围继续制作，不对整片授权额外设置分镜确认。移除无来源的价格/许可数字和未经验证的 TeX 自动回退。

## 验证与范围

从仓库根目录运行媒体回归与科学例子：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/science-explainer-video/tests -v
python3 skills/science-explainer-video/assets/modular_power_example.py
python3 tools/environment/tests/regression.py
```

媒体回归使用临时生成的 H.264 片段、音频和字幕：检查尺寸、帧率、帧数、总时长、场景次序、字幕轨、可见字幕像素、抽帧拼图、错误预检和失败时保留旧输出。没有个人素材或付费服务。

系统 FFmpeg 8.1.1 无 libass，用于验证缺滤镜时提前失败；临时隔离的 `imageio-ffmpeg==0.6.0` 所带 FFmpeg 7.1 用于验证实际烧录和字幕区。各环境会跳过不适用的一个滤镜分支，不能把单个环境的跳过当作该分支通过。临时工具未安装到全局，也不随技能分发。执行结果和提交记录写在同一张 Issue。

未覆盖完整 Manim/字体/TeX 渲染、真实旁白同步、成片响度测量、客户端新会话发现、全新机器安装和其他机器。预检或回归通过不能替代这些验收。原包评估和修复前失败证据保留在 Issue 历史中。
