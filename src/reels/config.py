"""Configuration: YAML defaults + environment overrides. Secrets come only from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("REELS_ROOT", Path(__file__).resolve().parents[2]))
SECRET_ENV_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "IG_ACCESS_TOKEN")


@dataclass
class Settings:
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def jobs_dir(self) -> Path:
        return ROOT / self.get("paths.jobs_dir", "jobs")

    @property
    def db_path(self) -> Path:
        return ROOT / self.get("paths.db_path", "data/reels.db")

    @property
    def logs_dir(self) -> Path:
        return ROOT / self.get("paths.logs_dir", "logs")

    @property
    def script_rules(self) -> dict[str, Any]:
        return dict(self.raw.get("script", {}))

    def secret(self, key: str) -> str | None:
        return os.environ.get(key) or None

    def redacted(self) -> dict[str, Any]:
        """Safe-to-log view: shows which secrets are set, never their values."""
        return {**self.raw, "secrets_present": {k: bool(os.environ.get(k)) for k in SECRET_ENV_KEYS}}


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if os.environ.get("REELS_LLM_PROVIDER"):
        raw.setdefault("llm", {})["provider"] = os.environ["REELS_LLM_PROVIDER"]
    if os.environ.get("REELS_PUBLISH_ENABLED", "false").lower() != "true":
        raw.setdefault("publishing", {})["mode"] = "dry_run"  # live publishing must be opted into explicitly
    return Settings(raw=raw)
