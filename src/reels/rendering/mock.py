"""Fixture renderer that produces a real H.264/AAC file without invoking Remotion or paid APIs."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..config import ROOT
from .ffmpeg_post import ffmpeg_executable


def _font(size: int) -> ImageFont.ImageFont:
    path = ROOT / "renderer" / "node_modules" / "@fontsource" / "inter" / "files" / "inter-latin-900-normal.woff"
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def render_fixture(props: dict[str, Any], output_path: Path, poster_path: Path,
                   *, timeout_s: int = 900) -> Path:
    audio_path = Path(props["audio_path"])
    scenes = props.get("scenes", [])
    if not audio_path.is_file() or not scenes:
        raise ValueError("fixture render requires a voice track and at least one scene")
    width, height = props.get("size", [1080, 1920])
    image = Image.new("RGB", (width, height), "#05070A")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 72, 896, 136), radius=20, fill="#0D1117", outline="#1F2933", width=2)
    draw.text((88, 91), "TECH EXPLAINED", font=_font(28), fill="#34E39A")
    draw.text((64, 430), scenes[0]["headline"], font=_font(58), fill="#F5F7FA")
    draw.rounded_rectangle((64, 680, 896, 1290), radius=24, fill="#0D1117", outline="#1F2933", width=2)
    draw.text((104, 730), str(scenes[0]["template"]).replace("_", " ").upper(),
              font=_font(30), fill="#22D3EE")
    draw.text((104, 820), scenes[0]["headline"], font=_font(42), fill="#F5F7FA")
    for index, scene in enumerate(scenes[:5]):
        draw.rounded_rectangle((104, 930 + index * 58, 800, 974 + index * 58),
                               radius=14, fill="#111922", outline="#1F2933", width=1)
        draw.text((124, 936 + index * 58), scene["headline"][:48], font=_font(24),
                  fill="#34E39A" if index == 0 else "#8B95A1")
    draw.text((100, 1330), "Local fixture render • voice and scenes are mocked", font=_font(22), fill="#8B95A1")
    poster_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(poster_path, "PNG", optimize=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_frames = max(scene["from_frame"] + scene["duration_frames"] for scene in scenes)
    duration_s = duration_frames / float(props.get("fps", 30))
    command = [
        ffmpeg_executable(), "-hide_banner", "-y", "-loop", "1", "-framerate", "30",
        "-i", str(poster_path), "-i", str(audio_path),
        "-filter_complex",
        "[0:v]eq=brightness=0.1,zoompan=z='1+0.0025*mod(on,200)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        "d=1:s=1080x1920:fps=30,format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a", "-t", f"{duration_s:.3f}",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    if result.returncode:
        raise RuntimeError(f"mock FFmpeg render failed: {result.stderr[-3000:]}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("mock renderer did not produce an MP4")
    return output_path
