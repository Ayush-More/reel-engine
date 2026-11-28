"""Command line entry point: `reels --help`. Typer-based CLI (Phase 1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .config import ROOT, load_settings
from .contracts.models import (
    Alignment,
    CaptionTrack,
    QCReport,
    ReelProject,
    RenderProps,
    Script,
    Topic,
    PublishPackage,
)
from .monitoring.logging import setup_logging
from .orchestrator import Ctx, job_status, make_job_id, run_pipeline
from .publishing.base import blocked_reasons
from .publishing.dryrun import DryRunPublisher
from .scripting.llm_client import build_llm
from .storage.artifacts import JobFiles, hash_obj
from .storage.db import JobStore

app = typer.Typer(
    name="reels",
    help="Tech explainer Reels engine (Phase 1 and local Phase 2)",
    no_args_is_help=True,
)


def _ctx(job_id: str) -> Ctx:
    settings = load_settings()
    setup_logging(settings.logs_dir)
    return Ctx(job_id, settings, JobFiles(settings.jobs_dir, job_id), JobStore(settings.db_path),
               build_llm(settings, ROOT))


@app.command()
def new(
    topic: str = typer.Option(..., help="Topic title for the new Reel"),
    until: str = typer.Option("plan_scenes", help="Run pipeline up to this stage"),
    force: bool = typer.Option(False, help="Force re-run of completed stages"),
) -> None:
    """Create a job from a topic and run the pipeline."""
    job_id = make_job_id(topic)
    ctx = _ctx(job_id)
    topic_obj = Topic(id=f"topic_{hash_obj(topic)[:8]}", title=topic, source="manual")
    ctx.files.write_json("topic.json", topic_obj.model_dump(mode="json"))
    ctx.store.create_job(job_id, topic)
    summary = run_pipeline(ctx, until=until, force=force)
    typer.echo(json.dumps({"job_id": job_id, "stages": summary, "status": job_status(ctx),
                           "folder": str(ctx.files.dir)}, indent=2))
    raise SystemExit(0 if "failed" not in summary.values() else 1)


@app.command()
def run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    until: str = typer.Option("plan_scenes", help="Run pipeline up to this stage"),
    force: bool = typer.Option(False, help="Force re-run of completed stages"),
) -> None:
    """(Re)run a job; completed stages are skipped."""
    ctx = _ctx(job_id)
    summary = run_pipeline(ctx, until=until, force=force)
    typer.echo(json.dumps({"stages": summary, "status": job_status(ctx)}, indent=2))
    raise SystemExit(0 if "failed" not in summary.values() else 1)


@app.command()
def status(job_id: str = typer.Argument(..., help="Job ID to check")) -> None:
    """Show status of a job."""
    ctx = _ctx(job_id)
    typer.echo(json.dumps({"status": job_status(ctx), "stages": ctx.store.stage_summary(job_id),
                           "cost_usd": ctx.store.total_cost(job_id),
                           "approved": ctx.store.is_approved(job_id)}, indent=2))


@app.command()
def script(
    topic: str = typer.Argument(..., help="Topic to generate a script for"),
) -> None:
    """Generate a script for a topic (runs only the script stage)."""
    job_id = make_job_id(topic)
    ctx = _ctx(job_id)
    topic_obj = Topic(id=f"topic_{hash_obj(topic)[:8]}", title=topic, source="manual")
    ctx.files.write_json("topic.json", topic_obj.model_dump(mode="json"))
    ctx.store.create_job(job_id, topic)
    summary = run_pipeline(ctx, until="generate_script", force=False)
    typer.echo(json.dumps({"job_id": job_id, "stages": summary, "folder": str(ctx.files.dir)}, indent=2))
    raise SystemExit(0 if "failed" not in summary.values() else 1)


@app.command(name="plan-scenes")
def plan_scenes_cmd(
    job_id: str = typer.Argument(..., help="Job ID whose scenes to plan"),
    force: bool = typer.Option(False, help="Force re-run"),
) -> None:
    """Plan scenes for an existing job (runs from validate_script through plan_scenes)."""
    ctx = _ctx(job_id)
    summary = run_pipeline(ctx, until="plan_scenes", force=force)
    typer.echo(json.dumps({"stages": summary, "status": job_status(ctx)}, indent=2))
    raise SystemExit(0 if "failed" not in summary.values() else 1)


@app.command()
def render(
    job_id: str = typer.Argument(..., help="Validated Phase 1 job to render"),
    mode: str = typer.Option("mock", help="Render backend: mock (offline) or remotion"),
    force: bool = typer.Option(False, help="Force re-run of completed Phase 2 stages"),
) -> None:
    """Run voice, alignment, captions, rendering, cover, and QC for a job."""
    ctx = _ctx(job_id)
    if mode not in ("mock", "remotion"):
        typer.echo("mode must be 'mock' or 'remotion'", err=True)
        raise SystemExit(2)
    ctx.settings.raw.setdefault("rendering", {})["mode"] = mode
    summary = run_pipeline(ctx, until="validate_final_video", force=force)
    typer.echo(json.dumps({"job_id": job_id, "stages": summary, "status": job_status(ctx),
                           "folder": str(ctx.files.dir)}, indent=2))
    raise SystemExit(0 if summary.get("validate_final_video") == "succeeded" else 1)


@app.command()
def validate(file: str = typer.Argument(..., help="Script or project JSON file to validate")) -> None:
    """Validate any script/project JSON file against the contract and rules (no job needed)."""
    from .validation.script_rules import has_errors, validate_script_rules
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    script_data = data["script"] if "script" in data else data
    # Support artefact envelope format
    if isinstance(script_data, dict) and "data" in script_data and "content_hash" in script_data:
        script_data = script_data["data"]
    script_obj = Script.model_validate(script_data)
    issues = validate_script_rules(script_obj, load_settings().script_rules)
    for i in issues:
        typer.echo(str(i))
    typer.echo(f"RESULT: {'FAIL' if has_errors(issues) else 'PASS'}")
    raise SystemExit(1 if has_errors(issues) else 0)


@app.command()
def approve(
    job_id: str = typer.Argument(..., help="Job ID to approve"),
    by: str = typer.Option("local", help="Who approved"),
    note: str = typer.Option("", help="Approval note"),
    reject: bool = typer.Option(False, help="Reject instead of approve"),
) -> None:
    """Approve or reject a job."""
    ctx = _ctx(job_id)
    ctx.store.set_approval(job_id, not reject, by, note)
    typer.echo(f"{'rejected' if reject else 'approved'} {job_id}")


@app.command()
def publish(
    job_id: str = typer.Argument(..., help="Job ID to publish"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run only"),
) -> None:
    """Publish a reel (Phase 1: dry-run only)."""
    ctx = _ctx(job_id)
    if not dry_run:
        typer.echo("Live publishing is not available in Phase 1. Use --dry-run.", err=True)
        raise SystemExit(2)
    _do_dry_run(ctx, job_id)


@app.command(name="dry-run")
def dry_run(job_id: str = typer.Argument(..., help="Job ID to dry-run publish")) -> None:
    """Dry-run publish a reel (alias for publish --dry-run)."""
    ctx = _ctx(job_id)
    _do_dry_run(ctx, job_id)


def _do_dry_run(ctx: Ctx, job_id: str) -> None:
    raw = ctx.files.read_json("script.validated.json")
    data = raw["data"] if isinstance(raw, dict) and "data" in raw and "content_hash" in raw else raw
    script_obj = Script.model_validate(data)
    qc = ctx.files.read_json("qc_report.json") if ctx.files.exists("qc_report.json") else None
    key = hash_obj([job_id, ctx.files.path("final.mp4").name, script_obj.meta.title])
    reasons = blocked_reasons(qc_verdict=(qc or {}).get("verdict"), approved=ctx.store.is_approved(job_id),
                              require_approval=bool(ctx.settings.get("publishing.require_approval", True)),
                              already_published=ctx.store.published_live(key))
    pkg = PublishPackage(job_id=job_id, video_path=str(ctx.files.path("final.mp4")),
                         cover_path=str(ctx.files.path("cover.jpg")), caption=script_obj.meta.instagram_caption,
                         hashtags=script_obj.meta.hashtags, idempotency_key=key)
    result = DryRunPublisher().publish(pkg, reasons)
    ctx.store.record_publish(key, job_id, "dry_run", result.status)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def schema() -> None:
    """Export JSON Schemas for the renderer."""
    out = ROOT / "schemas"
    out.mkdir(exist_ok=True)
    models = {
        "script": Script,
        "reel_project": ReelProject,
        "render_props": RenderProps,
        "alignment": Alignment,
        "captions": CaptionTrack,
        "qc_report": QCReport,
    }
    for name, model in models.items():
        (out / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
    typer.echo(f"wrote JSON Schemas to {out}")


def main(argv: list[str] | None = None) -> int:
    """Entry point that returns an int exit code for compatibility."""
    try:
        app(argv, standalone_mode=False)
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
