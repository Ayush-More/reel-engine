"""Audio metadata and silence checks using WAV directly or FFmpeg for compressed audio."""
from __future__ import annotations

import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioMetrics:
    duration_s: float
    longest_silence_s: float
    mean_db: float


def _ffmpeg() -> str:
    if executable := shutil.which("ffmpeg"):
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("FFmpeg is required to inspect compressed audio") from exc


def inspect_audio(path: Path, silence_threshold_db: float = -40.0) -> AudioMetrics:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as audio:
            frames = audio.readframes(audio.getnframes())
            sample_rate = audio.getframerate()
            sample_width = audio.getsampwidth()
            channels = audio.getnchannels()
        if sample_width != 2:
            raise ValueError(f"unsupported WAV sample width {sample_width}; expected 16-bit PCM")
        import array
        import math

        samples = array.array("h")
        samples.frombytes(frames)
        if __import__("sys").byteorder != "little":
            samples.byteswap()
        threshold = int(32767 * 10 ** (silence_threshold_db / 20))
        longest = current = 0
        energy = 0.0
        for sample in samples:
            magnitude = abs(sample)
            current = current + 1 if magnitude <= threshold else 0
            longest = max(longest, current)
            energy += sample * sample
        duration = len(samples) / (sample_rate * channels)
        mean = math.sqrt(energy / max(1, len(samples))) / 32768
        mean_db = 20 * math.log10(max(mean, 1e-12))
        return AudioMetrics(duration, longest / (sample_rate * channels), mean_db)

    command = [
        _ffmpeg(), "-hide_banner", "-i", str(path), "-af",
        f"silencedetect=noise={silence_threshold_db}dB:d=0.01,volumedetect", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = result.stderr
    if result.returncode:
        raise RuntimeError(f"FFmpeg audio inspection failed: {output[-2000:]}")
    durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", output)]
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", output)
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not duration_match or not mean_match:
        raise RuntimeError(f"FFmpeg did not return duration/volume metrics for {path}")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return AudioMetrics(duration, max(durations, default=0.0), float(mean_match.group(1)))
