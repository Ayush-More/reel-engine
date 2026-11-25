"""Structured JSON logging with job/stage context and secret redaction."""
from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")
stage_var: contextvars.ContextVar[str] = contextvars.ContextVar("stage", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(EAA[A-Za-z0-9]{20,})"),  # Meta access tokens commonly start with EAA
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|authorization)\s*[=:]\s*)([^\s,;\"']+)"),
]


def redact(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[2].sub(lambda m: m.group(1) + "[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "job_id": job_id_var.get(),
            "stage": stage_var.get(),
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload.update({k: json.loads(redact(json.dumps(v, default=str))) for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)
    fmt = JsonFormatter()
    handler = logging.FileHandler(logs_dir / "reels.jsonl", encoding="utf-8")
    handler.setFormatter(fmt)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"reels.{name}")
