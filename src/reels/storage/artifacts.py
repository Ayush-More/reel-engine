"""Artefact files per job, plus content hashing for resumable stages."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contracts.models import SCHEMA_VERSION


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))


class JobFiles:
    def __init__(self, jobs_dir: Path, job_id: str):
        self.dir = jobs_dir / job_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.dir / name

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def write_json(self, name: str, data: Any) -> Path:
        """Atomic write: a crash never leaves a half-written artefact that looks valid."""
        target = self.path(name)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return target

    def write_artefact(self, name: str, data: Any, producer: str, input_hash: str) -> Path:
        """Write an artefact with metadata envelope: created_at, producer, content_hash, data."""
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "job_id": self.dir.name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "producer": producer,
            "content_hash": hash_obj(data),
            "input_hash": input_hash,
            "data": data,
        }
        return self.write_json(name, envelope)

    def read_artefact_data(self, name: str) -> Any:
        """Read an artefact and return only its 'data' payload (or the raw dict if no envelope)."""
        raw = self.read_json(name)
        if isinstance(raw, dict) and "data" in raw and "content_hash" in raw:
            return raw["data"]
        return raw

    def read_json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text(encoding="utf-8"))
