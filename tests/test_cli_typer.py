"""Tests for the Typer CLI commands."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from reels.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def mock_root(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))


def test_schema_command_exports_files():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "wrote JSON Schemas" in result.output
    assert (ROOT / "schemas" / "script.schema.json").exists()
    assert (ROOT / "schemas" / "render_props.schema.json").exists()


def test_validate_example_passes():
    result = runner.invoke(app, ["validate", str(ROOT / "examples" / "tokens_reel.json")])
    assert "PASS" in result.output
    assert result.exit_code == 0


def test_validate_bad_file_fails(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"topic_title":"t","target_audience":"a","hook_variants":["h"],"chosen_hook":"h",'
                   '"meta":{"title":"t","category":"c","thumbnail_headline":"t",'
                   '"instagram_caption":"c","hashtags":["#a","#b","#c"]},'
                   '"beats":[],"claims":[],"estimated_duration_s":10}', encoding="utf-8")
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1


def test_new_command_creates_job(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))
    result = runner.invoke(app, ["new", "--topic", "Test topic"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert "job_id" in out
    assert out["stages"]["plan_scenes"] == "succeeded"


def test_plan_scenes_command(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))
    # First create a job
    result1 = runner.invoke(app, ["new", "--topic", "Plan test topic"])
    assert result1.exit_code == 0
    job_id = json.loads(result1.output)["job_id"]
    # Then plan-scenes
    result2 = runner.invoke(app, ["plan-scenes", job_id])
    assert result2.exit_code == 0


def test_script_command(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))
    result = runner.invoke(app, ["script", "Script test topic"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert "generate_script" in out["stages"]


def test_dry_run_command(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))
    result1 = runner.invoke(app, ["new", "--topic", "Dry run test topic"])
    assert result1.exit_code == 0
    job_id = json.loads(result1.output)["job_id"]
    result2 = runner.invoke(app, ["dry-run", job_id])
    assert result2.exit_code == 0
    out = json.loads(result2.output)
    assert out["status"] == "blocked"  # no QC, no approval


def test_live_publish_blocked_in_phase1(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(ROOT))
    result1 = runner.invoke(app, ["new", "--topic", "Publish test"])
    job_id = json.loads(result1.output)["job_id"]
    result2 = runner.invoke(app, ["publish", job_id])
    assert result2.exit_code == 2
