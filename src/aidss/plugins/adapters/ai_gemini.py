"""Google's Gemini API, presented as the platform's own contract.

Gemini differs from the OpenAI schema in more places than Anthropic does:

  * The model is in the **path**, not the body:
    ``/models/{model}:generateContent``. So a request cannot be built without
    knowing the model first, and the usual "model is just another field"
    assumption does not hold.
  * Turns are ``contents[]`` with ``parts[]``, and the assistant role is called
    ``model``.
  * The system prompt is ``systemInstruction``, a separate top-level object.
  * Generation settings live under ``generationConfig`` rather than at the top.
  * Usage is ``usageMetadata.promptTokenCount`` / ``candidatesTokenCount``.
  * It **does** have embeddings, on a different route again -
    ``:embedContent``, one call per text.

Two behaviours here are worth stating because they are not obvious from the
schema:

**A blocked response is not an empty one.** Gemini returns 200 with no
candidate, or a candidate whose ``finishReason`` is ``SAFETY``, when its
filters fire. Read naively that becomes an empty string, which travels
downstream as an analyst who had nothing to say - so both cases are raised as
provider failures naming the reason.

**JSON mode is real here.** ``responseMimeType: application/json`` is honoured,
so structured output is schema-enforced rather than prompt-enforced. The Output
Validator still runs; this is the one adapter where it is a second layer rather
than the only one.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import ChatCompletion, ChatMessage
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import AIProvider
from aidss.plugins.registry import register

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Finish reasons that mean the model was stopped rather than finished. Raised
#: rather than returned, because each produces a short or empty answer that is
#: indistinguishable from a genuine one downstream.
BLOCKED_REASONS = frozenset({"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"})


@register
class GeminiProvider(AIProvider):
    name: ClassVar[str] = "gemini"

    def __init__(
        self,
        api_key: str | None,
        *,
        chat_model: str,
        embedding_model: str = "text-embedding-004",
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embedding_model = embedding_model
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> GeminiProvider:
        return cls(
            api_key=settings.ai_api_key,
            chat_model=settings.ai_chat_model,
            embedding_model=settings.ai_embedding_model,
            base_url=settings.ai_base_url or DEFAULT_BASE_URL,
            timeout=settings.ai_timeout_seconds,
        )

    # --- internals ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            # The header form rather than `?key=`, which would put the
            # credential in every access log along the path.
            headers["x-goog-api-key"] = self._api_key
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self._client.post(path, json=payload, headers=self._headers())
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        if response.status_code == 429:
            raise ProviderUnavailableError(
                self.name, "rate limit or quota exceeded", retryable=True
            )
        if response.status_code >= 500:
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
    def _to_contents(messages: list[ChatMessage]) -> tuple[dict | None, list[dict]]:
        """Split into a system instruction and Gemini's own turn shape.

        Several system messages are joined for the same reason as the Anthropic
        adapter: silently dropping one is how a language rule stops being
        enforced without anything failing.
        """
        system_parts = [m.content for m in messages if m.role == "system"]
        contents = [
            {
                # Gemini calls the assistant "model". Sent as "assistant" the
                # request is rejected, and the message says only that the role
                # is invalid.
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role in ("user", "assistant")
        ]
        instruction = (
            {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
        )
        return instruction, contents

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
        chosen = model or self._chat_model
        instruction, contents = self._to_contents(messages)
        if not contents:
            raise ProviderUnavailableError(
                self.name,
                "generateContent needs at least one user turn; only a system "
                "instruction was supplied",
                retryable=False,
            )

        config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        # Honoured natively, unlike the other two adapters - so a caller asking
        # for JSON gets it enforced by the API rather than only by the prompt.
        if response_format and response_format.get("type") in (
            "json_object",
            "json_schema",
        ):
            config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if instruction:
            payload["systemInstruction"] = instruction

        data = self._post(f"/models/{chosen}:generateContent", payload)

        # A prompt refused before generation: 200, no candidates, and a reason
        # in promptFeedback.
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise ProviderUnavailableError(
                self.name,
                f"the prompt was blocked ({feedback['blockReason']})",
                retryable=False,
            )

        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderUnavailableError(
                self.name,
                f"no candidate was returned: {data!r}",
                retryable=False,
            )

        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason in BLOCKED_REASONS:
            # Distinguished from an empty answer on purpose. Returned as "" it
            # reads downstream as an analyst who had nothing to say.
            raise ProviderUnavailableError(
                self.name,
                f"the response was stopped by the model's filters ({reason})",
                retryable=False,
            )

        parts = (candidate.get("content") or {}).get("parts") or []
        content = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        )

        # MAX_TOKENS is reported after the fact and truncates mid-structure,
        # which for a JSON response means unparseable output. Raised rather
        # than passed on, so the retry is spent on the cause.
        if reason == "MAX_TOKENS" and not content.strip():
            raise ProviderUnavailableError(
                self.name,
                "the response hit the output-token limit before producing anything",
                retryable=False,
            )

        usage = data.get("usageMetadata") or {}
        return ChatCompletion(
            content=content,
            model=chosen,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            raw=data,
        )

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """One call per text.

        Gemini has a batch route, but it is a different path with a different
        body, and the platform embeds a handful of chunks at a time rather than
        thousands. A second request shape to keep working is a worse trade than
        a few extra round trips.
        """
        if not texts:
            return []

        chosen = model or self._embedding_model
        vectors: list[list[float]] = []
        for text in texts:
            data = self._post(
                f"/models/{chosen}:embedContent",
                {"model": f"models/{chosen}", "content": {"parts": [{"text": text}]}},
            )
            try:
                vectors.append([float(x) for x in data["embedding"]["values"]])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderUnavailableError(
                    self.name,
                    f"embedding response does not match the schema: {data!r}",
                    retryable=False,
                ) from exc
        return vectors

    def supports_tool_calling(self) -> bool:
        return True

    def supports_structured_output(self) -> bool:
        # The one adapter here where this is true: `responseMimeType` is
        # honoured by the API, so the Output Validator is a second layer rather
        # than the only one.
        return True
