"""Voice provider interface, deterministic offline provider, and ElevenLabs TTS adapter."""
from __future__ import annotations

import hashlib
import math
import os
import random
import shutil
import time
import wave
from abc import ABC, abstractmethod
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .audio import AudioMetrics, inspect_audio


@dataclass(frozen=True)
class VoiceResult:
    path: Path
    text_hash: str
    provider: str
    model: str
    duration_s: float
    longest_silence_s: float
    mean_db: float
    cache_hit: bool


class VoiceProvider(ABC):
    name = "base"

    @abstractmethod
    def synthesize(self, text: str, output_path: Path, cache_dir: Path, *,
                   target_duration_s: float, voice_id: str | None = None) -> VoiceResult:
        """Create audio at output_path, reusing cached bytes when the exact input matches."""


def _text_hash(text: str, provider: str, model: str, voice_id: str | None,
               output_format: str = "") -> str:
    payload = "\0".join((text, provider, model, voice_id or "", output_format))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_result(cache_file: Path, output_path: Path, provider: str, model: str,
                  text_hash: str, cache_hit: bool) -> VoiceResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cache_file, output_path)
    metrics: AudioMetrics = inspect_audio(output_path)
    return VoiceResult(output_path, text_hash, provider, model, metrics.duration_s,
                       metrics.longest_silence_s, metrics.mean_db, cache_hit)


class MockVoiceProvider(VoiceProvider):
    """Offline deterministic tone track; it is a test fixture, not intelligible speech."""
    name = "mock"

    def __init__(self, sample_rate: int = 8000):
        self.sample_rate = sample_rate
        self.calls = 0

    def synthesize(self, text: str, output_path: Path, cache_dir: Path, *,
                   target_duration_s: float, voice_id: str | None = None) -> VoiceResult:
        text_hash = _text_hash(text, self.name, "tone-fixture-v1", voice_id, "wav-pcm16")
        cache_file = cache_dir / f"{text_hash}.wav"
        if cache_file.exists():
            return _cache_result(cache_file, output_path, self.name, "tone-fixture-v1", text_hash, True)
        self.calls += 1
        cache_dir.mkdir(parents=True, exist_ok=True)
        tokens = text.split()
        if not tokens:
            raise ValueError("cannot synthesize an empty script")
        total_samples = max(len(tokens), round(target_duration_s * self.sample_rate))
        samples_per_token = total_samples // len(tokens)
        output = array("h")
        for index, token in enumerate(tokens):
            token_seed = hashlib.sha256(token.encode("utf-8")).digest()
            frequency = 180 + token_seed[0] * 2
            count = samples_per_token if index < len(tokens) - 1 else total_samples - len(output)
            for frame in range(count):
                fade = min(1.0, frame / 80, (count - frame) / 80)
                phase = 2 * math.pi * frequency * frame / self.sample_rate
                output.append(round(5000 * max(0.0, fade) * math.sin(phase)))
        with wave.open(str(cache_file), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(output.tobytes())
        return _cache_result(cache_file, output_path, self.name, "tone-fixture-v1", text_hash, False)


class ElevenLabsVoiceProvider(VoiceProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, model: str = "eleven_multilingual_v2",
                 output_format: str = "mp3_44100_128", timeout_s: float = 120.0,
                 retries: int = 4, client: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self.model, self.output_format = model, output_format
        self.timeout_s, self.retries = timeout_s, retries
        self.client = client or httpx.Client(timeout=timeout_s)

    def synthesize(self, text: str, output_path: Path, cache_dir: Path, *,
                   target_duration_s: float, voice_id: str | None = None) -> VoiceResult:
        voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
        if not voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID is not set")
        text_hash = _text_hash(text, self.name, self.model, voice_id, self.output_format)
        cache_file = cache_dir / f"{text_hash}.{self.output_format.split('_')[0]}"
        if cache_file.exists():
            return _cache_result(cache_file, output_path, self.name, self.model, text_hash, True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    params={"output_format": self.output_format},
                    headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                    json={"text": text, "model_id": self.model,
                          "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}},
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                cache_file.write_bytes(response.content)
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code != 429 and exc.response.status_code < 500:
                    raise RuntimeError(f"ElevenLabs TTS failed ({exc.response.status_code}): {exc.response.text}") from exc
                if attempt + 1 == self.retries:
                    raise RuntimeError(f"ElevenLabs TTS exhausted {self.retries} retries") from exc
                time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.25))
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt + 1 == self.retries:
                    raise RuntimeError(f"ElevenLabs TTS request failed after {self.retries} attempts") from exc
                time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.25))
        if last_error and not cache_file.exists():
            raise RuntimeError("ElevenLabs TTS failed without producing cached audio") from last_error
        return _cache_result(cache_file, output_path, self.name, self.model, text_hash, False)


def build_voice_provider(settings: Any) -> VoiceProvider:
    provider = os.environ.get("REELS_VOICE_PROVIDER", settings.get("voice.provider", "mock"))
    if provider == "mock":
        return MockVoiceProvider()
    if provider == "elevenlabs":
        return ElevenLabsVoiceProvider(
            model=settings.get("voice.model", "eleven_multilingual_v2"),
            output_format=settings.get("voice.output_format", "mp3_44100_128"),
            retries=int(settings.get("voice.retries", 4)),
            timeout_s=float(settings.get("voice.timeout_s", 120)),
        )
    raise ValueError(f"unknown voice.provider: {provider}")
