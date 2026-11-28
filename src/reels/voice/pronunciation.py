"""Pronunciation substitutions applied before speech generation and alignment."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    replacements = data.get("replacements", data) if isinstance(data, dict) else {}
    if not isinstance(replacements, dict):
        raise ValueError(f"pronunciation overrides in {path} must be a mapping")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in replacements.items()):
        raise ValueError(f"pronunciation overrides in {path} must contain string pairs")
    return replacements


def apply_overrides(text: str, overrides: dict[str, str]) -> str:
    for source, spoken in sorted(overrides.items(), key=lambda pair: len(pair[0]), reverse=True):
        if not source:
            raise ValueError("pronunciation override terms cannot be empty")
        text = re.sub(re.escape(source), lambda _: spoken, text, flags=re.IGNORECASE)
    return text
