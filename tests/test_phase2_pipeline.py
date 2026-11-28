import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from reels.alignment.providers import ProportionalAligner, align_with_fallback
from reels.contracts.models import Script, Topic
from reels.orchestrator import Ctx, job_status, make_job_id, run_pipeline
from reels.qc.report import MediaProbe, evaluate_qc
from reels.storage.artifacts import JobFiles
from reels.storage.db import JobStore
from reels.voice.audio import inspect_audio
from reels.voice.pronunciation import apply_overrides, load_overrides
from reels.voice.provider import ElevenLabsVoiceProvider, MockVoiceProvider
from reels.visuals.layout import build_layout_report, safe_area_violations


ROOT = Path(__file__).resolve().parents[1]


def test_mock_voice_is_cached_and_has_duration_and_silence_metrics(tmp_path):
    provider = MockVoiceProvider()
    text = "AI tumhari line padhta hi nahi hai"
    first = provider.synthesize(text, tmp_path / "voice.wav", tmp_path / "cache",
                                target_duration_s=3.0)
    second = provider.synthesize(text, tmp_path / "voice-again.wav", tmp_path / "cache",
                                 target_duration_s=3.0)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert provider.calls == 1
    metrics = inspect_audio(first.path)
    assert metrics.duration_s == pytest.approx(3.0, abs=0.01)
    assert metrics.mean_db > -40
    assert metrics.longest_silence_s < 1.2


def test_pronunciation_overrides_are_case_insensitive(tmp_path):
    path = tmp_path / "pronunciation.yaml"
    path.write_text("replacements:\n  tokenizer: toe-ken-eye-zer\n", encoding="utf-8")
    overrides = load_overrides(path)
    assert apply_overrides("The TOKENIZER splits text.", overrides) == "The toe-ken-eye-zer splits text."


def test_elevenlabs_retries_rate_limit_then_uses_text_cache(tmp_path, monkeypatch):
    import httpx

    fixture = MockVoiceProvider().synthesize(
        "offline audio fixture", tmp_path / "fixture.wav", tmp_path / "fixture-cache",
        target_duration_s=1,
    )
    audio_bytes = fixture.path.read_bytes()
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, request=request, text="rate limited")
        return httpx.Response(200, request=request, content=audio_bytes)

    monkeypatch.setattr("reels.voice.provider.time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = ElevenLabsVoiceProvider(
        api_key="test-key", retries=2, client=client,
    )
    first = provider.synthesize(
        "test speech", tmp_path / "speech.mp3", tmp_path / "eleven-cache",
        target_duration_s=1, voice_id="test-voice",
    )
    second = provider.synthesize(
        "test speech", tmp_path / "speech-again.mp3", tmp_path / "eleven-cache",
        target_duration_s=1, voice_id="test-voice",
    )
    assert len(requests) == 2
    assert requests[0].headers["xi-api-key"] == "test-key"
    assert first.cache_hit is False and second.cache_hit is True
    assert first.text_hash == second.text_hash


def test_alignment_uses_word_timings_and_falls_back(tmp_path, script):
    provider = MockVoiceProvider()
    audio = provider.synthesize(
        " ".join(beat.narration for beat in script.beats),
        tmp_path / "voice.wav",
        tmp_path / "cache",
        target_duration_s=script.estimated_duration_s,
    )

    class BrokenAligner:
        name = "broken"

        def align(self, audio_path, beats):
            raise RuntimeError("offline provider unavailable")

    fallback = ProportionalAligner()
    result = align_with_fallback(BrokenAligner(), fallback, audio.path, script.beats)
    assert result.aligner == "proportional_mock"
    assert result.coverage == 1
    assert result.words[0].start == 0
    assert result.words[-1].end == pytest.approx(result.audio_duration_s)


def test_layout_guard_enforces_all_blueprint_reservations(script):
    report = build_layout_report(script)
    assert report.safe_area_passed
    assert not report.violations
    assert safe_area_violations([
        {"name": "right-overflow", "x": 897, "y": 700, "width": 100, "height": 100, "zone": "stage"}
    ]) == ["right-overflow violates 120px stage right buffer"]
    assert "outside safe area" in safe_area_violations([
        {"name": "bottom-overflow", "x": 64, "y": 1441, "width": 100, "height": 10, "zone": "caption"}
    ])[0]
    changed = script.model_copy(update={
        "beats": [script.beats[0].model_copy(update={"headline": "word" * 60}), *script.beats[1:]]
    })
    assert any("exceeds two lines" in message for message in build_layout_report(changed).violations)


def test_cover_generator_writes_valid_srgb_jpeg(tmp_path, script):
    from reels.thumbnails.cover import generate_cover, validate_cover

    cover = generate_cover(script, tmp_path / "cover.jpg")
    result = validate_cover(cover)
    assert result["passed"] is True
    assert result["width"] == 1080 and result["height"] == 1920
    assert result["format"] == "JPEG" and result["srgb"] is True


def test_qc_hard_gates_fail_closed_for_broken_media(script):
    report = evaluate_qc(
        "job_bad",
        script,
        {"scenes": []},
        {"words": [{"text": "not-captioned", "start": 0.0, "end": 0.5}]},
        {"segments": [{"start": 0.0, "end": 0.5, "words": [
            {"text": "हिंदी", "start": 0.0, "end": 0.5}
        ]}]},
        {"safe_area_passed": False, "boxes": []},
        MediaProbe(20, 720, 1280, 24, "h264", "aac", "yuv420p"),
        SimpleNamespace(mean_db=-60, longest_silence_s=4.0, duration_s=20),
        lufs=-30,
        true_peak=-0.5,
        black=[1.0],
        frozen=[4.0],
        cover={"passed": False},
        missing_assets=["font.otf"],
        audio_video_duration_s=20,
    )
    assert report.verdict == "fail"
    failed = {check.name for check in report.checks if not check.passed}
    assert {"duration", "resolution", "frame_rate", "audio_present_not_silent",
            "silence", "integrated_loudness", "true_peak", "black_frames",
            "frozen_frames", "text_safe_area", "caption_script", "scene_continuity",
            "cover", "assets"} <= failed


def _phase2_root(tmp_path, project_json):
    root = tmp_path / "repo"
    for folder in ("examples", "prompts", "config"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "examples" / "tokens_reel.json").write_text(json.dumps(project_json), encoding="utf-8")
    for name in ("script.md", "repair.md"):
        shutil.copyfile(ROOT / "prompts" / name, root / "prompts" / name)
    (root / "config" / "pronunciation.yaml").write_text("replacements: {}\n", encoding="utf-8")
    return root


def test_offline_phase2_pipeline_outputs_video_cover_qc_and_resumes(tmp_path, monkeypatch, project_json):
    import reels.orchestrator as orchestrator
    import reels.rendering.mock as mock_renderer
    import reels.thumbnails.cover as cover_generator
    from reels.config import Settings
    from reels.scripting.llm_client import MockLLM

    root = _phase2_root(tmp_path, project_json)
    monkeypatch.setattr(orchestrator, "ROOT", root)
    monkeypatch.setattr(mock_renderer, "ROOT", root)
    monkeypatch.setattr(cover_generator, "ROOT", root)
    settings = Settings(raw={
        "script": {
            "min_duration_s": 55, "max_duration_s": 80, "max_words_per_second": 3.6,
            "max_hook_words": 14, "max_headline_words": 12, "max_beat_seconds": 12,
            "banned_openers": ["today we"],
        },
        "llm": {"provider": "mock", "max_repair_attempts": 2},
        "voice": {"provider": "mock", "max_duration_deviation": 0.08, "max_silence_s": 1.2},
        "alignment": {"provider": "mock", "min_coverage": 0.98},
        "captions": {"max_words": 4, "max_chars": 26, "max_seconds": 2.0},
        "rendering": {"mode": "mock", "fps": 30, "width": 1080, "height": 1920, "timeout_s": 300},
    })
    topic = "Offline Phase 2 test"
    job_id = make_job_id(topic)
    files = JobFiles(tmp_path / "jobs", job_id)
    store = JobStore(tmp_path / "reels.db")
    store.create_job(job_id, topic)
    files.write_json("topic.json", Topic(id="topic_test", title=topic).model_dump(mode="json"))
    llm = MockLLM(root / "examples" / "tokens_reel.json")
    ctx = Ctx(job_id, settings, files, store, llm)

    summary = run_pipeline(ctx, until="validate_final_video")

    assert summary["generate_voiceover"] == "succeeded"
    assert summary["align_audio"] == "succeeded"
    assert summary["generate_visual_assets"] == "succeeded"
    assert summary["render_video"] == "succeeded"
    assert summary["postprocess_video"] == "succeeded"
    assert summary["generate_thumbnail"] == "succeeded"
    assert summary["validate_final_video"] == "succeeded"
    assert job_status(ctx) == "ready_for_approval"
    assert all(files.exists(name) for name in (
        "voice.meta.json", "alignment.json", "retimed_beats.json", "captions.json",
        "render_props.json", "raw.mp4", "final.mp4", "cover.jpg", "qc_report.json",
    ))
    report = files.read_json("qc_report.json")
    assert report["verdict"] == "pass", report
    assert report["score"] >= 80

    stage_runs = {
        name: store.last_run(job_id, name)["id"]
        for name in ("generate_voiceover", "align_audio", "render_video", "validate_final_video")
    }
    llm_calls = llm.calls
    summary = run_pipeline(ctx, until="validate_final_video")
    assert summary["validate_final_video"] == "succeeded"
    assert llm.calls == llm_calls
    assert stage_runs == {
        name: store.last_run(job_id, name)["id"]
        for name in stage_runs
    }
