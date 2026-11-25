from reels.contracts.models import PublishPackage
from reels.publishing.base import blocked_reasons
from reels.publishing.dryrun import DryRunPublisher

PKG = PublishPackage(job_id="j", video_path="final.mp4", cover_path="cover.jpg", caption="c",
                     hashtags=["#AI"], idempotency_key="k")


def test_blocked_without_qc_pass_or_approval():
    r = blocked_reasons(qc_verdict=None, approved=False)
    assert len(r) == 2
    res = DryRunPublisher().publish(PKG, r)
    assert res.status == "blocked" and res.blocked_reasons == r


def test_would_publish_only_when_all_guards_pass():
    res = DryRunPublisher().publish(PKG, blocked_reasons(qc_verdict="pass", approved=True))
    assert res.status == "would_publish" and res.detail["plan"][0]["params"]["media_type"] == "REELS"


def test_pipeline_phase1_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from reels import config
    from reels.orchestrator import Ctx, job_status, make_job_id, run_pipeline
    from reels.scripting.llm_client import build_llm
    from reels.storage.artifacts import JobFiles
    from reels.storage.db import JobStore
    from reels.contracts.models import Topic

    settings = config.load_settings()
    jid = make_job_id("AI tokens")
    ctx = Ctx(jid, settings, JobFiles(tmp_path, jid), JobStore(tmp_path / "t.db"), build_llm(settings, config.ROOT))
    Topic(id="t1", title="AI tokens")
    ctx.files.write_json("topic.json", {"id": "t1", "title": "AI tokens", "source": "manual"})
    ctx.store.create_job(jid, "AI tokens")

    summary = run_pipeline(ctx, until="plan_scenes")
    assert summary["validate_script"] == "succeeded" and summary["plan_scenes"] == "succeeded"
    assert ctx.files.exists("scene_plan.json")
    calls = ctx.llm.calls
    run_pipeline(ctx, until="plan_scenes")                      # resume: nothing re-runs
    assert ctx.llm.calls == calls

    # going past Phase 1 must BLOCK, never report success
    summary = run_pipeline(ctx, until="publish_to_instagram")
    assert summary["generate_voiceover"] == "blocked"
    assert job_status(ctx) == "blocked_awaiting_later_phase"
