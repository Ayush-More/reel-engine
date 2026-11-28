"""Create a locally generated, colour-managed JPEG cover."""
from __future__ import annotations

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageStat

from ..config import ROOT
from ..contracts.models import Script
from ..rendering.ffmpeg_post import ffmpeg_executable

WIDTH, HEIGHT = 1080, 1920
MAX_BYTES = 8 * 1024 * 1024


def _srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _font(size: int, text: str = "") -> ImageFont.ImageFont:
    font_root = ROOT / "renderer" / "node_modules" / "@fontsource"
    if any("\u0900" <= char <= "\u097f" for char in text):
        candidates = [font_root / "noto-sans-devanagari" / "files" /
                      "noto-sans-devanagari-devanagari-700-normal.woff"]
    else:
        candidates = [font_root / "inter" / "files" / "inter-latin-900-normal.woff"]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def generate_cover(script: Script, output_path: Path, source_video: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image: Image.Image
    if source_video and source_video.is_file():
        import subprocess

        result = subprocess.run(
            [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-ss", "1",
             "-i", str(source_video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=60, check=False,
        )
        try:
            image = Image.open(io.BytesIO(result.stdout)).convert("RGB")
        except (OSError, ValueError):
            image = _background()
    else:
        image = _background()
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((64, 82, 458, 158), radius=38, fill=(13, 17, 23, 235),
                           outline=(52, 227, 154, 255), width=3)
    draw.text((94, 103), "TECH EXPLAINED", font=_font(28, "TECH EXPLAINED"), fill=(52, 227, 154, 255))
    title = script.meta.thumbnail_headline.strip() or script.meta.title
    font = _font(88, title)
    lines = textwrap.wrap(title, width=20, break_long_words=True, break_on_hyphens=False)[:3]
    top = 260
    for line in lines:
        draw.text((64, top + 5), line, font=font, fill=(0, 0, 0, 205), stroke_width=4)
        draw.text((64, top), line, font=font, fill=(245, 247, 250, 255),
                  stroke_width=1, stroke_fill=(5, 7, 10, 255))
        top += 118
    draw.rounded_rectangle((64, 630, 400, 642), radius=6, fill=(52, 227, 154, 255))
    image.save(output_path, "JPEG", quality=91, optimize=True, icc_profile=_srgb_profile())
    return output_path


def _background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        blend = y / HEIGHT
        color = (int(5 + blend * 7), int(7 + blend * 9), int(10 + blend * 15))
        for x in range(WIDTH):
            pixels[x, y] = color
    return image


def validate_cover(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"passed": False, "reason": "cover file missing"}
    try:
        with Image.open(path) as image:
            image.load()
            profile = image.info.get("icc_profile")
            srgb = False
            if profile:
                description = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile)))
                srgb = "srgb" in description.lower()
            stddev = max(ImageStat.Stat(image.convert("RGB")).stddev)
            passed = (
                image.format == "JPEG" and image.size == (WIDTH, HEIGHT)
                and image.mode in ("RGB", "RGBA") and srgb
                and path.stat().st_size < MAX_BYTES and stddev >= 2.0
            )
            return {
                "passed": passed,
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
                "srgb": srgb,
                "size_bytes": path.stat().st_size,
                "stddev": stddev,
            }
    except (OSError, ValueError) as exc:
        return {"passed": False, "reason": f"cannot read cover: {exc}"}
