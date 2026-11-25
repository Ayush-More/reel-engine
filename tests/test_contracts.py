import copy

import pytest
from pydantic import ValidationError

from reels.contracts.models import ReelProject, Script


def test_example_project_is_schema_valid(project_json):
    proj = ReelProject.model_validate(project_json)
    assert proj.script.beats[0].role.value == "HOOK"
    assert proj.alignment_excerpt is not None and proj.alignment_excerpt.coverage == 1.0


def test_unknown_field_is_rejected(project_json):
    bad = copy.deepcopy(project_json["script"])
    bad["surprise"] = 1
    with pytest.raises(ValidationError):
        Script.model_validate(bad)


def test_template_props_are_validated(project_json):
    bad = copy.deepcopy(project_json["script"])
    bad["beats"][3]["props"].pop("tokens")  # token_split requires tokens
    with pytest.raises(ValidationError):
        Script.model_validate(bad)


def test_flow_edges_must_reference_nodes(project_json):
    bad = copy.deepcopy(project_json["script"])
    bad["beats"][4]["props"]["edges"][0]["dst"] = "nope"
    with pytest.raises(ValidationError):
        Script.model_validate(bad)


def test_beat_end_must_follow_start(project_json):
    bad = copy.deepcopy(project_json["script"])
    bad["beats"][1]["end"] = bad["beats"][1]["start"]
    with pytest.raises(ValidationError):
        Script.model_validate(bad)


def test_hashtags_need_hash_sign(project_json):
    bad = copy.deepcopy(project_json["script"])
    bad["meta"]["hashtags"] = ["AI", "#LLM", "#GPT"]
    with pytest.raises(ValidationError):
        Script.model_validate(bad)
