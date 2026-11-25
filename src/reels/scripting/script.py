"""Script generation with a bounded repair loop. Invalid output never leaves this module as 'valid'."""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from ..contracts.models import Script, Topic
from ..monitoring.logging import get_logger
from ..validation.script_rules import Issue, has_errors, validate_script_rules
from .llm_client import LLMClient

log = get_logger("script")


class ScriptGenerationError(RuntimeError):
    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.errors = errors


def _extract_json(text: str) -> str:
    """Tolerate ```json fences or leading prose, but nothing cleverer: the schema is the real gate."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def generate_script(llm: LLMClient, topic: Topic, prompts_dir: Path, rules: dict,
                    max_repairs: int = 2) -> tuple[Script, list[Issue]]:
    system = (prompts_dir / "script.md").read_text(encoding="utf-8")
    repair_tpl = (prompts_dir / "repair.md").read_text(encoding="utf-8")
    schema_hint = json.dumps(Script.model_json_schema())
    user = f"Topic: {topic.title}\n\nJSON schema:\n{schema_hint}"
    errors: list[str] = []

    for attempt in range(max_repairs + 1):
        raw = llm.complete_json(system, user)
        try:
            script = Script.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError) as exc:
            errors = [str(exc)]
            log.warning("schema validation failed", extra={"data": {"attempt": attempt, "errors": errors[:1]}})
        else:
            issues = validate_script_rules(script, rules)
            if not has_errors(issues):
                return script, issues
            errors = [str(i) for i in issues if i.severity == "error"]
            log.warning("script rules failed", extra={"data": {"attempt": attempt, "errors": errors}})
        user = repair_tpl.format(errors="\n".join(errors)) + f"\n\nPrevious JSON:\n{raw}"

    raise ScriptGenerationError(f"script invalid after {max_repairs} repair attempts", errors)
