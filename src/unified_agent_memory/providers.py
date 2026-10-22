"""LLM provider seam for the optional LLM distiller.

Same pattern as the author's open-managed-agents: an offline default tier
that is always available with no keys, plus key-gated adapters that are
only constructed when the corresponding environment variable is present.
Nothing in the core pipeline requires a provider -- the deterministic
distiller is the default and the offline tier of this seam simply
declines, which the dream phase reports honestly.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol


class ProviderUnavailable(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str: ...


class OfflineProvider:
    """Deterministic offline tier: present, but makes no model calls."""

    name = "offline"

    def complete(self, prompt: str) -> str:
        raise ProviderUnavailable(
            "offline tier does not call models; use DeterministicDistiller"
        )


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini"):
        import openai  # optional dependency, key-gated

        self._client = openai.OpenAI()
        self._model = model

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-5"):
        import anthropic  # optional dependency, key-gated

        self._client = anthropic.Anthropic()
        self._model = model

    def complete(self, prompt: str) -> str:
        resp = self._client.messages.create(
            model=self._model, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")


def default_provider() -> Optional[LLMProvider]:
    """Pick a provider from the environment; None means 'offline only'."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicProvider()
        except Exception:
            return None
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAIProvider()
        except Exception:
            return None
    return None
