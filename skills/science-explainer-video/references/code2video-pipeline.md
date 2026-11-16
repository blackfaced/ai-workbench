# Code-to-Video 技术管线

只读选定路线。工程、素材、依赖版本和渲染命令留在具体视频项目中。

## 路线选择

| 需求 | 候选 | 开始制作前验证 |
| --- | --- | --- |
| 数学公式、几何变换 | Manim Community | 中文字体、MathTex、示例场景 |
| 算法过程、数据结构 | Manim 或 Motion Canvas | 最小场景导出帧序列/视频及时间线 |
| React 包装、图表、复用布局 | Remotion | 当前项目的渲染命令、浏览器依赖和输出 |
| 拼接、配音、字幕 | FFmpeg | 编码器、滤镜和一段短素材 |

Manim Community 与创作者使用的其它 Manim 分支不是同一个兼容目标；本包模板按 Community API 编写。不要把其它版本的安装和调用参数直接混用。

## 依赖预检

以下命令从技能目录运行，使用与制作工程相同的 Python 和 PATH：

```bash
python3 scripts/check_environment.py --route compose --soft-subs --audio
python3 scripts/check_environment.py --route compose --burn-subs --audio
python3 scripts/check_environment.py --route preview
python3 scripts/check_environment.py --route manim --font "Noto Sans SC" --math
```

按当前需求选一条，省略不需要的 `--audio` / 字幕选项。预检只读，不安装或更新软件。使用项目隔离环境固定已核验的版本；缺依赖时提供具体缺项，避免边安装边切换制作路线。

- 合成脚本自动检查 FFmpeg、FFprobe、H.264/AAC 编码器以及所需滤镜；烧录必须有 `subtitles`/libass。缺少时明确失败，不静默切换成软字幕。
- 抽帧需要 Pillow；脚本启动时检查。
- Manim 路线检查当前 Python 模块、指定字体以及默认 MathTex 的 `latex`/`dvisvgm`。自定义 TeX 编译器通过 [TexTemplate](https://docs.manim.community/en/stable/reference/manim.utils.tex.TexTemplate.html) 配置并运行最小公式，不假设 tectonic 自动可用。
- 工具存在不等于中文或公式能正确渲染。先跑 `python3 -m manim -ql assets/manim_house_style.py StyleDemo`，目检缺字、边界和公式颜色。实际工程字体和版本不同则重新验证。
- Motion Canvas/Remotion 使用项目声明的固定依赖和渲染脚本；浏览器依赖按官方环境文档处理，不默认关闭浏览器沙盒。[Remotion 文档](https://www.remotion.dev/docs/)、[Motion Canvas 文档](https://motioncanvas.io/docs/)

## 合成合同

```bash
python3 scripts/assemble_video.py --scenes s1.mp4 s2.mp4 \
  --voice voice.wav --subs captions.srt \
  --resolution 1080x1920 --fps 30 --bottom-strip 120 -o final.mp4
```

- 每片先统一尺寸、像素格式、帧率和时间起点，再拼接。输入原音轨被丢弃；需要保留声音时先单独准备旁白/混音轨。输出 MP4 的画面时长由统一后的帧数决定，音轨补齐或截断到该长度。
- 所有输入先声明，再指定输出映射；软字幕用 `--no-burn-subs`。短字幕结束不会截断画面。字幕应落在片长内，超范围字幕需先调整。
- `--bottom-strip` 改为在最终画布内部预留空间，画面等比缩放到其余区域；宽高与黑条高度需为偶数。相较原包“追加高度”的行为，旧命令现在保持目标画幅。
- 用户路径作为独立命令参数传递；concat 清单和烧录滤镜只引用受控临时文件名，避免特殊字符在多层语法中被解释。
- 参数或依赖不满足时提前退出；渲染在临时目录完成，输出的尺寸、帧数、帧率和时长检查通过才替换目标。已有输入文件不能被当作输出覆盖。

FFmpeg 参数和拼接约束见 [CLI 文档](https://ffmpeg.org/ffmpeg.html) 与 [concat 文档](https://ffmpeg.org/ffmpeg-formats.html#concat)。

## 配音、字幕与检查

旁白可用用户录音或已授权的 TTS；无配音时按字幕阅读速度安排停留时间。先用实际音频校准分镜，成片再检查句尾和镜头锚点。

BGM 采用固定音量系数：有旁白时默认 0.12，无旁白时默认 0.35，并循环到画面结束。不是随说话动态变化的侧链压缩；音乐风格和响度不同仍需听检。`loudnorm` 目标为 -14 LUFS，先测实际输出，再决定是否需要两遍归一化。

字幕烧录保持最终画幅，预留空间不保证任意长度/多行字幕都能放下。按真实文案抽帧，检查字号、换行和安全区。软字幕的样式由播放器决定。`preview_frames.py` 是均匀抽样初检，需补看短镜头的边界/关键帧和完整播放。

## 成本与许可

不维护无来源的分钟单价或团队人数阈值。实际选择服务、准备付费或分发时，查所选版本/服务的官方条款并记录日期、适用主体和计费口径。可从 [Remotion 许可](https://www.remotion.dev/license)、[FFmpeg 许可说明](https://ffmpeg.org/legal.html) 和所选工具的发行包许可证开始。
