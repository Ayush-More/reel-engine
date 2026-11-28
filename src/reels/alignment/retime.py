"""Map beats onto real audio: the audio is the clock. Beats are re-timed from word timestamps."""
from __future__ import annotations

import re
from typing import Any, Sequence


def _n_words(text: str) -> int:
    return len(re.findall(r"[\w\u0900-\u097F']+", text))


def retime_beats(beats: Sequence[Any], words: Sequence[Any], audio_duration: float,
                 tail_pad: float = 0.1) -> list[tuple[str, float, float]]:
    """Return [(beat_id, start, end)] using each beat's word count to find its slice of aligned words.

    Raises ValueError when the narration word count and aligned word count disagree by more than 2%,
    because a silent mismatch here would desynchronise every later beat.
    """
    expected = sum(_n_words(b.narration) for b in beats)
    if expected == 0 or abs(expected - len(words)) / expected > 0.02:
        raise ValueError(f"alignment has {len(words)} words but script has {expected}; refusing to retime")
    out: list[tuple[str, float, float]] = []
    chunks: list[Sequence[Any]] = []
    cursor = 0
    for b in beats:
        n = _n_words(b.narration)
        chunk = words[cursor:cursor + n]
        cursor += n
        if not chunk:
            raise ValueError(f"no aligned words left for beat {b.id}")
        chunks.append(chunk)
    for i, (beat, chunk) in enumerate(zip(beats, chunks)):
        start = 0.0 if i == 0 else out[-1][2]
        if i < len(beats) - 1:
            gap_start = float(chunk[-1].end)
            gap_end = float(chunks[i + 1][0].start)
            end = (gap_start + gap_end) / 2
        else:
            end = audio_duration + tail_pad
        if end <= start:
            raise ValueError(f"non-positive duration for beat {beat.id}")
        out.append((beat.id, round(start, 3), round(end, 3)))
    return out
