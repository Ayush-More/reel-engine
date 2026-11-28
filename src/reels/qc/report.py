"""Phase 2 hard gates and weighted quality score."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..alignment.captions import CaptionSegment, CaptionWord, validate_caption_sync
from ..contracts.models import QCCheck, QCReport, Script
from ..rendering.ffmpeg_post import ffmpeg_executable
from ..storage.artifacts import JobFiles
from ..thumbnails.cover import validate_cover
from ..validation.script_rules import ROLE_ORDER, word_count
from ..voice.audio import inspect_audio
from ..visuals.layout import safe_area_violations


@dataclass(frozen=True)
class MediaProbe:
    duration_s: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    pixel_format: str | None


def probe_media(path: Path) -> MediaProbe:
    if not path.is_file():
        raise FileNotFoundError(f"video does not exist: {path}")
    result = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    output = result.stderr
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not duration:
        raise RuntimeError(f"FFmpeg could not probe {path}: {output[-2000:]}")
    hours, minutes, seconds = duration.groups()
    video_line = next((line for line in output.splitlines() if "Video:" in line), "")
    audio_line = next((line for line in output.splitlines() if "Audio:" in line), "")
    size = re.search(r"(\d{2,5})x(\d{2,5})", video_line)
    fps = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line)
    video_codec = re.search(r"Video:\s*([a-zA-Z0-9_]+)", video_line)
    audio_codec = re.search(r"Audio:\s*([a-zA-Z0-9_]+)", audio_line)
    pixel = re.search(r",\s*([a-zA-Z0-9_]+)\s*\(", video_line)
    return MediaProbe(
        duration_s=int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        width=int(size.group(1)) if size else None,
        height=int(size.group(2)) if size else None,
        fps=float(fps.group(1)) if fps else None,
        video_codec=video_codec.group(1).lower() if video_codec else None,
        audio_codec=audio_codec.group(1).lower() if audio_codec else None,
        pixel_format=pixel.group(1) if pixel else None,
    )


def _analyze_filters(path: Path) -> tuple[list[float], list[float]]:
    result = subprocess.run(
        [
            ffmpeg_executable(), "-hide_banner", "-i", str(path),
            "-vf", "blackdetect=d=0.3:pix_th=0.02,freezedetect=n=-50dB:d=2.5",
            "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"FFmpeg visual QC failed: {result.stderr[-2000:]}")
    output = result.stderr
    black = [float(value) for value in re.findall(r"black_duration:\s*([0-9.]+)", output)]
    frozen = [float(value) for value in re.findall(r"freeze_duration:\s*([0-9.]+)", output)]
    return black, frozen


def _loudness(path: Path) -> tuple[float | None, float | None]:
    result = subprocess.run(
        [
            ffmpeg_executable(), "-hide_banner", "-i", str(path),
            "-af", "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json",
            "-vn", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"FFmpeg loudness QC failed: {result.stderr[-2000:]}")
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, re.S)
    if not blocks:
        return None, None
    data = json.loads(blocks[-1])
    try:
        return float(data["input_i"]), float(data["input_tp"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _caption_segments(payload: dict[str, Any]) -> list[CaptionSegment]:
    return [
        CaptionSegment(
            start=float(segment["start"]),
            end=float(segment["end"]),
            words=[
                CaptionWord(text=str(word["text"]), start=float(word["start"]), end=float(word["end"]))
                for word in segment["words"]
            ],
        )
        for segment in payload.get("segments", [])
    ]


def _has_roman_script(captions: dict[str, Any]) -> bool:
    words = [word for segment in captions.get("segments", []) for word in segment.get("words", [])]
    return all(not any("\u0900" <= char <= "\u097f" for char in word.get("text", ""))
               for word in words)


def _quality_dimensions(script: Script, props: dict[str, Any], alignment: dict[str, Any],
                        captions: dict[str, Any], sync: dict[str, Any], loudness: float | None,
                        layout_passed: bool) -> dict[str, float]:
    hook = next((beat for beat in script.beats if beat.role.value == "HOOK"), script.beats[0])
    hook_ok = word_count(hook.narration) <= 14 and not hook.narration.lower().startswith(
        ("aaj hum", "today we", "is video mein", "hello dosto", "namaste dosto")
    )
    roles = [beat.role.value for beat in script.beats]
    story_ok = roles == sorted(roles, key=ROLE_ORDER.index)
    accuracy_ok = all(claim.is_analogy or bool(claim.source_urls) for claim in script.claims)
    scenes = props.get("scenes", [])
    template_changes = sum(
        previous["template"] != current["template"]
        for previous, current in zip(scenes, scenes[1:])
    )
    visual_score = 15.0 * template_changes / max(1, len(scenes) - 1)
    visual_score = min(15.0, visual_score)
    caption_words = [word for segment in captions.get("segments", []) for word in segment.get("words", [])]
    reading_speeds = [
        len(segment.get("words", [])) / max(0.01, float(segment["end"]) - float(segment["start"]))
        for segment in captions.get("segments", [])
    ]
    clarity_ok = all(word_count(beat.headline) <= 12 for beat in script.beats)
    if reading_speeds:
        clarity_ok = clarity_ok and max(reading_speeds) <= 3.2
    caption_audio = 10.0 if sync.get("passed") and loudness is not None and abs(loudness + 14) <= 1.5 else 0.0
    props_ok = layout_passed and len(scenes) == len(script.beats)
    return {
        "hook": 20.0 if hook_ok else 0.0,
        "story_structure": 15.0 if story_ok else 0.0,
        "accuracy": 20.0 if accuracy_ok else 0.0,
        "visual_variety": visual_score,
        "caption_audio": caption_audio,
        "clarity": 10.0 if clarity_ok and caption_words else 0.0,
        "brand_consistency": 10.0 if props_ok else 0.0,
    }


def _check(name: str, passed: bool, measured: Any, limit: str) -> QCCheck:
    return QCCheck(name=name, severity="hard", passed=bool(passed), measured=str(measured), limit=limit)


def evaluate_qc(job_id: str, script: Script, props: dict[str, Any], alignment: dict[str, Any],
                captions: dict[str, Any], layout: dict[str, Any], media: MediaProbe,
                audio_metrics: Any, lufs: float | None, true_peak: float | None,
                black: list[float], frozen: list[float], cover: dict[str, Any],
                missing_assets: list[str], audio_video_duration_s: float | None = None) -> QCReport:
    sync = validate_caption_sync(
        _caption_segments(captions),
        [SimpleNamespace(**word) for word in alignment.get("words", [])],
    )
    boxes = layout.get("boxes", [])
    violations = safe_area_violations(boxes)
    layout_ok = bool(layout.get("safe_area_passed")) and not violations

    scene_rows = sorted(props.get("scenes", []), key=lambda row: row["from_frame"])
    scene_gaps = []
    cursor = 0
    for row in scene_rows:
        if row["from_frame"] != cursor:
            scene_gaps.append((cursor, row["from_frame"]))
        cursor = row["from_frame"] + row["duration_frames"]
    expected_frames = round(media.duration_s * 30)
    if abs(cursor - expected_frames) > 5:
        scene_gaps.append((cursor, expected_frames))
    roman_script = _has_roman_script(captions)

    checks = [
        _check("duration", 55 <= media.duration_s <= 80,
               f"{media.duration_s:.2f}s", "55-80s"),
        _check("resolution", (media.width, media.height) == (1080, 1920),
               f"{media.width}x{media.height}", "1080x1920, 9:16"),
        _check("frame_rate", media.fps is not None and abs(media.fps - 30) <= 0.01,
               media.fps, "constant 30 fps"),
        _check("video_codec", media.video_codec == "h264" and media.pixel_format == "yuv420p",
               f"{media.video_codec}/{media.pixel_format}", "H.264 High, yuv420p"),
        _check("audio_codec", media.audio_codec == "aac", media.audio_codec, "AAC"),
        _check("audio_video_duration", audio_video_duration_s is not None
               and abs(media.duration_s - audio_video_duration_s) <= 0.15,
               audio_video_duration_s, "A/V duration difference <=0.15s"),
        _check("audio_present_not_silent", audio_metrics.mean_db > -40,
               f"{audio_metrics.mean_db:.2f}dB", "mean > -40dB"),
        _check("silence", audio_metrics.longest_silence_s <= 1.2,
               f"{audio_metrics.longest_silence_s:.2f}s", "no silence >1.2s"),
        _check("integrated_loudness", lufs is not None and abs(lufs + 14) <= 1.5,
               f"{lufs} LUFS", "-14 LUFS +/-1.5"),
        _check("true_peak", true_peak is not None and true_peak <= -1.0,
               f"{true_peak} dBTP", "<=-1 dBTP"),
        _check("black_frames", max(black, default=0.0) <= 0.3, black, "no black >0.3s"),
        _check("frozen_frames", max(frozen, default=0.0) <= 2.5, frozen, "no freeze >2.5s"),
        _check("text_safe_area", layout_ok, violations or "0 violations", "0 outside/clipped/overlapping"),
        _check("caption_sync", sync["passed"],
               f"median={sync.get('median_s')}s max={sync.get('max_s')}s",
               "median<=0.04s, max<=0.12s"),
        _check("caption_script", roman_script,
               "Roman-script captions" if roman_script else "Devanagari found",
               "Roman-script Hinglish"),
        _check("scene_continuity", not scene_gaps, scene_gaps or "continuous", "0 gaps"),
        _check("cover", bool(cover.get("passed")), cover, "1080x1920 sRGB JPEG <8MB"),
        _check("assets", not missing_assets, missing_assets or "all resolved", "0 missing"),
    ]
    dimensions = _quality_dimensions(script, props, alignment, captions, sync, lufs, layout_ok)
    score = round(sum(dimensions.values()), 1)
    passed = all(check.passed for check in checks) and score >= 80
    return QCReport(
        job_id=job_id,
        checks=checks,
        verdict="pass" if passed else "fail",
        score=score,
        quality_dimensions=dimensions,
    )


def run_qc(files: JobFiles, script: Script, *, props_name: str = "render_props.json",
           alignment_name: str = "alignment.json", captions_name: str = "captions.json",
           layout_name: str = "layout_report.json", video_name: str = "final.mp4",
           cover_name: str = "cover.jpg") -> QCReport:
    props = files.read_artefact_data(props_name)
    alignment = files.read_artefact_data(alignment_name)
    captions = files.read_artefact_data(captions_name)
    layout = files.read_json(layout_name)
    video_path = files.path(video_name)
    media = probe_media(video_path)
    audio_path = Path(props["audio_path"])
    audio_metrics = inspect_audio(audio_path)
    lufs, true_peak = _loudness(video_path)
    black, frozen = _analyze_filters(video_path)
    cover = validate_cover(files.path(cover_name))
    missing_assets = [
        asset for asset in props.get("assets", [])
        if not (files.dir / asset).is_file()
    ]
    report = evaluate_qc(
        files.dir.name, script, props, alignment, captions, layout, media,
        audio_metrics, lufs, true_peak, black, frozen, cover, missing_assets,
        audio_video_duration_s=audio_metrics.duration_s,
    )
    files.write_json("qc_report.json", report.model_dump(mode="json"))
    return report
