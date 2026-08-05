"""Generic OpenAI-compatible adapter (Section 12.1).

This one adapter serves OpenAI, Azure OpenAI (via a deployment base_url),
Ollama, vLLM, LM Studio, Groq, DeepSeek, and OpenRouter - they all speak the
same ``/v1/chat/completions`` and ``/v1/embeddings`` schema. A provider that
deviates gets its own adapter rather than an ``if`` branch in here.

Note: the LLM Gateway (routing, retry, fallback chain, cost tracking) is
Phase 4. This adapter only supplies the transport contract it will sit on.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import ChatCompletion, ChatMessage
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import AIProvider
from aidss.plugins.registry import register


@register
class OpenAICompatibleProvider(AIProvider):
    name: ClassVar[str] = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        chat_model: str,
        embedding_model: str,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embedding_model = embedding_model
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAICompatibleProvider:
        return cls(
            base_url=settings.ai_base_url,
            # Local servers (Ollama, vLLM, LM Studio) usually need no API key.
            api_key=settings.ai_api_key,
            chat_model=settings.ai_chat_model,
            embedding_model=settings.ai_embedding_model,
            # Passed through, which it was not: the constructor took a timeout
            # and this ignored it, so every deployment ran on the 60-second
            # default no matter what it configured. A self-hosted gateway on
            # modest hardware needs minutes for an analyzer prompt, and the
            # symptom was three analyzers failing at once with "the read
            # operation timed out" - which reads like the gateway is broken
            # rather than like we hung up on it.
            timeout=settings.ai_timeout_seconds,
        )

    # --- internals ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self._client.post(path, json=payload, headers=self._headers())
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        if response.status_code == 429:
            raise ProviderUnavailableError(self.name, "rate limit exceeded", retryable=True)
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {response.status_code}", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                self.name, f"client error {response.status_code}: {response.text[:200]}",
                retryable=False,
            )
        return response.json()

    # --- AIProvider contract --------------------------------------------

    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> ChatCompletion:
        payload: dict = {
            "model": model or self._chat_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            # Section 12.6: streaming stays off for structured output so the
            # Output Validator can inspect a complete response.
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        data = self._post("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError(
                self.name, f"response does not match the OpenAI-compatible schema: {data!r}",
                retryable=False,
            ) from exc

        usage = data.get("usage") or {}
        return ChatCompletion(
            content=content,
            model=data.get("model", payload["model"]),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        data = self._post(
            "/embeddings", {"model": model or self._embedding_model, "input": texts}
        )
        try:
            # Sort by index: the schema permits results in any order.
            items = sorted(data["data"], key=lambda d: d.get("index", 0))
            return [[float(x) for x in item["embedding"]] for item in items]
        except (KeyError, TypeError) as exc:
            raise ProviderUnavailableError(
                self.name, f"embedding response does not match the schema: {data!r}",
                retryable=False,
            ) from exc

    def supports_tool_calling(self) -> bool:
        return True

    def supports_structured_output(self) -> bool:
        # Support is uneven across OpenAI-compatible servers, so Core must still
        # run the Output Validator as a second layer (Section 12.5).
        return False
