"""FFmpeg mastering for H.264/AAC vertical MP4 output."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_executable() -> str:
    if executable := shutil.which("ffmpeg"):
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("FFmpeg is required; install the project media dependencies") from exc


def postprocess_video(raw_path: Path, output_path: Path, *, timeout_s: int = 900,
                      integrated_lufs: float = -14.0, true_peak_dbtp: float = -1.0) -> Path:
    if not raw_path.is_file():
        raise FileNotFoundError(f"Remotion output does not exist: {raw_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_executable(), "-hide_banner", "-y", "-i", str(raw_path),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
              "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-af", f"loudnorm=I={integrated_lufs}:TP={true_peak_dbtp}:LRA=11",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-movflags", "+faststart", str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    if result.returncode:
        raise RuntimeError(f"FFmpeg mastering failed: {result.stderr[-3000:]}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg exited successfully without producing the mastered MP4")
    return output_path
