import copy

from reels.contracts.models import Script
from reels.validation.script_rules import has_errors, validate_script_rules


def codes(issues, severity="error"):
    return {i.code for i in issues if i.severity == severity}


def test_example_passes_rules(script):
    issues = validate_script_rules(script)
    assert not has_errors(issues), [str(i) for i in issues]


def test_gap_between_beats_is_an_error(project_json):
    d = copy.deepcopy(project_json["script"])
    d["beats"][2]["start"] += 1.0
    assert "timeline_gap" in codes(validate_script_rules(Script.model_validate(d)))


def test_generic_hook_is_rejected(project_json):
    d = copy.deepcopy(project_json["script"])
    d["beats"][0]["narration"] = "Aaj hum seekhenge ki AI tokens kya hote hain"
    assert "hook_generic" in codes(validate_script_rules(Script.model_validate(d)))


def test_unsourced_factual_claim_is_an_error(project_json):
    d = copy.deepcopy(project_json["script"])
    d["claims"][1]["source_urls"] = []
    assert "claim_unsourced" in codes(validate_script_rules(Script.model_validate(d)))


def test_too_short_reel_fails_duration(project_json):
    d = copy.deepcopy(project_json["script"])
    d["beats"] = d["beats"][:6]
    d["beats"][-1]["role"] = "CTA"
    assert "duration" in codes(validate_script_rules(Script.model_validate(d)))
