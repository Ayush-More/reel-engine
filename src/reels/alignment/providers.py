"""Primary remote word alignment and deterministic offline fallback."""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

import httpx

from ..contracts.models import Alignment, Beat, WordTiming
from ..voice.audio import inspect_audio

TOKEN = re.compile(r"[\w\u0900-\u097F']+(?:[.,!?;:।]+)?", re.UNICODE)


def narration_tokens(text: str) -> list[str]:
    return TOKEN.findall(text)


class WordAligner(ABC):
    name = "base"

    @abstractmethod
    def align(self, audio_path: Path, beats: Sequence[Beat]) -> Alignment:
        """Return monotonic word timings for the exact spoken beat text."""


class ProportionalAligner(WordAligner):
    """Offline fallback suitable for development and fixtures, not production timing."""
    name = "proportional_mock"

    def align(self, audio_path: Path, beats: Sequence[Beat]) -> Alignment:
        duration = inspect_audio(audio_path).duration_s
        words = [token for beat in beats for token in narration_tokens(beat.narration)]
        if not words:
            raise ValueError("cannot align an empty narration")
        step = duration / len(words)
        timings = [
            WordTiming(text=text, start=round(index * step, 4),
                       end=round((index + 1) * step, 4))
            for index, text in enumerate(words)
        ]
        timings[-1] = timings[-1].model_copy(update={"end": duration})
        return Alignment(aligner=self.name, audio_duration_s=duration, words=timings, coverage=1.0)


class WhisperXAligner(WordAligner):
    """Optional local forced aligner; import/model errors are handled by the fallback chain."""
    name = "whisperx"

    def __init__(self, device: str = "cpu", language_code: str = "hi"):
        self.device, self.language_code = device, language_code

    def align(self, audio_path: Path, beats: Sequence[Beat]) -> Alignment:
        try:
            import whisperx
        except ImportError as exc:
            raise RuntimeError("WhisperX is not installed; use the proportional local fallback") from exc
        audio = whisperx.load_audio(str(audio_path))
        duration = inspect_audio(audio_path).duration_s
        text = " ".join(beat.narration for beat in beats)
        model, metadata = whisperx.load_align_model(language_code=self.language_code, device=self.device)
        result = whisperx.align(
            [{"start": 0.0, "end": duration, "text": text}],
            model,
            metadata,
            audio,
            self.device,
            return_char_alignments=False,
        )
        timings = [
            WordTiming(text=str(word["word"]), start=float(word["start"]),
                       end=float(word["end"]), confidence=word.get("score"))
            for segment in result.get("segments", [])
            for word in segment.get("words", [])
            if word.get("start") is not None and word.get("end") is not None
        ]
        expected = sum(len(narration_tokens(beat.narration)) for beat in beats)
        coverage = len(timings) / expected if expected else 0.0
        return Alignment(
            aligner=self.name,
            audio_duration_s=duration,
            words=timings,
            coverage=coverage,
        )


class LocalFallbackAligner(WordAligner):
    name = "local_fallback"

    def __init__(self):
        self.whisperx = WhisperXAligner()
        self.proportional = ProportionalAligner()

    def align(self, audio_path: Path, beats: Sequence[Beat]) -> Alignment:
        try:
            result = self.whisperx.align(audio_path, beats)
            expected = sum(len(narration_tokens(beat.narration)) for beat in beats)
            if expected and result.coverage >= 0.98:
                return result
        except (ImportError, RuntimeError, ValueError):
            pass
        return self.proportional.align(audio_path, beats)


class ElevenLabsAligner(WordAligner):
    name = "elevenlabs_forced_alignment"

    def __init__(self, api_key: str | None = None, timeout_s: float = 120.0,
                 client: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self.timeout_s = timeout_s
        self.client = client or httpx.Client(timeout=timeout_s)

    def align(self, audio_path: Path, beats: Sequence[Beat]) -> Alignment:
        text = " ".join(beat.narration for beat in beats)
        with audio_path.open("rb") as audio_file:
            response = self.client.post(
                "https://api.elevenlabs.io/v1/forced-alignment",
                headers={"xi-api-key": self.api_key},
                data={"text": text},
                files={"file": (audio_path.name, audio_file, "application/octet-stream")},
                timeout=self.timeout_s,
            )
        response.raise_for_status()
        payload = response.json()
        raw_words = payload.get("words", [])
        timings = [
            WordTiming(
                text=str(word.get("text", word.get("word", ""))),
                start=float(word["start"]),
                end=float(word["end"]),
                confidence=word.get("confidence"),
            )
            for word in raw_words
            if word.get("type", "word") == "word"
        ]
        expected = sum(len(narration_tokens(beat.narration)) for beat in beats)
        coverage = len(timings) / expected if expected else 0.0
        duration = inspect_audio(audio_path).duration_s
        return Alignment(aligner=self.name, audio_duration_s=duration, words=timings, coverage=coverage)


def build_aligner(settings: Any) -> WordAligner:
    provider = settings.get("alignment.provider", "mock")
    if provider == "mock":
        return ProportionalAligner()
    if provider == "elevenlabs":
        return ElevenLabsAligner(timeout_s=float(settings.get("alignment.timeout_s", 120)))
    if provider == "whisperx":
        return WhisperXAligner(
            device=settings.get("alignment.device", "cpu"),
            language_code=settings.get("alignment.language_code", "hi"),
        )
    raise ValueError(f"unknown alignment.provider: {provider}")


def align_with_fallback(primary: WordAligner, fallback: WordAligner, audio_path: Path,
                        beats: Sequence[Beat], min_coverage: float = 0.98) -> Alignment:
    try:
        result = primary.align(audio_path, beats)
        expected = sum(len(narration_tokens(beat.narration)) for beat in beats)
        if result.coverage < min_coverage or len(result.words) < expected * min_coverage:
            raise ValueError(
                f"{primary.name} alignment coverage {result.coverage:.1%} is below {min_coverage:.0%}"
            )
        return result
    except (httpx.HTTPError, ValueError, KeyError, RuntimeError) as primary_error:
        if primary is fallback:
            raise
        result = fallback.align(audio_path, beats)
        if result.coverage < min_coverage:
            raise ValueError(f"fallback alignment coverage {result.coverage:.1%} is too low") from primary_error
        return result
