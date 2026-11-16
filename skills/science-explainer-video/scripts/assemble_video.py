#!/usr/bin/env python3
"""合成 MP4：逐片统一规格 → 拼接 → 配音/字幕 → 检查输出。

    python3 assemble_video.py --scenes s1.mp4 s2.mp4 -o final.mp4
    python3 assemble_video.py --scenes s1.mp4 --voice vo.wav --bgm bgm.mp3 \
        --subs subs.srt --bottom-strip 90 -o final.mp4

场景自带音轨会丢弃。成片时长由画面决定，短旁白补静音、长旁白截断；
BGM 循环并按有无旁白选择固定音量，不做动态 ducking。响度滤镜目标 -14 LUFS，
实际成片需另测。--bottom-strip 在目标画布内部留黑条，保持 --resolution 不变。
依赖：FFmpeg、FFprobe；烧录字幕还需 subtitles/libass。
"""
from fractions import Fraction
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from check_environment import check_media


def run(cmd, **kwargs):
    print("+", " ".join(str(x) for x in cmd[:6]), "...", file=sys.stderr)
    subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def video_info(path):
    data = probe(path)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"没有视频轨：{path}")
    return video


def concat_scenes(scenes, res, fps, dest, bottom_strip=0):
    """每段先统一规格和起点；清单仅含受控临时文件名，避免用户路径转义。"""
    w, h = map(int, res.split("x"))
    content_h = h - bottom_strip
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        names = []
        total_frames = 0
        for i, scene in enumerate(scenes):
            name = f"scene-{i:04d}.mp4"
            normalized = tmp / name
            vf = (f"setpts=PTS-STARTPTS,fps={fps},"
                  f"scale={w}:{content_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                  f"setsar=1,pad={w}:{h}:(ow-iw)/2:({content_h}-ih)/2:color=black")
            run(["ffmpeg", "-y", "-v", "error", "-i", scene, "-map", "0:v:0", "-an",
                 "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", normalized])
            total_frames += int(video_info(normalized)["nb_frames"])
            names.append(f"file '{name}'\n")
        manifest = tmp / "scenes.txt"
        manifest.write_text("".join(names), encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", manifest,
             "-map", "0:v:0", "-c:v", "copy", dest])
    if int(video_info(dest)["nb_frames"]) != total_frames:
        raise ValueError("拼接后帧数与场景总帧数不符")
    return total_frames


def main():
    ap = argparse.ArgumentParser(description="科普视频成片合成")
    ap.add_argument("--scenes", nargs="+", required=True, help="场景片段，按顺序；原音轨丢弃")
    ap.add_argument("--voice", help="旁白音频，画面结束时截断")
    ap.add_argument("--bgm", help="背景音乐，循环至画面结束")
    ap.add_argument("--bgm-volume", type=float, default=0.12, help="有旁白时 BGM 固定音量系数")
    ap.add_argument("--bgm-volume-full", type=float, default=0.35, help="无旁白时 BGM 固定音量系数")
    ap.add_argument("--subs", help="UTF-8 SRT 字幕文件")
    ap.add_argument("--no-burn-subs", action="store_true", help="软字幕，不烧录")
    ap.add_argument("--resolution", default="1920x1080", help="最终画布尺寸，宽高须为正偶数")
    ap.add_argument("--bottom-strip", type=int, default=0, help="在画布内部预留字幕黑条，偶数像素")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("-o", "--output", required=True, help="MP4 输出路径")
    args = ap.parse_args()
    try:
        w, h = map(int, args.resolution.split("x"))
    except ValueError:
        ap.error("--resolution 格式应为 宽x高，如 1080x1920")
    if min(w, h) < 2 or w % 2 or h % 2 or args.fps <= 0:
        ap.error("宽高必须为正偶数，--fps 必须为正整数")
    if args.bottom_strip < 0 or args.bottom_strip >= h or args.bottom_strip % 2:
        ap.error("--bottom-strip 必须为小于画布高度的非负偶数")
    if any(not math.isfinite(v) or v < 0 for v in (args.bgm_volume, args.bgm_volume_full)):
        ap.error("BGM 音量必须为非负有限数")
    if args.no_burn_subs and not args.subs:
        ap.error("--no-burn-subs 需要 --subs")
    paths = args.scenes + [p for p in (args.voice, args.bgm, args.subs) if p]
    for path in paths:
        if not Path(path).is_file():
            ap.error(f"找不到输入文件：{path}")
    output = Path(args.output).resolve()
    if output in [Path(p).resolve() for p in paths]:
        ap.error("输出路径不能覆盖输入文件")
    if output.suffix.lower() != ".mp4" or not output.parent.is_dir():
        ap.error("输出需为已存在目录中的 .mp4 文件")
    burn = bool(args.subs and not args.no_burn_subs)
    has_audio = bool(args.voice or args.bgm)
    errors = check_media(compose=True, burn_subs=burn,
                         soft_subs=bool(args.subs and args.no_burn_subs), audio=has_audio)
    if errors:
        ap.error("\n".join(errors))

    # Keep staging on the output filesystem so final replacement is atomic.
    with tempfile.TemporaryDirectory(prefix=".science-video-", dir=output.parent) as directory:
        tmp = Path(directory)
        track = tmp / "video.mp4"
        frames = concat_scenes(args.scenes, args.resolution, args.fps, track, args.bottom_strip)
        duration = frames / args.fps
        inputs = ["-i", str(track)]
        filters = []
        idx = 1
        voice_label = bgm_label = None
        if args.voice:
            inputs += ["-i", str(Path(args.voice).resolve())]
            filters.append(f"[{idx}:a:0]loudnorm=I=-14:TP=-1.5:LRA=11,apad[vo]")
            voice_label = "[vo]"
            idx += 1
        if args.bgm:
            inputs += ["-stream_loop", "-1", "-i", str(Path(args.bgm).resolve())]
            volume = args.bgm_volume if args.voice else args.bgm_volume_full
            filters.append(f"[{idx}:a:0]volume={volume}[bgm]")
            bgm_label = "[bgm]"
            idx += 1
        subtitle_index = None
        if args.subs and args.no_burn_subs:
            subtitle_index = idx
            inputs += ["-i", str(Path(args.subs).resolve())]

        audio_map = voice_label
        if voice_label and bgm_label:
            filters.append(f"{voice_label}{bgm_label}amix=inputs=2:duration=first:dropout_transition=2,"
                           "loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
            audio_map = "[aout]"
        elif bgm_label:
            filters.append(f"{bgm_label}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
            audio_map = "[aout]"

        cmd = ["ffmpeg", "-y", "-v", "error"] + inputs
        if filters:
            cmd += ["-filter_complex", ";".join(filters)]
        if burn:
            # A controlled relative name avoids both filtergraph and filename escaping layers.
            shutil.copyfile(args.subs, tmp / "captions.srt")
            font_size = max(12, round(h * 0.035))
            if args.bottom_strip:
                font_size = min(font_size, max(8, args.bottom_strip // 3))
            margin = max(2, args.bottom_strip // 5) if args.bottom_strip else max(4, round(h * 0.04))
            style = (f"PlayResX={w},PlayResY={h},FontSize={font_size},"
                     "PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=1,"
                     f"Alignment=2,MarginV={margin}")
            cmd += ["-vf", f"subtitles=filename=captions.srt:force_style='{style}'"]
        cmd += ["-map", "0:v:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium"]
        if audio_map:
            cmd += ["-map", audio_map, "-c:a", "aac", "-b:a", "192k"]
        if subtitle_index is not None:
            cmd += ["-map", f"{subtitle_index}:s:0", "-c:s", "mov_text"]
        staged = tmp / "final.mp4"
        # -shortest would cut video to the end of a short subtitle track.
        cmd += ["-t", f"{duration:.9f}", "-movflags", "+faststart", str(staged)]
        run(cmd, cwd=tmp)
        data = probe(staged)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        if ((video["width"], video["height"]) != (w, h)
                or int(video["nb_frames"]) != frames
                or Fraction(video["r_frame_rate"]) != args.fps
                or abs(float(data["format"]["duration"]) - duration) > 1 / args.fps):
            raise ValueError("合成后的尺寸、帧数、帧率或时长不符合预期；未替换输出文件")
        os.replace(staged, output)
    print(f"成片已输出：{output}（{frames} 帧，{duration:.3f} 秒）")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"合成失败：{exc}")
