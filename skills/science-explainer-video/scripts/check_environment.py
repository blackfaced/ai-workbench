#!/usr/bin/env python3
"""Read-only dependency checks for the selected video route; never installs packages."""
import argparse
import importlib.util
import shutil
import subprocess


def ffmpeg_features(kind):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-" + kind],
                            capture_output=True, text=True, check=True)
    return {parts[1] for line in result.stdout.splitlines()
            if len(parts := line.split()) >= 2}


def check_media(*, compose=False, burn_subs=False, soft_subs=False, audio=False):
    errors = [f"缺少 {name}：安装后确认它在 PATH 中。"
              for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if errors:
        return errors
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        filters = ffmpeg_features("filters")
        encoders = ffmpeg_features("encoders")
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"FFmpeg/FFprobe 无法运行：{exc}"]
    required_filters = {"scale", "pad", "fps", "setsar", "setpts"} if compose else set()
    required_encoders = {"libx264"} if compose else set()
    if burn_subs and "subtitles" not in filters:
        errors.append("缺少 subtitles/libass：选择带 libass 的 FFmpeg，或显式使用 --no-burn-subs 软字幕。")
    if soft_subs:
        required_encoders.add("mov_text")
    if audio:
        required_filters.update(("loudnorm", "apad", "amix", "volume"))
        required_encoders.add("aac")
    errors.extend(f"缺少 FFmpeg 滤镜：{name}" for name in sorted(required_filters - filters))
    errors.extend(f"缺少 FFmpeg 编码器：{name}" for name in sorted(required_encoders - encoders))
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--route", choices=("compose", "preview", "manim"), default="compose")
    ap.add_argument("--burn-subs", action="store_true")
    ap.add_argument("--soft-subs", action="store_true")
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--font", help="Manim Text 使用的确切字体名，如 Noto Sans SC")
    ap.add_argument("--math", action="store_true", help="检查默认 MathTex 的 latex + dvisvgm 工具链")
    args = ap.parse_args()
    errors = check_media(compose=args.route == "compose", burn_subs=args.burn_subs,
                         soft_subs=args.soft_subs, audio=args.audio)
    if args.route == "preview" and not importlib.util.find_spec("PIL"):
        errors.append("当前 Python 环境缺少 Pillow；抽帧拼图需要它。")
    if args.route == "manim":
        if not importlib.util.find_spec("manim"):
            errors.append("当前 Python 环境缺少 Manim Community。")
        if args.font:
            try:
                import manimpango
                if args.font not in manimpango.list_fonts():
                    errors.append(f"未找到字体 {args.font}；选用已安装的中文字体并同步修改模板 FONT。")
            except ImportError:
                errors.append("无法检查字体：当前 Python 环境缺少 manimpango。")
        if args.math:
            errors.extend(f"默认 MathTex 工具链缺少 {tool}；自定义 TeX 模板需另跑最小公式验证。"
                          for tool in ("latex", "dvisvgm") if not shutil.which(tool))
    if errors:
        ap.exit(1, "\n".join(errors) + "\n")
    print("依赖检查通过；仍需渲染样例验证字体、公式和实际媒体输出。")


if __name__ == "__main__":
    main()
