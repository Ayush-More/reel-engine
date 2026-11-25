"""Caption grouping from word timings. Works on any objects with .text/.start/.end."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

SENTENCE_END = (".", "?", "!", "\u0964")
CLAUSE_END = (",", ";", ":")


@dataclass
class CaptionWord:
    text: str
    start: float
    end: float


@dataclass
class CaptionSegment:
    start: float
    end: float
    words: list[CaptionWord] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def group_captions(words: Sequence[Any], max_words: int = 4, max_chars: int = 26,
                   max_seconds: float = 2.4, pause_break: float = 0.35) -> list[CaptionSegment]:
    """Break on sentence end, long pauses, word/char/time limits; prefer breaking after commas."""
    segments: list[CaptionSegment] = []
    cur: list[CaptionWord] = []

    def flush() -> None:
        if cur:
            segments.append(CaptionSegment(cur[0].start, cur[-1].end, list(cur)))
            cur.clear()

    prev_end: float | None = None
    for w in words:
        cw = CaptionWord(w.text, float(w.start), float(w.end))
        if cur and prev_end is not None and cw.start - prev_end >= pause_break:
            flush()
        projected_chars = len(" ".join([x.text for x in cur] + [cw.text]))
        if cur and (len(cur) >= max_words or projected_chars > max_chars or cw.end - cur[0].start > max_seconds):
            flush()
        cur.append(cw)
        prev_end = cw.end
        if cw.text.endswith(SENTENCE_END) or (cw.text.endswith(CLAUSE_END) and len(cur) >= 2):
            flush()
    flush()
    return segments


def validate_caption_sync(segments: Sequence[CaptionSegment], words: Sequence[Any],
                          median_limit: float = 0.04, max_limit: float = 0.12) -> dict[str, Any]:
    """Caption word starts must equal the alignment's word starts (they are derived, so this guards regressions)."""
    flat = [w for s in segments for w in s.words]
    if len(flat) != len(words):
        return {"passed": False, "reason": f"{len(flat)} caption words vs {len(words)} aligned words"}
    errs = sorted(abs(c.start - float(a.start)) for c, a in zip(flat, words))
    median = errs[len(errs) // 2] if errs else 0.0
    mx = errs[-1] if errs else 0.0
    return {"passed": median <= median_limit and mx <= max_limit, "median_s": median, "max_s": mx}
