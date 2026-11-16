#!/usr/bin/env python3
"""抽帧质检：从视频中均匀抽帧，拼成带时间戳的 contact sheet，供快速目检。

用法:
    python3 preview_frames.py video.mp4 -o sheet.jpg
    python3 preview_frames.py video.mp4 -n 16 --cols 4 -o sheet.jpg

依赖: ffmpeg, ffprobe, Pillow
"""
import argparse
import math
import os
import subprocess
import sys
import tempfile

from check_environment import check_media

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("当前 Python 环境缺少 Pillow；抽帧拼图需要它。")


def get_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def extract_frame(video: str, t: float, dest: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", video,
         "-frames:v", "1", "-q:v", "3", dest],
        check=True,
    )


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser(description="抽帧生成 contact sheet 供质检")
    ap.add_argument("video", help="输入视频路径")
    ap.add_argument("-n", "--num", type=int, default=12, help="抽帧数量（默认 12）")
    ap.add_argument("--cols", type=int, default=3, help="每行帧数（默认 3）")
    ap.add_argument("-o", "--output", default="contact_sheet.jpg", help="输出图片")
    args = ap.parse_args()

    errors = check_media()
    if errors:
        ap.error("\n".join(errors))

    if not os.path.exists(args.video):
        sys.exit(f"找不到视频: {args.video}")

    duration = get_duration(args.video)
    n = max(2, args.num)
    # 避开首尾黑帧：在 (0, duration) 开区间内均匀取点
    times = [duration * (i + 0.5) / n for i in range(n)]

    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"f{i:03d}.jpg")
            try:
                extract_frame(args.video, t, p)
                frames.append((t, Image.open(p).convert("RGB")))
            except (subprocess.CalledProcessError, OSError) as e:
                print(f"警告: {fmt_time(t)} 处抽帧失败 ({e})，跳过", file=sys.stderr)

    if not frames:
        sys.exit("没有抽到任何帧，检查视频是否可读")

    w, h = frames[0][1].size
    thumb_w = 640
    thumb_h = int(h * thumb_w / w)
    label_h = 36
    cols = max(1, args.cols)
    rows = math.ceil(len(frames) / cols)

    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "#111111")
    draw = ImageDraw.Draw(sheet)
    font = load_font(22)

    for idx, (t, img) in enumerate(frames):
        r, c = divmod(idx, cols)
        x, y = c * thumb_w, r * (thumb_h + label_h)
        sheet.paste(img.resize((thumb_w, thumb_h), Image.LANCZOS), (x, y + label_h))
        label = f"#{idx + 1}  {fmt_time(t)} / {fmt_time(duration)}"
        draw.rectangle([x, y, x + thumb_w, y + label_h], fill="#1e1e1e")
        draw.text((x + 8, y + 6), label, fill="#eeeeee", font=font)

    sheet.save(args.output, quality=90)
    print(f"已生成 {args.output}：{len(frames)} 帧，时长 {fmt_time(duration)}")


if __name__ == "__main__":
    main()
