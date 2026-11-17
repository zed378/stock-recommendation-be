"""Anthropic's Messages API, presented as the platform's own contract.

Anthropic is not OpenAI-compatible, and the differences are not cosmetic:

  * The route is ``/v1/messages``, authenticated with ``x-api-key`` and a
    required ``anthropic-version`` header rather than a bearer token.
  * The system prompt is a **top-level field**, not a message with
    ``role: "system"``. Sent as a message it is rejected outright, so the
    conversion below lifts it out - and joins several, because the platform
    composes one system message today and may compose two tomorrow.
  * Content comes back as a list of typed blocks rather than a string.
  * ``max_tokens`` is **required**. OpenAI treats it as optional and defaults
    it; Anthropic returns 400 without it, so this adapter carries a default of
    its own rather than passing the absence through.
  * Usage is ``input_tokens``/``output_tokens``.

**There is no embedding endpoint.** Anthropic does not publish one, and the
honest thing is to say so at the point of use rather than return an empty list
that reads downstream as "no relevant documents". Retrieval is configured with
its own provider anyway (Section 16.3), which is exactly the case this is for.

Structured output is prompt-enforced, not schema-enforced: the Messages API has
tool-use, but pressing it into service as a JSON mode is a larger change than
this needs, and the Output Validator is the second layer regardless.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import ChatCompletion, ChatMessage
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import AIProvider
from aidss.plugins.registry import register

#: Pinned rather than tracking "latest". A version header that moves on its own
#: turns a working deployment into a broken one on somebody else's release day.
API_VERSION = "2023-06-01"

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

#: Required by the API, so the adapter needs a number when the caller has no
#: opinion. Generous enough for an analyzer's JSON, which is the longest thing
#: this platform asks for.
DEFAULT_MAX_TOKENS = 4096


@register
class AnthropicProvider(AIProvider):
    name: ClassVar[str] = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        *,
        chat_model: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicProvider:
        return cls(
            api_key=settings.ai_api_key,
            chat_model=settings.ai_chat_model,
            base_url=settings.ai_base_url or DEFAULT_BASE_URL,
            timeout=settings.ai_timeout_seconds,
        )

    # --- internals ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": API_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        return self._send("POST", path, json=payload)

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._send("GET", path, params=params)

    def _send(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        if response.status_code == 429:
            raise ProviderUnavailableError(self.name, "rate limit exceeded", retryable=True)
        # 529 is Anthropic's "overloaded", which is transient and would read as
        # an ordinary client error under a plain >= 400 branch.
        if response.status_code in (529,) or response.status_code >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {response.status_code}", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                self.name,
                f"client error {response.status_code}: {response.text[:200]}",
                retryable=False,
            )
        return response.json()

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
        """Lift system messages out, because the API takes them separately.

        Several are joined rather than the last one winning: dropping an
        instruction silently is how a language rule or an anti-execution rule
        stops being enforced without anything failing.

        Consecutive same-role turns are left as they are. The API rejects them
        in some versions, but the platform never produces them - and merging
        here would hide it if that ever changed.
        """
        system_parts = [m.content for m in messages if m.role == "system"]
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        return ("\n\n".join(system_parts) or None), turns

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
        system, turns = self._split_system(messages)
        if not turns:
            # A request of system prompt only is rejected by the API, and the
            # error it returns says nothing useful about why.
            raise ProviderUnavailableError(
                self.name,
                "the Messages API needs at least one user turn; only a system "
                "prompt was supplied",
                retryable=False,
            )

        payload: dict = {
            "model": model or self._chat_model,
            "messages": turns,
            "temperature": temperature,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if system:
            payload["system"] = system
        # `response_format` is deliberately not forwarded. The Messages API has
        # no such field, and passing an unknown key is a 400 - so a caller
        # asking for JSON gets prompt-enforced JSON plus the Output Validator,
        # which is what `supports_structured_output()` reports below.

        data = self._post("/messages", payload)
        try:
            # Content is a list of typed blocks. Only text blocks are joined:
            # a tool-use block rendered into the prose would put a JSON
            # fragment inside an analyst's paragraph.
            blocks = data["content"]
            content = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise ProviderUnavailableError(
                self.name,
                f"response does not match the Messages schema: {data!r}",
                retryable=False,
            ) from exc

        usage = data.get("usage") or {}
        return ChatCompletion(
            content=content,
            model=data.get("model", payload["model"]),
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            raw=data,
        )

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        raise ProviderUnavailableError(
            self.name,
            "Anthropic publishes no embedding endpoint. Configure a separate "
            "provider for retrieval - the embedding model is configured apart "
            "from the chat model precisely so this can differ.",
            retryable=False,
        )

    def list_models(self) -> list[str]:
        # Newest first, which is the order worth keeping for a dropdown.
        data = self._get("/models", params={"limit": 1000})
        return [str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]

    def supports_tool_calling(self) -> bool:
        return True

    def supports_structured_output(self) -> bool:
        # Prompt-enforced here rather than schema-enforced, so the Output
        # Validator remains the layer that guarantees the shape.
        return False
