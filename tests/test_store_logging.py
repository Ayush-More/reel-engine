import json
import logging

from reels.monitoring.logging import JsonFormatter, redact
from reels.storage.artifacts import JobFiles, hash_obj
from reels.storage.db import FAILED, SUCCEEDED, JobStore


def test_redaction_hides_keys_and_tokens():
    s = redact("key sk-abcdefghijklmnop1234 and access_token=EAAB12345678901234567890xyz")
    assert "sk-abcdef" not in s and "EAAB1234" not in s


def test_json_log_is_valid_json_and_redacted():
    rec = logging.LogRecord("reels.t", logging.INFO, __file__, 1, "token api_key=SECRET123", None, None)
    out = json.loads(JsonFormatter().format(rec))
    assert "SECRET123" not in out["msg"] and out["level"] == "INFO"


def test_atomic_json_roundtrip(tmp_path):
    jf = JobFiles(tmp_path, "job1")
    jf.write_json("a.json", {"x": 1})
    assert jf.read_json("a.json") == {"x": 1} and not list(jf.dir.glob("*.tmp"))


def test_job_status_derives_from_latest_stage_rows(tmp_path):
    st = JobStore(tmp_path / "t.db")
    st.create_job("j", "topic")
    r1 = st.start_stage("j", "generate_script", "h1"); st.finish_stage(r1, FAILED, "boom")
    assert st.stage_summary("j") == {"generate_script": FAILED}
    r2 = st.start_stage("j", "generate_script", "h1"); st.finish_stage(r2, SUCCEEDED)
    assert st.stage_summary("j") == {"generate_script": SUCCEEDED}
    assert st.last_run("j", "generate_script")["attempt"] == 2


def test_hash_is_order_independent():
    assert hash_obj({"a": 1, "b": 2}) == hash_obj({"b": 2, "a": 1})


def test_live_duplicate_guard(tmp_path):
    st = JobStore(tmp_path / "t.db")
    assert st.record_publish("k", "j", "live", "published") is True
    assert st.published_live("k") is True
    assert st.record_publish("k", "j", "live", "published") is False
