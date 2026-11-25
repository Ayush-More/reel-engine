"""SQLite job store: job status is derived from stage rows, never from log lines."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  job_id TEXT PRIMARY KEY, topic TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stage_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, stage TEXT NOT NULL,
  status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1, input_hash TEXT,
  started_at TEXT NOT NULL, finished_at TEXT, error TEXT, cost_usd REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS approvals(
  job_id TEXT PRIMARY KEY, approved INTEGER NOT NULL, by TEXT, at TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS publishes(
  idempotency_key TEXT PRIMARY KEY, job_id TEXT NOT NULL, mode TEXT NOT NULL,
  status TEXT NOT NULL, at TEXT NOT NULL);
"""
SUCCEEDED, FAILED, BLOCKED, RUNNING = "succeeded", "failed", "blocked", "running"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_job(self, job_id: str, topic: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO jobs VALUES (?,?,?)", (job_id, topic, now()))

    def start_stage(self, job_id: str, stage: str, input_hash: str) -> int:
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) FROM stage_runs WHERE job_id=? AND stage=?", (job_id, stage)).fetchone()[0]
            cur = c.execute(
                "INSERT INTO stage_runs(job_id,stage,status,attempt,input_hash,started_at) VALUES (?,?,?,?,?,?)",
                (job_id, stage, RUNNING, n + 1, input_hash, now()),
            )
            return int(cur.lastrowid)

    def finish_stage(self, run_id: int, status: str, error: str | None = None, cost_usd: float = 0.0) -> None:
        with self._conn() as c:
            c.execute("UPDATE stage_runs SET status=?, finished_at=?, error=?, cost_usd=? WHERE id=?",
                      (status, now(), error, cost_usd, run_id))

    def last_run(self, job_id: str, stage: str) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM stage_runs WHERE job_id=? AND stage=? ORDER BY id DESC LIMIT 1",
                             (job_id, stage)).fetchone()

    def stage_summary(self, job_id: str) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT stage,status FROM stage_runs WHERE id IN "
                "(SELECT MAX(id) FROM stage_runs WHERE job_id=? GROUP BY stage) ORDER BY id", (job_id,)).fetchall()
        return {r["stage"]: r["status"] for r in rows}

    def total_cost(self, job_id: str) -> float:
        with self._conn() as c:
            return float(c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM stage_runs WHERE job_id=?", (job_id,)).fetchone()[0])

    def set_approval(self, job_id: str, approved: bool, by: str, note: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO approvals VALUES (?,?,?,?,?)", (job_id, int(approved), by, now(), note))

    def is_approved(self, job_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT approved FROM approvals WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row["approved"])

    def record_publish(self, key: str, job_id: str, mode: str, status: str) -> bool:
        """Returns False if this idempotency key was already used by a real (non-blocked) publish."""
        with self._conn() as c:
            row = c.execute("SELECT status FROM publishes WHERE idempotency_key=?", (key,)).fetchone()
            if row and row["status"] in ("published", "would_publish") and mode == "live":
                return False
            c.execute("INSERT OR REPLACE INTO publishes VALUES (?,?,?,?,?)", (key, job_id, mode, status, now()))
            return True

    def published_live(self, key: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT 1 FROM publishes WHERE idempotency_key=? AND mode='live' AND status='published'",
                            (key,)).fetchone()
        return row is not None

    def total_cost_today(self) -> float:
        """Sum of cost_usd across all jobs for today (UTC)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM stage_runs WHERE started_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return float(row[0])
