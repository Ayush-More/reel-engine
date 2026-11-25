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
from .storage.artifacts import JobFiles, hash_obj
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
    return hash_obj(ctx.files.path(name).read_text(encoding="utf-8")) if ctx.files.exists(name) else None


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
    input_hash = hash_obj([ctx.files.read_json("topic.json"), rules])
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
    input_hash = hash_obj([data, ctx.settings.script_rules])
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
    input_hash = hash_obj(data)
    ctx.files.write_artefact("scene_plan.json", {"fps": FPS, "size": [1080, 1920], "scenes": scenes},
                             producer="orchestrator.plan_scenes", input_hash=input_hash)
    return {}


def _not_yet(phase: int, what: str) -> Callable[[Ctx], dict[str, Any]]:
    def fn(ctx: Ctx) -> dict[str, Any]:
        raise NotImplementedInPhase(f"Phase {phase}: {what}")
    return fn


def build_stages() -> list[Stage]:
    cfg = lambda ctx: {"rules": ctx.settings.script_rules, "llm": ctx.settings.get("llm")}
    return [
        Stage("discover_topic", discover_topic, lambda c: _file_hash(c, "topic.json")),
        Stage("research_topic", research_topic, lambda c: "n/a"),
        Stage("generate_concept", generate_concept, lambda c: "n/a"),
        Stage("generate_script", generate_script_stage,
              lambda c: [_file_hash(c, "topic.json"), cfg(c), _file_hash_prompts()]),
        Stage("validate_script", validate_script_stage, lambda c: [_file_hash(c, "script.json"), cfg(c)]),
        Stage("plan_scenes", plan_scenes, lambda c: _file_hash(c, "script.validated.json")),
        Stage("generate_voiceover", _not_yet(2, "ElevenLabs TTS"), lambda c: "-", 2),
        Stage("align_audio", _not_yet(2, "forced alignment"), lambda c: "-", 2),
        Stage("generate_visual_assets", _not_yet(2, "render_props + assets"), lambda c: "-", 2),
        Stage("render_video", _not_yet(2, "Remotion render"), lambda c: "-", 2),
        Stage("generate_thumbnail", _not_yet(2, "cover generation"), lambda c: "-", 2),
        Stage("validate_final_video", _not_yet(2, "QC gates"), lambda c: "-", 2),
        Stage("request_manual_approval", _not_yet(3, "approval queue UI"), lambda c: "-", 3),
        Stage("publish_to_instagram", _not_yet(3, "Graph API publisher"), lambda c: "-", 3),
    ]


def _file_hash_prompts() -> str:
    return hash_obj([(ROOT / "prompts" / n).read_text(encoding="utf-8") for n in ("script.md", "repair.md")])


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
    names = [s.name for s in build_stages()]
    if any(v == FAILED for v in summary.values()):
        return "failed"
    if any(v == BLOCKED for v in summary.values()):
        return "blocked_awaiting_later_phase"
    if all(summary.get(n) in (SUCCEEDED, SKIPPED) for n in names):
        qc = ctx.files.read_json("qc_report.json") if ctx.files.exists("qc_report.json") else None
        return "ready_for_approval" if qc and qc.get("verdict") == "pass" else "incomplete_no_qc"
    return "in_progress"
