"""CLI integration cases for issue #192; generated media only, no machine config writes.

Run: python3 -m unittest discover -s skills/science-explainer-video/tests -v
Requires FFmpeg, FFprobe and Pillow. Burn-in is skipped when libass is unavailable.
"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

PACKAGE = Path(__file__).resolve().parents[1]
ASSEMBLE = PACKAGE / "scripts/assemble_video.py"


def command(args, **kwargs):
    return subprocess.run([str(x) for x in args], capture_output=True, timeout=60, **kwargs)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg and FFprobe")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="science-media-tests-")
        cls.root = Path(cls.temp.name)
        for name, size, fps, color in [("red", "320x180", 24, "red"),
                                       ("blue", "640x360", 30, "blue")]:
            p = command(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                         f"color=c={color}:s={size}:r={fps}:d=1", "-c:v", "libx264",
                         "-pix_fmt", "yuv420p", cls.root / f"{name}.mp4"])
            if p.returncode:
                raise RuntimeError(p.stderr.decode())
        cls.quoted = cls.root / "片段 one's.mp4"
        shutil.copyfile(cls.root / "red.mp4", cls.quoted)
        cls.subs = cls.root / "字幕 one's:clip.srt"
        cls.subs.write_text("1\n00:00:00,000 --> 00:00:00,300\nSAFE ZONE\n\n", encoding="utf-8")
        p = command(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     "sine=frequency=440:duration=0.2", cls.root / "voice.wav"])
        if p.returncode:
            raise RuntimeError(p.stderr.decode())
        filters = command(["ffmpeg", "-hide_banner", "-filters"]).stdout.decode()
        cls.has_subtitles = any("subtitles" == line.split()[1] for line in filters.splitlines()
                                if len(line.split()) >= 2)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assemble(self, scenes=None, extra=(), success=True, output=None, env=None):
        output = output or self.root / (self._testMethodName + ".mp4")
        p = command([sys.executable, ASSEMBLE, "--scenes", *(scenes or [self.root / "red.mp4"]),
                     "--resolution", "320x180", "--fps", "24", *extra, "-o", output], env=env)
        if success:
            self.assertEqual(p.returncode, 0, p.stderr.decode())
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout.decode())
        return output, p

    def probe(self, path, seconds, frames, size=(320, 180)):
        p = command(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        data = json.loads(p.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), size)
        self.assertEqual(video["r_frame_rate"], "24/1")
        self.assertEqual(int(video["nb_frames"]), frames)
        self.assertAlmostEqual(float(data["format"]["duration"]), seconds, delta=1 / 24)
        return data

    def frame(self, path, time=0.1):
        p = command(["ffmpeg", "-v", "error", "-ss", str(time), "-i", path,
                     "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"])
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        return Image.open(io.BytesIO(p.stdout)).convert("RGB")

    def test_single_and_same_specs(self):
        out, _ = self.assemble()
        self.probe(out, 1, 24)
        out, _ = self.assemble([self.root / "red.mp4"] * 2)
        self.probe(out, 2, 48)

    def test_mixed_specs_preserve_duration_and_scene_order(self):
        out, _ = self.assemble([self.root / "red.mp4", self.root / "blue.mp4"])
        self.probe(out, 2, 48)
        self.assertGreater(self.frame(out, 0.5).getpixel((160, 90))[0], 200)
        self.assertGreater(self.frame(out, 1.5).getpixel((160, 90))[2], 200)

    def test_quoted_scene_path(self):
        out, _ = self.assemble([self.quoted, self.root / "blue.mp4"])
        self.probe(out, 2, 48)

    def test_short_soft_subtitles_do_not_trim_video(self):
        out, _ = self.assemble(extra=["--subs", self.subs, "--no-burn-subs"])
        data = self.probe(out, 1, 24)
        self.assertIn("mov_text", [s["codec_name"] for s in data["streams"]])
        sub = command(["ffmpeg", "-v", "error", "-i", out, "-map", "0:s:0", "-f", "srt", "-"])
        self.assertIn(b"SAFE ZONE", sub.stdout)

    def test_voice_bgm_and_soft_subtitles_have_full_duration(self):
        out, _ = self.assemble(extra=["--subs", self.subs, "--no-burn-subs",
                                     "--voice", self.root / "voice.wav", "--bgm", self.root / "voice.wav"])
        data = self.probe(out, 1, 24)
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        self.assertAlmostEqual(float(audio["duration"]), 1, delta=1 / 24)

    def test_portrait_strip_stays_inside_canvas(self):
        out, _ = self.assemble(extra=["--resolution", "180x320", "--bottom-strip", "60"])
        self.probe(out, 1, 24, (180, 320))
        self.assertLess(max(self.frame(out).crop((0, 260, 180, 320)).getextrema()[0]), 8)

    def test_burn_subtitles_with_special_path_and_safe_zone(self):
        if not self.has_subtitles:
            self.skipTest("FFmpeg build lacks subtitles/libass; preflight covered separately")
        out, _ = self.assemble(extra=["--subs", self.subs, "--bottom-strip", "60"])
        self.probe(out, 1, 24)
        img = self.frame(out)
        white = lambda region: sum(min(rgb) > 180 for rgb in region.getdata())
        self.assertGreater(white(img.crop((0, 120, 320, 180))), 10, "subtitle must be visible inside reserved strip")
        self.assertEqual(white(img.crop((0, 0, 320, 120))), 0, "subtitle must not cover content")

    def test_missing_subtitle_filter_fails_before_render(self):
        if self.has_subtitles:
            self.skipTest("requires build without subtitles filter")
        out, p = self.assemble(extra=["--subs", self.subs], success=False)
        self.assertIn("subtitles/libass", p.stderr.decode())
        self.assertNotIn("+ ffmpeg", p.stderr.decode())
        self.assertFalse(out.exists())

    def test_bad_geometry_is_rejected_before_render(self):
        for extra in [("--resolution", "319x180"), ("--bottom-strip", "180"), ("--fps", "0")]:
            with self.subTest(extra=extra):
                out, p = self.assemble(extra=extra, success=False)
                self.assertNotIn("+ ffmpeg", p.stderr.decode())
                self.assertFalse(out.exists())

    def test_source_cannot_be_overwritten(self):
        source = self.root / "red.mp4"
        before = source.read_bytes()
        _, p = self.assemble(output=source, success=False)
        self.assertIn("输入", p.stderr.decode())
        self.assertEqual(source.read_bytes(), before)

    def test_missing_binary_is_actionable(self):
        env = dict(os.environ, PATH=str(self.root / "no-tools"))
        out, p = self.assemble(env=env, success=False)
        self.assertIn("ffmpeg", p.stderr.decode())
        self.assertNotIn("Traceback", p.stderr.decode())
        self.assertFalse(out.exists())

    def test_render_failure_preserves_previous_output(self):
        out = self.root / "previous.mp4"
        shutil.copyfile(self.root / "red.mp4", out)
        before = out.read_bytes()
        invalid_audio = self.root / "broken.wav"
        invalid_audio.write_text("not audio")
        self.assemble(extra=["--voice", invalid_audio], output=out, success=False)
        self.assertEqual(out.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".science-video-*")), [])

    def test_preview_contains_both_scenes(self):
        out, _ = self.assemble([self.root / "red.mp4", self.root / "blue.mp4"])
        sheet = self.root / "sheet.jpg"
        p = command([sys.executable, PACKAGE / "scripts/preview_frames.py", out,
                     "-n", "4", "--cols", "2", "-o", sheet])
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        with Image.open(sheet) as img:
            self.assertEqual(img.size, (1280, 792))
            self.assertGreater(img.getpixel((320, 216))[0], 200)
            self.assertGreater(img.getpixel((320, 612))[2], 200)


if __name__ == "__main__":
    unittest.main()
