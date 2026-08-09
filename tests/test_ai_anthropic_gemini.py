"""Anthropic and Gemini, behind the same contract as everything else.

Neither is OpenAI-compatible, and the differences are the kind that fail at
runtime rather than at import: a system message sent as a turn is rejected, an
assistant role Gemini does not recognise is rejected, and a missing
`max_tokens` is a 400 from Anthropic only. Each of those gets a test, because
each is invisible until a real request is made.
"""

from __future__ import annotations

import httpx
import pytest

from aidss.domain.types import ChatMessage
from aidss.plugins.adapters.ai_anthropic import API_VERSION, AnthropicProvider
from aidss.plugins.adapters.ai_gemini import GeminiProvider
from aidss.plugins.errors import ProviderUnavailableError


def transport(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    )


def anthropic(handler, **kwargs) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="k", chat_model="claude-sonnet-4-5", client=transport(handler), **kwargs
    )


def gemini(handler, **kwargs) -> GeminiProvider:
    return GeminiProvider(
        api_key="k", chat_model="gemini-2.5-pro", client=transport(handler), **kwargs
    )


ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "A measured reading."}],
    "model": "claude-sonnet-4-5",
    "usage": {"input_tokens": 120, "output_tokens": 45},
}

GEMINI_OK = {
    "candidates": [
        {
            "content": {"parts": [{"text": "A measured reading."}], "role": "model"},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 45},
}


# --- Anthropic ---------------------------------------------------------------


def test_the_system_prompt_is_lifted_out_of_the_messages() -> None:
    """It is a top-level field, not a turn. Sent as `role: "system"` the API
    rejects the request outright."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ANTHROPIC_OK)

    anthropic(handler).chat_completion(
        [ChatMessage(role="system", content="Be careful."), ChatMessage(role="user", content="Hi")]
    )

    assert seen["system"] == "Be careful."
    assert [m["role"] for m in seen["messages"]] == ["user"]


def test_several_system_messages_are_joined_not_dropped() -> None:
    """Losing one silently is how a language rule or an anti-execution rule
    stops being enforced without anything failing."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ANTHROPIC_OK)

    anthropic(handler).chat_completion(
        [
            ChatMessage(role="system", content="Answer in English."),
            ChatMessage(role="system", content="Never instruct a trade."),
            ChatMessage(role="user", content="Hi"),
        ]
    )

    assert "Answer in English." in seen["system"]
    assert "Never instruct a trade." in seen["system"]


def test_max_tokens_is_always_sent() -> None:
    """Optional for OpenAI, required by Anthropic. Absent, the request is a
    400 that says nothing about which field is missing."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ANTHROPIC_OK)

    anthropic(handler).chat_completion([ChatMessage(role="user", content="Hi")])

    assert seen["max_tokens"] > 0


def test_the_version_header_is_pinned() -> None:
    """A header that tracks "latest" turns a working deployment into a broken
    one on somebody else's release day."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json=ANTHROPIC_OK)

    anthropic(handler).chat_completion([ChatMessage(role="user", content="Hi")])

    assert seen["anthropic-version"] == API_VERSION
    assert seen["x-api-key"] == "k"
    assert "authorization" not in seen


def test_only_text_blocks_become_the_answer() -> None:
    """Content is a list of typed blocks. A tool-use block rendered into the
    prose puts a JSON fragment inside an analyst's paragraph."""
    payload = {
        **ANTHROPIC_OK,
        "content": [
            {"type": "text", "text": "Reading. "},
            {"type": "tool_use", "id": "x", "name": "lookup", "input": {}},
            {"type": "text", "text": "Continued."},
        ],
    }
    result = anthropic(lambda r: httpx.Response(200, json=payload)).chat_completion(
        [ChatMessage(role="user", content="Hi")]
    )

    assert result.content == "Reading. Continued."


def test_anthropic_usage_field_names_are_translated() -> None:
    """`input_tokens`/`output_tokens` rather than `prompt`/`completion`. Read
    with the OpenAI names every call would cost zero, and the budget screen
    would report a system that never spends anything."""
    result = anthropic(lambda r: httpx.Response(200, json=ANTHROPIC_OK)).chat_completion(
        [ChatMessage(role="user", content="Hi")]
    )

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 45


def test_a_system_only_request_is_refused_before_it_is_sent() -> None:
    with pytest.raises(ProviderUnavailableError, match="at least one user turn"):
        anthropic(lambda r: httpx.Response(200, json=ANTHROPIC_OK)).chat_completion(
            [ChatMessage(role="system", content="Only this.")]
        )


def test_overloaded_is_retryable() -> None:
    """529 is Anthropic's own "overloaded". Under a plain >= 400 branch it
    reads as a client error and the fallback chain gives up on it."""
    with pytest.raises(ProviderUnavailableError) as caught:
        anthropic(lambda r: httpx.Response(529, text="overloaded")).chat_completion(
            [ChatMessage(role="user", content="Hi")]
        )

    assert caught.value.retryable is True


def test_anthropic_embedding_says_why_it_cannot() -> None:
    """Anthropic publishes no embedding endpoint. Returning an empty list would
    travel downstream as "no relevant documents"."""
    with pytest.raises(ProviderUnavailableError, match="no embedding endpoint"):
        anthropic(lambda r: httpx.Response(200, json={})).embed(["text"])


# --- Gemini ------------------------------------------------------------------


def test_the_model_goes_in_the_path() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=GEMINI_OK)

    gemini(handler).chat_completion([ChatMessage(role="user", content="Hi")])

    assert "/models/gemini-2.5-pro:generateContent" in seen["url"]


def test_the_assistant_role_is_renamed_to_model() -> None:
    """Sent as "assistant" the request is rejected, and the message says only
    that the role is invalid."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GEMINI_OK)

    gemini(handler).chat_completion(
        [
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hello"),
            ChatMessage(role="user", content="More"),
        ]
    )

    assert [c["role"] for c in seen["contents"]] == ["user", "model", "user"]


def test_the_system_prompt_becomes_a_system_instruction() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GEMINI_OK)

    gemini(handler).chat_completion(
        [ChatMessage(role="system", content="Be careful."), ChatMessage(role="user", content="Hi")]
    )

    assert seen["systemInstruction"]["parts"][0]["text"] == "Be careful."
    assert all(c["role"] != "system" for c in seen["contents"])


def test_json_mode_is_requested_natively() -> None:
    """The one adapter where structured output is enforced by the API rather
    than only by the prompt."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GEMINI_OK)

    gemini(handler).chat_completion(
        [ChatMessage(role="user", content="Hi")],
        response_format={"type": "json_object"},
    )

    assert seen["generationConfig"]["responseMimeType"] == "application/json"


def test_a_blocked_prompt_is_a_failure_not_an_empty_answer() -> None:
    """Gemini answers 200 with no candidate when its filters fire. Read
    naively that becomes an empty string, which travels downstream as an
    analyst who had nothing to say."""
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}

    with pytest.raises(ProviderUnavailableError, match="blocked"):
        gemini(lambda r: httpx.Response(200, json=payload)).chat_completion(
            [ChatMessage(role="user", content="Hi")]
        )


def test_a_filtered_response_is_a_failure_too() -> None:
    payload = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}

    with pytest.raises(ProviderUnavailableError, match="filters"):
        gemini(lambda r: httpx.Response(200, json=payload)).chat_completion(
            [ChatMessage(role="user", content="Hi")]
        )


def test_gemini_usage_field_names_are_translated() -> None:
    result = gemini(lambda r: httpx.Response(200, json=GEMINI_OK)).chat_completion(
        [ChatMessage(role="user", content="Hi")]
    )

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 45


def test_the_key_travels_in_a_header_not_the_query_string() -> None:
    """`?key=` puts the credential in every access log along the path."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=GEMINI_OK)

    gemini(handler).chat_completion([ChatMessage(role="user", content="Hi")])

    assert "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "k"


def test_gemini_embeds_each_text() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"embedding": {"values": [0.1, 0.2]}})

    vectors = gemini(handler).embed(["one", "two"])

    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert len(calls) == 2
    assert all(":embedContent" in url for url in calls)


def test_no_texts_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    assert gemini(handler).embed([]) == []


# --- both, through the configuration path ------------------------------------


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
def test_a_row_is_built_with_its_own_credentials(adapter: str, session) -> None:
    """The bug this avoids: built through `from_settings`, every row would
    share the one key and endpoint in the environment - which is not
    multi-provider, and leaves the fallback chain nowhere to fall to."""
    from aidss.config import get_settings
    from aidss.db.models import AIProviderConfig
    from aidss.llm.provisioning import provider_from_row
    from aidss.security.secrets import encrypt_secret

    settings = get_settings()
    row = AIProviderConfig(
        name=adapter,
        adapter_name=adapter,
        default_model="a-model",
        api_key_ciphertext=encrypt_secret("row-specific-key", settings),
    )

    built = provider_from_row(row, settings)

    assert built.name == adapter
    assert built._api_key == "row-specific-key"
    assert built._chat_model == "a-model"


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
def test_a_first_party_row_keeps_its_own_endpoint(adapter: str, session) -> None:
    """Falling back to `settings.ai_base_url` would aim an Anthropic row at
    whatever OpenAI-compatible gateway the environment names, and the failure
    would look like Anthropic rejecting a valid key."""
    from aidss.config import get_settings
    from aidss.db.models import AIProviderConfig
    from aidss.llm.provisioning import provider_from_row

    settings = get_settings()
    built = provider_from_row(
        AIProviderConfig(name=adapter, adapter_name=adapter, default_model="m"), settings
    )

    assert settings.ai_base_url not in built._base_url


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
def test_an_explicit_base_url_still_wins(adapter: str, session) -> None:
    """Somebody routing through a proxy has to be able to say so."""
    from aidss.config import get_settings
    from aidss.db.models import AIProviderConfig
    from aidss.llm.provisioning import provider_from_row

    built = provider_from_row(
        AIProviderConfig(
            name=adapter,
            adapter_name=adapter,
            default_model="m",
            base_url="https://proxy.internal/v1",
        ),
        get_settings(),
    )

    assert built._base_url == "https://proxy.internal/v1"
