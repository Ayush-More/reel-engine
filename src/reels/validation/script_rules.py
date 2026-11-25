"""Deterministic script rules. Pure functions over attribute-style objects (no pydantic import),
so they are easy to unit test. Runs BEFORE any paid voice/render call."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

ROLE_ORDER = ["HOOK", "PROBLEM", "ANALOGY", "MECHANISM", "TAKEAWAY", "CTA"]
REQUIRED_ROLES = ["PROBLEM", "ANALOGY", "MECHANISM", "TAKEAWAY", "CTA"]
DEFAULT_WPS = 2.4  # Phase 1 baseline for duration estimation
DURATION_TOLERANCE = 0.15  # ±15% Phase 1 tolerance
DEFAULTS = {
    "min_duration_s": 55, "max_duration_s": 80, "max_words_per_second": 3.6, "max_hook_words": 14,
    "max_headline_words": 12, "max_beat_seconds": 12,
    "banned_openers": ["aaj hum", "today we", "is video mein", "hello dosto", "namaste dosto"],
}


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str
    beat_id: str | None = None

    def __str__(self) -> str:
        where = f" [{self.beat_id}]" if self.beat_id else ""
        return f"{self.severity.upper()} {self.code}{where}: {self.message}"


def _role(b: Any) -> str:
    r = b.role
    return getattr(r, "value", r)


def _template(b: Any) -> str:
    t = b.template
    return getattr(t, "value", t)


def word_count(text: str) -> int:
    return len(re.findall(r"[\w\u0900-\u097F']+", text))


def validate_script_rules(script: Any, rules: dict[str, Any] | None = None) -> list[Issue]:
    cfg = {**DEFAULTS, **(rules or {})}
    issues: list[Issue] = []
    beats = list(script.beats)

    def err(code: str, msg: str, bid: str | None = None) -> None:
        issues.append(Issue(code, "error", msg, bid))

    def warn(code: str, msg: str, bid: str | None = None) -> None:
        issues.append(Issue(code, "warning", msg, bid))

    # timing
    if abs(beats[0].start) > 0.05:
        err("timeline_start", f"first beat starts at {beats[0].start}, expected 0")
    for prev, cur in zip(beats, beats[1:]):
        if abs(cur.start - prev.end) > 0.05:
            err("timeline_gap", f"{prev.id} ends {prev.end} but {cur.id} starts {cur.start}", cur.id)
    total = beats[-1].end
    if not cfg["min_duration_s"] <= total <= cfg["max_duration_s"]:
        err("duration", f"total {total:.1f}s outside {cfg['min_duration_s']}-{cfg['max_duration_s']}s")
    if abs(script.estimated_duration_s - total) > 1.0:
        warn("duration_estimate", f"estimated_duration_s {script.estimated_duration_s} differs from beats {total:.1f}")

    # structure: roles must be non-decreasing in ROLE_ORDER, and all required roles present
    roles = [_role(b) for b in beats]
    idx = [ROLE_ORDER.index(r) for r in roles]
    if idx != sorted(idx):
        err("role_order", f"roles out of order: {roles}")
    for needed in REQUIRED_ROLES:
        if needed not in roles:
            err("role_missing", f"missing {needed} beat")
    if roles[0] not in ("HOOK", "PROBLEM"):
        err("first_beat", "first beat must be HOOK or PROBLEM")

    # hook
    hook = beats[0].narration
    if word_count(hook) > cfg["max_hook_words"]:
        err("hook_length", f"hook has {word_count(hook)} words (max {cfg['max_hook_words']})", beats[0].id)
    low = hook.lower().strip()
    for banned in cfg["banned_openers"]:
        if low.startswith(banned):
            err("hook_generic", f"hook starts with banned opener '{banned}'", beats[0].id)
    if script.chosen_hook.strip() != hook.strip() and script.chosen_hook.strip() not in hook:
        warn("hook_mismatch", "chosen_hook does not match first beat narration", beats[0].id)

    # per-beat duration estimation check (Phase 1: ±15% tolerance against ~2.4 w/s estimate)
    for b in beats:
        actual_dur = b.end - b.start
        estimated_dur = estimate_duration(b.narration)
        if estimated_dur > 0 and abs(actual_dur - estimated_dur) / estimated_dur > DURATION_TOLERANCE:
            err("duration_estimate_beat",
                f"beat duration {actual_dur:.1f}s vs estimated {estimated_dur:.1f}s "
                f"(>{DURATION_TOLERANCE*100:.0f}% off at {DEFAULT_WPS} w/s)", b.id)

    # per-beat
    claim_ids = {c.id for c in script.claims}
    prev_tpl = None
    for b in beats:
        dur = b.end - b.start
        wps = word_count(b.narration) / dur
        if wps > cfg["max_words_per_second"]:
            err("too_fast", f"{wps:.2f} words/s exceeds {cfg['max_words_per_second']}", b.id)
        if wps < 1.2:
            warn("too_slow", f"{wps:.2f} words/s may feel static", b.id)
        if dur > cfg["max_beat_seconds"]:
            err("beat_too_long", f"{dur:.1f}s beat; split it so visuals change every few seconds", b.id)
        if word_count(b.headline) > cfg["max_headline_words"]:
            err("headline_long", f"headline has {word_count(b.headline)} words", b.id)
        if _template(b) == prev_tpl:
            warn("template_repeat", f"same template '{prev_tpl}' twice in a row", b.id)
        prev_tpl = _template(b)
        for cid in b.claim_ids:
            if cid not in claim_ids:
                err("unknown_claim", f"references missing claim {cid}", b.id)
        if _role(b) == "MECHANISM" and not b.claim_ids:
            err("mechanism_unsourced", "MECHANISM beat must reference at least one claim", b.id)

    # claims
    for c in script.claims:
        if not c.is_analogy and not c.source_urls:
            err("claim_unsourced", f"factual claim {c.id} has no source URL")
        for source_url in c.source_urls:
            parsed = urlparse(source_url.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                err("claim_source_invalid", f"claim {c.id} has invalid source URL {source_url!r}")
        if not c.is_analogy and not c.verified:
            warn("claim_unverified", f"claim {c.id} not yet verified by the research stage")
    used = {cid for b in beats for cid in b.claim_ids}
    for c in script.claims:
        if c.id not in used:
            if c.is_analogy:
                warn("claim_unused", f"claim {c.id} is never referenced by a beat")
            else:
                err("claim_uncovered", f"factual claim {c.id} is not referenced by any beat")
    return issues


def estimate_duration(narration: str, wps: float = DEFAULT_WPS) -> float:
    """Estimate beat duration from word count at the given words-per-second rate."""
    words = word_count(narration)
    return words / wps if wps > 0 else 0.0


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
