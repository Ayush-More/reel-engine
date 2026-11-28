"""Stage registry, resume logic and failure policy.

Rules enforced here (not left to individual stages):
  * a stage is skipped only if its last run succeeded with an identical input hash (idempotent resume)
  * any exception marks the stage failed and STOPS the pipeline (no later stage runs on bad input)
  * stages that are not implemented in the current phase are recorded as 'blocked', never 'succeeded'
  * job status is derived from stage rows; 'ready_for_approval' requires every stage to be succeeded/skipped
    AND the QC report to be a pass
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .config import ROOT, Settings
from .contracts.models import Script, Topic
from .monitoring.logging import get_logger, job_id_var, stage_var
from .scripting.llm_client import LLMClient
from .scripting.script import ScriptGenerationError, generate_script
from .storage.artifacts import JobFiles, hash_obj, sha256_bytes
from .storage.db import BLOCKED, FAILED, SUCCEEDED, JobStore
from .validation.script_rules import has_errors, validate_script_rules

log = get_logger("orchestrator")
SKIPPED = "skipped"
FPS = 30


class NotImplementedInPhase(RuntimeError):
    pass


class CostGuardError(RuntimeError):
    """Raised when a paid stage would exceed a per-reel or per-day budget cap."""


class Skip(Exception):
    """Raised by a stage to record an explicit, reasoned skip."""


@dataclass
class Ctx:
    job_id: str
    settings: Settings
    files: JobFiles
    store: JobStore
    llm: LLMClient
    voice_provider: Any = None


@dataclass
class Stage:
    name: str
    fn: Callable[[Ctx], dict[str, Any]]
    deps: Callable[[Ctx], Any]
    phase: int = 1


def make_job_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30] or "topic"
    return f"job_{slug}_{hash_obj(title)[:6]}"


def _file_hash(ctx: Ctx, name: str) -> str | None:
    return sha256_bytes(ctx.files.path(name).read_bytes()) if ctx.files.exists(name) else None


# ---------------------------------------------------------------- stage functions
def discover_topic(ctx: Ctx) -> dict[str, Any]:
    if not ctx.files.exists("topic.json"):
        raise RuntimeError("topic.json missing; create the job with `reels new`")
    Topic.model_validate(ctx.files.read_json("topic.json"))
    return {}


def research_topic(ctx: Ctx) -> dict[str, Any]:
    raise Skip("Phase 2: no research/fetch stage yet; claims in the script stay verified=false")


def generate_concept(ctx: Ctx) -> dict[str, Any]:
    raise Skip("Phase 1: concept and hooks are produced inside generate_script")


def _check_cost_guard(ctx: Ctx) -> None:
    """Abort before paid stages if budget caps would be exceeded."""
    max_reel = float(ctx.settings.get("cost.max_per_reel_usd", 1.50))
    max_day = float(ctx.settings.get("cost.max_per_day_usd", 4.00))
    reel_cost = ctx.store.total_cost(ctx.job_id)
    day_cost = ctx.store.total_cost_today()
    if reel_cost >= max_reel:
        raise CostGuardError(f"reel cost ${reel_cost:.2f} >= cap ${max_reel:.2f}")
    if day_cost >= max_day:
        raise CostGuardError(f"daily cost ${day_cost:.2f} >= cap ${max_day:.2f}")


def generate_script_stage(ctx: Ctx) -> dict[str, Any]:
    _check_cost_guard(ctx)  # guard before paid LLM call
    topic = Topic.model_validate(ctx.files.read_json("topic.json"))
    rules = ctx.settings.script_rules
    input_hash = hash_obj(_script_stage_inputs(ctx))
    try:
        script, issues = generate_script(ctx.llm, topic, ROOT / "prompts", rules,
                                         max_repairs=int(ctx.settings.get("llm.max_repair_attempts", 2)))
    except ScriptGenerationError as exc:
        ctx.files.write_json("script.errors.json", {"errors": exc.errors})
        raise
    ctx.files.write_artefact("script.json", script.model_dump(mode="json"),
                             producer="scripting.script", input_hash=input_hash)
    ctx.files.write_json("script.issues.json", [str(i) for i in issues])
    return {}


def validate_script_stage(ctx: Ctx) -> dict[str, Any]:
    raw = ctx.files.read_json("script.json")
    # Support both envelope and plain formats
    data = raw["data"] if isinstance(raw, dict) and "data" in raw and "content_hash" in raw else raw
    script = Script.model_validate(data)  # re-validate from disk: hand edits are checked too
    issues = validate_script_rules(script, ctx.settings.script_rules)
    ctx.files.write_json("validation_report.json", [str(i) for i in issues])
    if has_errors(issues):
        raise ValueError("script rules failed: " + "; ".join(str(i) for i in issues if i.severity == "error"))
    input_hash = hash_obj(_validate_stage_inputs(ctx))
    ctx.files.write_artefact("script.validated.json", script.model_dump(mode="json"),
                             producer="validation.script_rules", input_hash=input_hash)
    return {}


def plan_scenes(ctx: Ctx) -> dict[str, Any]:
    raw = ctx.files.read_json("script.validated.json")
    data = raw["data"] if isinstance(raw, dict) and "data" in raw and "content_hash" in raw else raw
    script = Script.model_validate(data)
    scenes = []
    for b in script.beats:
        from_frame = round(b.start * FPS)
        scenes.append({
            "beat_id": b.id, "template": b.template.value, "from_frame": from_frame,
            "duration_frames": round(b.end * FPS) - from_frame, "props": b.props,
            "headline": b.headline, "transition": b.transition,
            "timing_source": "script_estimate",  # becomes 'audio_alignment' after Phase 2 retime
        })
    input_hash = hash_obj(_scene_plan_stage_inputs(ctx))
    ctx.files.write_artefact("scene_plan.json", {"fps": FPS, "size": [1080, 1920], "scenes": scenes},
                             producer="orchestrator.plan_scenes", input_hash=input_hash)
    return {}


def generate_voiceover(ctx: Ctx) -> dict[str, Any]:
    from .contracts.models import Script, VoiceMetadata
    from .voice.pronunciation import apply_overrides, load_overrides
    from .voice.provider import MockVoiceProvider, build_voice_provider

    script = Script.model_validate(ctx.files.read_artefact_data("script.validated.json"))
    override_path = ROOT / "config" / "pronunciation.yaml"
    overrides = load_overrides(override_path)
    spoken_beats = [
        {"beat_id": beat.id, "narration": apply_overrides(beat.narration, overrides)}
        for beat in script.beats
    ]
    spoken_text = " ".join(beat["narration"] for beat in spoken_beats)
    if ctx.voice_provider is None:
        ctx.voice_provider = build_voice_provider(ctx.settings)
    provider = ctx.voice_provider
    output_path = ctx.files.path("voice.wav" if isinstance(provider, MockVoiceProvider) else "voice.mp3")
    cache_dir = ROOT / "data" / "voice_cache"
    result = provider.synthesize(
        spoken_text,
        output_path,
        cache_dir,
        target_duration_s=script.estimated_duration_s,
        voice_id=ctx.settings.get("voice.voice_id"),
    )
    target_duration = script.estimated_duration_s
    max_deviation = float(ctx.settings.get("voice.max_duration_deviation", 0.08))
    deviation = abs(result.duration_s - target_duration) / target_duration
    if deviation > max_deviation:
        raise ValueError(
            f"voice duration {result.duration_s:.2f}s differs from plan {target_duration:.2f}s "
            f"by {deviation:.1%} (limit {max_deviation:.0%})"
        )
    max_silence = float(ctx.settings.get("voice.max_silence_s", 1.2))
    if result.longest_silence_s > max_silence:
        raise ValueError(f"voice contains {result.longest_silence_s:.2f}s silence (limit {max_silence:.2f}s)")
    voice_id = ctx.settings.get("voice.voice_id")
    metadata = VoiceMetadata(
        provider=result.provider,
        model=result.model,
        voice_id=voice_id,
        text_hash=result.text_hash,
        audio_path=str(result.path.resolve()),
        duration_s=result.duration_s,
        longest_silence_s=result.longest_silence_s,
        mean_db=result.mean_db,
        cache_hit=result.cache_hit,
    )
    ctx.files.write_json("spoken_script.json", {"beats": spoken_beats})
    ctx.files.write_artefact(
        "voice.meta.json",
        metadata.model_dump(mode="json"),
        producer=f"voice.{result.provider}",
        input_hash=hash_obj(_voice_stage_inputs(ctx)),
    )
    return {}


def align_audio(ctx: Ctx) -> dict[str, Any]:
    from .alignment.captions import group_captions
    from .alignment.providers import LocalFallbackAligner, align_with_fallback, build_aligner
    from .alignment.retime import retime_beats
    from .contracts.models import CaptionTrack, Script

    script = Script.model_validate(ctx.files.read_artefact_data("script.validated.json"))
    spoken = ctx.files.read_json("spoken_script.json")["beats"]
    spoken_by_id = {beat["beat_id"]: beat["narration"] for beat in spoken}
    beats = [
        beat.model_copy(update={"narration": spoken_by_id[beat.id]})
        for beat in script.beats
    ]
    voice = ctx.files.read_artefact_data("voice.meta.json")
    audio_path = Path(voice["audio_path"])
    primary = build_aligner(ctx.settings)
    fallback = LocalFallbackAligner()
    alignment = align_with_fallback(
        primary, fallback, audio_path, beats,
        min_coverage=float(ctx.settings.get("alignment.min_coverage", 0.98)),
    )
    if alignment.coverage < 0.98:
        raise ValueError(f"word alignment coverage {alignment.coverage:.1%} is below 98%")
    retimed = retime_beats(beats, alignment.words, alignment.audio_duration_s)
    retimed_data = [
        {"beat_id": beat_id, "start": start, "end": end}
        for beat_id, start, end in retimed
    ]
    segments = group_captions(
        alignment.words,
        max_words=int(ctx.settings.get("captions.max_words", 4)),
        max_chars=int(ctx.settings.get("captions.max_chars", 26)),
        max_seconds=float(ctx.settings.get("captions.max_seconds", 2.0)),
    )
    caption_track = CaptionTrack.model_validate({
        "language": "roman_hinglish",
        "segments": [
            {
                "start": segment.start,
                "end": segment.end,
                "words": [word.__dict__ for word in segment.words],
            }
            for segment in segments
        ],
    })
    input_hash = hash_obj(_alignment_stage_inputs(ctx))
    ctx.files.write_artefact("alignment.json", alignment.model_dump(mode="json"),
                             producer=f"alignment.{alignment.aligner}", input_hash=input_hash)
    ctx.files.write_artefact("retimed_beats.json", retimed_data,
                             producer="alignment.retime", input_hash=input_hash)
    ctx.files.write_artefact("captions.json", caption_track.model_dump(mode="json"),
                             producer="alignment.captions", input_hash=input_hash)
    return {}


def generate_visual_assets(ctx: Ctx) -> dict[str, Any]:
    from .contracts.models import Script
    from .visuals.planner import build_render_props

    script = Script.model_validate(ctx.files.read_artefact_data("script.validated.json"))
    voice = ctx.files.read_artefact_data("voice.meta.json")
    build_render_props(
        ctx.job_id,
        script,
        ctx.files.read_artefact_data("retimed_beats.json"),
        ctx.files.read_artefact_data("captions.json"),
        Path(voice["audio_path"]),
        ctx.files,
        assets=[],
    )
    return {}


def render_video_stage(ctx: Ctx) -> dict[str, Any]:
    import subprocess

    from .rendering.mock import render_fixture
    from .rendering.remotion import render_video

    props = ctx.files.read_artefact_data("render_props.json")
    mode = ctx.settings.get("rendering.mode", "mock")
    timeout = int(ctx.settings.get("rendering.timeout_s", 900))
    if mode not in ("mock", "remotion"):
        raise ValueError(f"unknown rendering.mode: {mode}")
    for attempt in range(2):
        try:
            if mode == "mock":
                render_fixture(props, ctx.files.path("raw.mp4"), ctx.files.path("render_fixture.png"),
                               timeout_s=timeout)
            else:
                render_video(
                    ctx.files.path("render_props.json"),
                    ctx.files.path("raw.mp4"),
                    timeout_s=timeout,
                    concurrency=1 if attempt else None,
                )
            break
        except (RuntimeError, subprocess.SubprocessError) as exc:
            if attempt:
                raise
            if ctx.files.path("raw.mp4").exists():
                ctx.files.path("raw.mp4").unlink()
            log.warning("render failed; retrying with lower concurrency",
                        extra={"data": {"attempt": 1, "error": str(exc)[:500]}})
    return {}


def postprocess_video_stage(ctx: Ctx) -> dict[str, Any]:
    from .rendering.ffmpeg_post import postprocess_video

    postprocess_video(
        ctx.files.path("raw.mp4"),
        ctx.files.path("final.mp4"),
        timeout_s=int(ctx.settings.get("rendering.timeout_s", 900)),
        integrated_lufs=float(ctx.settings.get("rendering.loudness_lufs", -14)),
        true_peak_dbtp=float(ctx.settings.get("rendering.true_peak_dbtp", -1)),
    )
    return {}


def generate_thumbnail_stage(ctx: Ctx) -> dict[str, Any]:
    from .contracts.models import Script
    from .thumbnails.cover import generate_cover

    script = Script.model_validate(ctx.files.read_artefact_data("script.validated.json"))
    generate_cover(script, ctx.files.path("cover.jpg"), ctx.files.path("final.mp4"))
    return {}


def validate_final_video_stage(ctx: Ctx) -> dict[str, Any]:
    from .contracts.models import Script
    from .qc.report import run_qc

    script = Script.model_validate(ctx.files.read_artefact_data("script.validated.json"))
    report = run_qc(ctx.files, script)
    if report.verdict != "pass":
        failed = [check.name for check in report.checks if not check.passed]
        raise ValueError(
            f"QC hard gates failed ({', '.join(failed)}); quality score {report.score:.1f}/100"
        )
    return {}


def _not_yet(phase: int, what: str) -> Callable[[Ctx], dict[str, Any]]:
    def fn(ctx: Ctx) -> dict[str, Any]:
        raise NotImplementedInPhase(f"Phase {phase}: {what}")
    return fn


def build_stages() -> list[Stage]:
    return [
        Stage("discover_topic", discover_topic, lambda c: _file_hash(c, "topic.json")),
        Stage("research_topic", research_topic, lambda c: "n/a"),
        Stage("generate_concept", generate_concept, lambda c: "n/a"),
        Stage("generate_script", generate_script_stage,
              _script_stage_inputs),
        Stage("validate_script", validate_script_stage, _validate_stage_inputs),
        Stage("plan_scenes", plan_scenes, _scene_plan_stage_inputs),
        Stage("generate_voiceover", generate_voiceover, _voice_stage_inputs, 2),
        Stage("align_audio", align_audio, _alignment_stage_inputs, 2),
        Stage("generate_visual_assets", generate_visual_assets, _visual_stage_inputs, 2),
        Stage("render_video", render_video_stage, _render_stage_inputs, 2),
        Stage("postprocess_video", postprocess_video_stage, _postprocess_stage_inputs, 2),
        Stage("generate_thumbnail", generate_thumbnail_stage, _thumbnail_stage_inputs, 2),
        Stage("validate_final_video", validate_final_video_stage, _qc_stage_inputs, 2),
        Stage("request_manual_approval", _not_yet(3, "approval queue UI"), lambda c: "-", 3),
        Stage("publish_to_instagram", _not_yet(3, "Graph API publisher"), lambda c: "-", 3),
    ]


def _file_hash_prompts() -> str:
    return hash_obj([(ROOT / "prompts" / n).read_text(encoding="utf-8") for n in ("script.md", "repair.md")])


def _file_tree_hash(path: Path, pattern: str) -> str:
    files = sorted(path.rglob(pattern))
    return hash_obj([
        (file.relative_to(path).as_posix(), sha256_bytes(file.read_bytes()))
        for file in files if file.is_file()
    ])


def _script_stage_inputs(ctx: Ctx) -> list[Any]:
    cfg = {"rules": ctx.settings.script_rules, "llm": ctx.settings.get("llm")}
    mock_input_hash = None
    if ctx.llm.name == "mock":
        example = ROOT / "examples" / "tokens_reel.json"
        mock_input_hash = hash_obj(example.read_text(encoding="utf-8"))
    return [_file_hash(ctx, "topic.json"), cfg, _file_hash_prompts(), mock_input_hash]


def _validate_stage_inputs(ctx: Ctx) -> list[Any]:
    cfg = {"rules": ctx.settings.script_rules, "llm": ctx.settings.get("llm")}
    return [_file_hash(ctx, "script.json"), cfg]


def _scene_plan_stage_inputs(ctx: Ctx) -> str | None:
    return _file_hash(ctx, "script.validated.json")


def _voice_stage_inputs(ctx: Ctx) -> list[Any]:
    return [
        _file_hash(ctx, "script.validated.json"),
        ctx.settings.get("voice"),
        hash_obj((ROOT / "config" / "pronunciation.yaml").read_text(encoding="utf-8")),
    ]


def _alignment_stage_inputs(ctx: Ctx) -> list[Any]:
    return [
        _file_hash(ctx, "voice.meta.json"),
        _file_hash(ctx, "spoken_script.json"),
        ctx.settings.get("alignment"),
        ctx.settings.get("captions"),
    ]


def _visual_stage_inputs(ctx: Ctx) -> list[Any]:
    return [
        _file_hash(ctx, "script.validated.json"),
        _file_hash(ctx, "retimed_beats.json"),
        _file_hash(ctx, "captions.json"),
        _file_hash(ctx, "voice.meta.json"),
    ]


def _render_stage_inputs(ctx: Ctx) -> list[Any]:
    props = ctx.files.read_artefact_data("render_props.json") if ctx.files.exists("render_props.json") else None
    audio_path = Path(props["audio_path"]) if props else None
    audio_hash = hash_obj(audio_path.read_bytes()) if audio_path and audio_path.is_file() else None
    mode = ctx.settings.get("rendering.mode", "mock")
    renderer_hash = (
        [
            _file_tree_hash(ROOT / "renderer", "*.tsx"),
            _file_tree_hash(ROOT / "renderer", "*.ts"),
            sha256_bytes((ROOT / "renderer" / "package.json").read_bytes()),
        ]
        if mode == "remotion" else None
    )
    return [_file_hash(ctx, "render_props.json"), audio_hash, mode, renderer_hash]


def _postprocess_stage_inputs(ctx: Ctx) -> list[Any]:
    return [_file_hash(ctx, "raw.mp4"), ctx.settings.get("rendering")]


def _thumbnail_stage_inputs(ctx: Ctx) -> list[Any]:
    return [_file_hash(ctx, "final.mp4"), _file_hash(ctx, "script.validated.json")]


def _qc_stage_inputs(ctx: Ctx) -> list[Any]:
    return [
        _file_hash(ctx, "final.mp4"),
        _file_hash(ctx, "cover.jpg"),
        _file_hash(ctx, "render_props.json"),
        _file_hash(ctx, "alignment.json"),
        _file_hash(ctx, "captions.json"),
        _file_hash(ctx, "layout_report.json"),
    ]


# ---------------------------------------------------------------- runner
def run_pipeline(ctx: Ctx, until: str = "plan_scenes", force: bool = False) -> dict[str, str]:
    stages = build_stages()
    names = [s.name for s in stages]
    if until not in names:
        raise ValueError(f"unknown stage {until!r}; choose from {names}")
    job_id_var.set(ctx.job_id)

    for stage in stages:
        stage_var.set(stage.name)
        input_hash = hash_obj(stage.deps(ctx))
        last = ctx.store.last_run(ctx.job_id, stage.name)
        if (not force and last and last["status"] in (SUCCEEDED, SKIPPED) and last["input_hash"] == input_hash):
            log.info("stage cached, skipping")
        else:
            run_id = ctx.store.start_stage(ctx.job_id, stage.name, input_hash)
            try:
                out = stage.fn(ctx)
                ctx.store.finish_stage(run_id, SUCCEEDED, cost_usd=float(out.get("cost_usd", 0.0)))
                log.info("stage succeeded")
            except Skip as why:
                ctx.store.finish_stage(run_id, SKIPPED, error=str(why))
                log.info("stage skipped", extra={"data": {"reason": str(why)}})
            except NotImplementedInPhase as why:
                ctx.store.finish_stage(run_id, BLOCKED, error=str(why))
                log.warning("stage blocked", extra={"data": {"reason": str(why)}})
                break  # nothing downstream may run, and the job is NOT ready
            except CostGuardError as exc:
                ctx.store.finish_stage(run_id, FAILED, error=str(exc)[:2000])
                log.error("cost guard blocked stage", extra={"data": {"error": str(exc)[:500]}})
                break
            except (ScriptGenerationError, ValidationError, ValueError, RuntimeError) as exc:
                ctx.store.finish_stage(run_id, FAILED, error=str(exc)[:2000])
                log.error("stage failed", extra={"data": {"error": str(exc)[:500]}})
                break
            except Exception as exc:  # unexpected: still recorded, never swallowed
                ctx.store.finish_stage(run_id, FAILED, error=f"unexpected {type(exc).__name__}: {exc}"[:2000])
                log.exception("stage crashed")
                break
        if stage.name == until:
            break
    stage_var.set("-")
    return ctx.store.stage_summary(ctx.job_id)


def job_status(ctx: Ctx) -> str:
    summary = ctx.store.stage_summary(ctx.job_id)
    names = [s.name for s in build_stages() if s.phase <= 2]
    if any(v == FAILED for v in summary.values()):
        return "failed"
    if any(v == BLOCKED for v in summary.values()):
        return "blocked_awaiting_later_phase"
    if all(summary.get(n) in (SUCCEEDED, SKIPPED) for n in names):
        qc = ctx.files.read_json("qc_report.json") if ctx.files.exists("qc_report.json") else None
        return "ready_for_approval" if qc and qc.get("verdict") == "pass" else "incomplete_no_qc"
    return "in_progress"
