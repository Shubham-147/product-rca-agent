"""Shared, injectable LLM clients for Systems A, B, and C."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from src.config import get_settings


class LLMClient(ABC):
    """Minimal text-completion interface shared by every RCA system."""

    @abstractmethod
    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Return a text completion for ``prompt``."""


class OpenAIClient(LLMClient):
    """OpenAI SDK client configured exclusively through ``get_settings()``."""

    def __init__(self) -> None:
        # Validate configuration before constructing the SDK client. This preserves the
        # clear Step 0 missing-key error and keeps credentials out of this module.
        settings = get_settings()
        from openai import OpenAI

        self.model = settings.openai_model
        self._client = OpenAI(api_key=settings.openai_api_key)

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Call the configured model through the OpenAI Responses API."""
        response = self._client.responses.create(
            model=self.model,
            input=prompt,
            **kwargs,
        )
        text = response.output_text
        if not text:
            raise RuntimeError("OpenAI returned a response without text output.")
        return text


class FakeLLMClient(LLMClient):
    """TEST-ONLY deterministic client for offline pipeline wiring.

    Exact prompts may be mapped to canned responses. All other prompts receive the
    configured default, and every prompt is recorded for assertions.
    """

    def __init__(
        self,
        responses: Mapping[str, str] | None = None,
        default_response: str = "FAKE_LLM_RESPONSE",
    ) -> None:
        self._responses = dict(responses or {})
        self.default_response = default_response
        self.prompts: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Return a canned response without network access or API usage."""
        del kwargs
        self.prompts.append(prompt)
        return self._responses.get(prompt, self.default_response)

