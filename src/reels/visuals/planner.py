"""Build typed Remotion input from validated script, retimed beats, and captions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts.models import CaptionTrack, RenderProps, Script
from ..storage.artifacts import JobFiles, hash_obj
from .layout import build_layout_report

FPS = 30


def build_render_props(job_id: str, script: Script, retimed_beats: list[dict[str, Any]],
                       captions: dict[str, Any], audio_path: Path,
                       files: JobFiles, assets: list[str] | None = None) -> RenderProps:
    time_by_id = {beat["beat_id"]: beat for beat in retimed_beats}
    scenes = []
    for beat in script.beats:
        timing = time_by_id[beat.id]
        start = float(timing["start"])
        end = float(timing["end"])
        from_frame = round(start * FPS)
        end_frame = round(end * FPS)
        scenes.append({
            "beat_id": beat.id,
            "template": beat.template.value,
            "from_frame": from_frame,
            "duration_frames": end_frame - from_frame,
            "headline": beat.headline,
            "props": beat.props,
            "transition": beat.transition,
        })
    caption_track = CaptionTrack.model_validate(captions)
    render_props = RenderProps(
        job_id=job_id,
        fps=FPS,
        audio_path=str(audio_path.resolve()),
        scenes=scenes,
        captions=caption_track,
        assets=assets or [],
    )
    report = build_layout_report(script, caption_track.model_dump(mode="json"))
    if not report.safe_area_passed:
        raise ValueError("renderer layout failed safe-area preflight: " + "; ".join(report.violations))
    files.write_json("layout_report.json", report.model_dump(mode="json"))
    files.write_artefact(
        "render_props.json",
        render_props.model_dump(mode="json"),
        producer="visuals.planner",
        input_hash=hash_obj([script.model_dump(mode="json"), retimed_beats, captions, str(audio_path)]),
    )
    return render_props
