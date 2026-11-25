"""Provider-independent LLM interface. Swap providers without touching the pipeline."""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path


class LLMClient(ABC):
    name = "base"

    @abstractmethod
    def complete_json(self, system: str, user: str) -> str:
        """Return the raw model text; the caller validates it. Must not log prompts containing secrets."""


class MockLLM(LLMClient):
    """Offline provider: returns the bundled example script so the CLI works with no API keys."""
    name = "mock"

    def __init__(self, example_path: Path):
        self.example_path = example_path
        self.calls = 0

    def complete_json(self, system: str, user: str) -> str:
        self.calls += 1
        data = json.loads(self.example_path.read_text(encoding="utf-8"))
        return json.dumps(data["script"], ensure_ascii=False)


class AnthropicLLM(LLMClient):
    """Real provider (pip install reels-engine[llm]). Not exercised by the unit tests."""
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 6000):
        import anthropic  # lazy import: optional dependency

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.model, self.max_tokens = model, max_tokens

    def complete_json(self, system: str, user: str) -> str:
        msg = self._client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


class OpenAILLM(LLMClient):
    """OpenAI fallback provider (pip install reels-engine[llm])."""
    name = "openai"

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None, max_tokens: int = 6000):
        import openai  # lazy import: optional dependency

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = openai.OpenAI(api_key=key)
        self.model, self.max_tokens = model, max_tokens

    def complete_json(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


def build_llm(settings, root: Path) -> LLMClient:
    provider = settings.get("llm.provider", "mock")
    if provider == "mock":
        return MockLLM(root / "examples" / "tokens_reel.json")
    if provider == "anthropic":
        return AnthropicLLM(settings.get("llm.model"))
    if provider == "openai":
        return OpenAILLM(settings.get("llm.model", "gpt-4o"))
    raise ValueError(f"unknown llm.provider: {provider}")
