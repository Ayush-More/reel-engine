"""Conservative layout preflight for the 1080x1920 renderer safe area."""
from __future__ import annotations

import textwrap
from typing import Any

from ..contracts.models import LayoutBox, LayoutReport, Script

WIDTH, HEIGHT = 1080, 1920
SIDE_MARGIN = 64
BOTTOM_RESERVED = 480
STAGE_RIGHT_BUFFER = 120
CAPTION_Y = 1310


def _estimated_text_width(text: str, font_size: float) -> float:
    return sum(font_size * (0.28 if char.isspace() else 0.7 if ord(char) > 0x2FFF else 0.58)
               for char in text)


def safe_area_violations(boxes: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    safe_bottom = HEIGHT - BOTTOM_RESERVED
    safe_right = WIDTH - SIDE_MARGIN
    stage_right = safe_right - STAGE_RIGHT_BUFFER
    for box in boxes:
        name = box["name"]
        x, y = float(box["x"]), float(box["y"])
        width, height = float(box["width"]), float(box["height"])
        if x < SIDE_MARGIN or y < 0 or x + width > safe_right or y + height > safe_bottom:
            problems.append(f"{name} outside safe area")
        if box["zone"] == "stage" and x + width > stage_right:
            problems.append(f"{name} violates {STAGE_RIGHT_BUFFER}px stage right buffer")
    stage_boxes = [box for box in boxes if box["zone"] == "stage"]
    caption_boxes = [box for box in boxes if box["zone"] == "caption"]
    for stage in stage_boxes:
        for caption in caption_boxes:
            if (stage["x"] < caption["x"] + caption["width"]
                    and stage["x"] + stage["width"] > caption["x"]
                    and stage["y"] < caption["y"] + caption["height"]
                    and stage["y"] + stage["height"] > caption["y"]):
                problems.append(f"{stage['name']} overlaps {caption['name']}")
    return problems


def build_layout_report(script: Script, captions: dict[str, Any] | None = None) -> LayoutReport:
    boxes: list[LayoutBox] = [
        LayoutBox(name="brand", x=64, y=72, width=832, height=64, zone="chrome"),
    ]
    violations: list[str] = []
    for beat in script.beats:
        lines = textwrap.wrap(beat.headline, width=24, break_long_words=True, break_on_hyphens=False) or [""]
        if len(lines) > 2:
            violations.append(f"headline-{beat.id} exceeds two lines")
        headline_width = max((_estimated_text_width(line, 58) for line in lines), default=1)
        if headline_width > 832:
            violations.append(f"headline-{beat.id} exceeds headline width")
        boxes.append(LayoutBox(
            name=f"headline-{beat.id}", x=64, y=420, width=max(1, headline_width),
            height=210, zone="headline",
        ))
    for beat in script.beats:
        boxes.append(LayoutBox(name=f"stage-{beat.id}", x=64, y=680, width=832, height=610, zone="stage"))
    segments = (captions or {}).get("segments", [])
    for index, segment in enumerate(segments):
        text = " ".join(word["text"] for word in segment.get("words", []))
        width = max(1, _estimated_text_width(text, 62))
        if width > 900:
            violations.append(f"caption-{index} exceeds 900px caption width")
        boxes.append(LayoutBox(
            name=f"caption-{index}",
            x=540 - width / 2,
            y=CAPTION_Y,
            width=width,
            height=100,
            zone="caption",
        ))
    if not segments:
        boxes.append(LayoutBox(name="caption", x=90, y=CAPTION_Y, width=900, height=100, zone="caption"))
    violations.extend(safe_area_violations([box.model_dump() for box in boxes]))
    return LayoutReport(safe_area_passed=not violations, boxes=boxes, violations=violations)
