"""科普视频统一视觉风格（house style）—— Manim Community 版。

用法:
    1. 把本文件复制进你的 Manim 工程目录（或直接 import）
    2. 场景继承 ExplainerScene，调用 self.play_title_card() / self.section_header()
    3. 快速预览:  manim -pql your_scene.py YourScene
       定稿渲染:  manim -pqh your_scene.py YourScene

设计来源: 3Blue1Brown 深色底 + 高饱和强调色；公式项与画面元素同色原则。
注意: 中文 Text 必须传 FONT 常量；MathTex 需要 LaTeX，环境没有时改用 Text 排版。
"""

from __future__ import annotations

from manim import (
    DOWN, LEFT, RIGHT, UP, Create, FadeIn, FadeOut, MathTex, Rectangle,
    Scene, Text, VGroup, Write, config,
)

# 默认 MathTex 使用 Manim 的 TeX 模板；其它编译器需配置 TexTemplate 并单独验证。

# ---- 配色（深色底 + 高饱和强调色）----------------------------------------
BG_COLOR = "#0f1117"      # 近黑深蓝底
FG_COLOR = "#eceff4"      # 主文字
ACCENT_BLUE = "#58c4dd"   # 主强调（3B1B 蓝）
ACCENT_YELLOW = "#ffd166" # 次强调（结论、答案）
ACCENT_GREEN = "#8bd17c"  # 第三强调（验证、正确）
ACCENT_RED = "#ef6461"    # 警示（冲突、错误直觉）
MUTED = "#5c6370"         # 弱化（次要信息、坐标轴）

# 公式项配色轮换：让公式中的每一项与画面元素同色
TERM_COLORS = [ACCENT_BLUE, ACCENT_YELLOW, ACCENT_GREEN, ACCENT_RED]

# ---- 字体 -----------------------------------------------------------------
FONT = "Noto Sans SC"     # 环境无此字体时换成可用中文字体名
FONT_MONO = "DejaVu Sans Mono"

TITLE_SIZE = 56
HEADING_SIZE = 40
BODY_SIZE = 32
CAPTION_SIZE = 24


class ExplainerScene(Scene):
    """所有科普场景的基类：统一背景、提供片头/章节/结语三件套的实现。

    子类只需实现 body()，construct 已串好 片头 → 正文 → 结语 的节奏。
    若不需要片头/结语，直接继承 Scene 并手动调用工具函数即可。
    """

    video_title: str = ""      # 子类覆盖：视频标题
    section: str = ""          # 子类覆盖：本场景章节名
    outro: str = ""            # 子类覆盖：结语（回响），为空则跳过

    def construct(self):
        config.background_color = BG_COLOR
        if self.video_title:
            self.play_title_card(self.video_title)
        if self.section:
            self.section_header(self.section)
        self.body()
        if self.outro:
            self.play_outro(self.outro)

    def body(self):
        """子类实现正文内容。"""
        raise NotImplementedError

    # ---- 片头 / 章节 / 结语 ----------------------------------------------

    def play_title_card(self, title: str, subtitle: str = "", hold: float = 1.2):
        """标题卡：标题写入 + 下划线生长，短停后淡出。"""
        t = Text(title, font=FONT, font_size=TITLE_SIZE, color=FG_COLOR)
        underline = Rectangle(
            width=t.width * 0.6, height=0.06, color=ACCENT_BLUE,
            fill_opacity=1, stroke_width=0,
        ).next_to(t, DOWN, buff=0.35)
        group = VGroup(t, underline)
        if subtitle:
            s = Text(subtitle, font=FONT, font_size=CAPTION_SIZE, color=MUTED)
            s.next_to(underline, DOWN, buff=0.3)
            group.add(s)
        self.play(Write(t), Create(underline), run_time=1.2)
        if subtitle:
            self.play(FadeIn(group[2], shift=UP * 0.2), run_time=0.5)
        self.wait(hold)
        self.play(FadeOut(group), run_time=0.6)

    def section_header(self, text: str, hold: float = 0.8):
        """章节标题：左侧竖线 + 文字，留在画面上方作为本段锚点。"""
        bar = Rectangle(width=0.09, height=0.7, color=ACCENT_YELLOW,
                        fill_opacity=1, stroke_width=0)
        t = Text(text, font=FONT, font_size=HEADING_SIZE, color=FG_COLOR)
        t.next_to(bar, RIGHT, buff=0.25)
        group = VGroup(bar, t).to_edge(UP + LEFT, buff=0.6)
        self.play(Create(bar), FadeIn(t, shift=RIGHT * 0.2), run_time=0.7)
        self.wait(hold)
        return group  # 返回给调用者，正文结束时可 FadeOut

    def play_outro(self, text: str, hold: float = 1.5):
        """结语（回响）：清屏后居中呈现，给顿悟留呼吸。"""
        self.play(*[FadeOut(m) for m in self.mobjects], run_time=0.6)
        t = Text(text, font=FONT, font_size=BODY_SIZE, color=ACCENT_YELLOW)
        self.play(FadeIn(t, scale=0.9), run_time=0.8)
        self.wait(hold)

    # ---- 公式工具 ----------------------------------------------------------

    def colored_tex(self, tex_str: str, terms: list[str] | None = None):
        """创建公式并把指定子串按 TERM_COLORS 轮换着色。

        colored_tex(r"a^{2n}", ["2n"]) -> 指数 2n 染成 ACCENT_BLUE
        用于贯彻"公式项与画面元素同色"原则。
        """
        m = MathTex(tex_str, font_size=BODY_SIZE + 8)
        if terms:
            for i, term in enumerate(terms):
                for part in m.get_parts_by_tex(term):
                    part.set_color(TERM_COLORS[i % len(TERM_COLORS)])
        return m


# ---- 示例场景（开工前先跑通它验证环境）------------------------------------


class StyleDemo(ExplainerScene):
    """环境自检场景：片头 + 章节 + 中文 + 公式着色 + 结语。

    运行: manim -pql manim_house_style.py StyleDemo
    通过标准: 无报错；中文不豆腐块；公式中 2n 为蓝色高亮。
    """

    video_title = "示例：风格的自检"
    section = "第一节 · 公式与色彩"
    outro = "风格就位，开始创作吧"

    def body(self):
        formula = self.colored_tex(r"a^{2n} = (a^n)^2", ["2n", "a^n"])
        note = Text("指数减半，底数平方", font=FONT, font_size=BODY_SIZE,
                    color=ACCENT_BLUE)
        note.next_to(formula, DOWN, buff=0.5)
        self.play(Write(formula), run_time=1.0)
        self.play(FadeIn(note, shift=UP * 0.2), run_time=0.6)
        self.wait(1.0)
