"""Tests for new Phase 1 features: duration estimation, artefact metadata,
cost guard, OpenAI LLM provider."""
import json
from pathlib import Path

import pytest

from reels.storage.artifacts import JobFiles, hash_obj
from reels.storage.db import JobStore, SUCCEEDED
from reels.validation.script_rules import estimate_duration, validate_script_rules, has_errors, DEFAULT_WPS
from reels.scripting.llm_client import MockLLM, OpenAILLM, build_llm


class TestDurationEstimation:
    def test_estimate_at_default_wps(self):
        # "one two three four five" = 5 words / 2.4 wps ≈ 2.08s
        d = estimate_duration("one two three four five")
        assert abs(d - 5 / DEFAULT_WPS) < 0.01

    def test_zero_words_returns_zero(self):
        assert estimate_duration("") == 0.0

    def test_hinglish_mixed_text(self):
        d = estimate_duration("AI tumhari line padhta hi nahi hai")
        assert d > 0  # 7 words / 2.4 ≈ 2.9s
        assert abs(d - 7 / DEFAULT_WPS) < 0.01

    def test_beat_duration_within_tolerance_no_warning(self, script):
        """Example script beats are designed to be within 15% tolerance."""
        issues = validate_script_rules(script)
        duration_warnings = [i for i in issues if i.code == "duration_estimate_beat" and i.severity == "error"]
        assert len(duration_warnings) == 0  # these are warnings, not errors


class TestArtefactMetadata:
    def test_write_artefact_has_metadata_fields(self, tmp_path):
        jf = JobFiles(tmp_path, "job_meta_test")
        jf.write_artefact("test.json", {"key": "value"}, producer="test.module", input_hash="abc123")
        raw = jf.read_json("test.json")
        assert "created_at" in raw
        assert raw["producer"] == "test.module"
        assert raw["input_hash"] == "abc123"
        assert raw["content_hash"] == hash_obj({"key": "value"})
        assert raw["data"] == {"key": "value"}

    def test_read_artefact_data_unwraps_envelope(self, tmp_path):
        jf = JobFiles(tmp_path, "job_unwrap")
        jf.write_artefact("wrapped.json", {"inner": 42}, producer="p", input_hash="h")
        data = jf.read_artefact_data("wrapped.json")
        assert data == {"inner": 42}

    def test_read_artefact_data_on_plain_json(self, tmp_path):
        jf = JobFiles(tmp_path, "job_plain")
        jf.write_json("plain.json", {"direct": True})
        data = jf.read_artefact_data("plain.json")
        assert data == {"direct": True}


class TestCostGuard:
    def test_total_cost_today(self, tmp_path):
        st = JobStore(tmp_path / "cost.db")
        st.create_job("j1", "topic1")
        r1 = st.start_stage("j1", "s1", "h1")
        st.finish_stage(r1, SUCCEEDED, cost_usd=0.50)
        r2 = st.start_stage("j1", "s2", "h2")
        st.finish_stage(r2, SUCCEEDED, cost_usd=0.30)
        assert st.total_cost_today() == pytest.approx(0.80)

    def test_cost_guard_blocks_expensive_job(self, tmp_path, monkeypatch):
        """When reel cost >= cap, generate_script_stage should raise CostGuardError."""
        from reels.orchestrator import CostGuardError, _check_cost_guard, Ctx
        from reels.config import load_settings, ROOT
        monkeypatch.setenv("REELS_ROOT", str(Path(__file__).resolve().parents[1]))

        settings = load_settings()
        settings.raw.setdefault("cost", {})["max_per_reel_usd"] = 0.01  # very low cap

        st = JobStore(tmp_path / "guard.db")
        jf = JobFiles(tmp_path, "j_guard")
        st.create_job("j_guard", "topic")
        r1 = st.start_stage("j_guard", "s1", "h1")
        st.finish_stage(r1, SUCCEEDED, cost_usd=0.50)

        from reels.scripting.llm_client import MockLLM
        ctx = Ctx("j_guard", settings, jf, st, MockLLM(ROOT / "examples" / "tokens_reel.json"))
        with pytest.raises(CostGuardError, match="reel cost"):
            _check_cost_guard(ctx)


class TestOpenAIProvider:
    def test_build_llm_openai_requires_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        class FakeSettings:
            def get(self, key, default=None):
                if key == "llm.provider":
                    return "openai"
                if key == "llm.model":
                    return "gpt-4o"
                return default

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            build_llm(FakeSettings(), Path("."))

    def test_build_llm_mock_still_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REELS_ROOT", str(Path(__file__).resolve().parents[1]))
        from reels.config import load_settings, ROOT
        settings = load_settings()
        llm = build_llm(settings, ROOT)
        assert llm.name == "mock"


class TestPipelineWithArtefactEnvelopes:
    def test_pipeline_produces_enveloped_artefacts(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REELS_ROOT", str(Path(__file__).resolve().parents[1]))
        from reels import config
        from reels.orchestrator import Ctx, run_pipeline, make_job_id
        from reels.scripting.llm_client import build_llm
        from reels.contracts.models import Topic

        settings = config.load_settings()
        jid = make_job_id("Envelope test")
        ctx = Ctx(jid, settings, JobFiles(tmp_path, jid), JobStore(tmp_path / "env.db"),
                  build_llm(settings, config.ROOT))
        ctx.files.write_json("topic.json", {"id": "t1", "title": "Envelope test", "source": "manual"})
        ctx.store.create_job(jid, "Envelope test")

        run_pipeline(ctx, until="plan_scenes")

        # script.json should be an envelope
        raw_script = ctx.files.read_json("script.json")
        assert "created_at" in raw_script
        assert "producer" in raw_script
        assert raw_script["producer"] == "scripting.script"

        # scene_plan.json should also be enveloped
        raw_plan = ctx.files.read_json("scene_plan.json")
        assert "created_at" in raw_plan
        assert raw_plan["producer"] == "orchestrator.plan_scenes"

        # Pipeline still functions — plan data is valid
        plan_data = ctx.files.read_artefact_data("scene_plan.json")
        assert "scenes" in plan_data
