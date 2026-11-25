import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_json():
    return json.loads((ROOT / "examples" / "tokens_reel.json").read_text(encoding="utf-8"))


@pytest.fixture()
def script(project_json):
    from reels.contracts.models import Script
    return Script.model_validate(project_json["script"])
