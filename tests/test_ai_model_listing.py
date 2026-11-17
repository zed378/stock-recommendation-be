"""Listing the models an endpoint offers, so the provider form can show a dropdown.

The adapters are tested against canned responses in each vendor's real shape. The endpoint is tested
for the part that is easy to get wrong and costly when wrong: which key is sent to which URL.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from aidss.api.routes import admin as admin_routes
from aidss.config import get_settings
from aidss.db.base import get_sessionmaker
from aidss.db.models import AIProviderConfig
from aidss.plugins.adapters import ai_gemini, ai_openai_compatible
from aidss.plugins.adapters.ai_anthropic import API_VERSION, AnthropicProvider
from aidss.plugins.adapters.ai_gemini import GeminiProvider
from aidss.plugins.adapters.ai_openai_compatible import OpenAICompatibleProvider
from aidss.plugins.errors import ProviderUnavailableError


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")


# --- the three adapters -------------------------------------------------------


def test_openai_compatible_lists_chat_models_and_drops_the_obvious_non_chat_ones() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o"},
                    {"id": "gpt-4o-mini"},
                    {"id": "text-embedding-3-small"},
                    {"id": "whisper-1"},
                    {"id": "dall-e-3"},
                    {"id": "gpt-4o"},
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        "https://example.test", "sk-k", chat_model="m", embedding_model="e",
        client=transport(handler),
    )

    assert provider.list_models() == ["gpt-4o", "gpt-4o-mini"]
    assert seen[0].method == "GET" and seen[0].url.path == "/models"
    assert seen[0].headers["authorization"] == "Bearer sk-k"


def test_a_server_that_returns_a_bare_list_still_works() -> None:
    provider = OpenAICompatibleProvider(
        "https://example.test", None, chat_model="m", embedding_model="e",
        client=transport(lambda r: httpx.Response(200, json=[{"id": "llama3"}, {"id": "qwen2"}])),
    )
    assert provider.list_models() == ["llama3", "qwen2"]


def test_anthropic_lists_models_with_its_own_headers_and_keeps_the_api_order() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"data": [{"id": "claude-sonnet-4-5"}, {"id": "claude-haiku-4-5"}]}
        )

    provider = AnthropicProvider("sk-ant", chat_model="m", client=transport(handler))

    assert provider.list_models() == ["claude-sonnet-4-5", "claude-haiku-4-5"]
    assert seen[0].headers["x-api-key"] == "sk-ant"
    assert seen[0].headers["anthropic-version"] == API_VERSION
    assert seen[0].url.params["limit"] == "1000"


def test_gemini_keeps_only_models_that_can_answer_and_follows_pages() -> None:
    chat, embed = ["generateContent"], ["embedContent"]
    pages = {
        None: {
            "models": [
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": chat},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": embed},
            ],
            "nextPageToken": "p2",
        },
        "p2": {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": chat}]},
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("pageToken")])

    provider = GeminiProvider("g-key", chat_model="m", client=transport(handler))

    assert provider.list_models() == ["gemini-2.5-pro", "gemini-2.5-flash"]
    # The key travels in a header, never in the URL (which ends up in access logs).
    assert all(r.headers["x-goog-api-key"] == "g-key" for r in seen)
    assert all("g-key" not in str(r.url) for r in seen)


def test_a_rejected_key_is_an_error_not_an_empty_list() -> None:
    provider = OpenAICompatibleProvider(
        "https://example.test", "bad", chat_model="m", embedding_model="e",
        client=transport(lambda r: httpx.Response(401, text="invalid api key")),
    )
    with pytest.raises(ProviderUnavailableError, match="401"):
        provider.list_models()


# --- the endpoint ---------------------------------------------------------------


@pytest.fixture
def upstream(monkeypatch):
    """Route every adapter-built HTTP client to a recording handler, whatever URL it was given."""
    real = httpx.Client
    calls: list[httpx.Request] = []
    state = {"status": 200, "body": {"data": [{"id": "model-a"}, {"id": "model-b"}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(state["status"], json=state["body"])

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), base_url=kwargs.get("base_url", ""))

    monkeypatch.setattr(ai_openai_compatible.httpx, "Client", factory)
    monkeypatch.setattr(ai_gemini.httpx, "Client", factory)
    return calls, state


def test_a_typed_key_is_sent_to_the_typed_url_and_the_models_come_back(
    client, admin_headers, upstream
) -> None:
    calls, _ = upstream
    response = client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"base_url": "https://api.example.com/v1", "api_key": "sk-typed-in-the-form"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "models": ["model-a", "model-b"], "error": None}
    assert calls[0].url.host == "api.example.com"
    assert calls[0].headers["authorization"] == "Bearer sk-typed-in-the-form"
    assert "sk-typed-in-the-form" not in response.text


def test_the_environments_own_key_is_never_lent_to_a_probe(
    client, admin_headers, upstream, monkeypatch
) -> None:
    """The URL may have just been typed. With no key typed, nothing is sent, not the key the
    deployment was configured with."""
    calls, _ = upstream
    env = get_settings().model_copy(update={"ai_api_key": "sk-from-the-environment"})
    monkeypatch.setattr(admin_routes, "get_settings", lambda: env)

    client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"base_url": "https://somewhere.example/v1"},
    )

    assert "authorization" not in calls[0].headers


def test_a_stored_key_is_used_for_the_url_it_was_saved_with(
    client, admin_headers, upstream
) -> None:
    calls, _ = upstream
    created = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "saved", "base_url": "https://api.example.com/v1", "api_key": "sk-stored-1"},
    ).json()

    response = client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"provider_id": created["id"], "base_url": "https://api.example.com/v1/"},
    )

    assert response.json()["ok"] is True
    assert calls[0].headers["authorization"] == "Bearer sk-stored-1"


def test_a_stored_key_is_not_sent_to_a_different_url(client, admin_headers, upstream) -> None:
    calls, _ = upstream
    created = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "saved2", "base_url": "https://api.example.com/v1", "api_key": "sk-stored-2"},
    ).json()

    response = client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"provider_id": created["id"], "base_url": "https://evil.example/v1"},
    )

    body = response.json()
    assert body["ok"] is False and "Enter the key again" in body["error"]
    assert calls == []  # nothing left the building


def test_a_provider_is_not_created_or_changed_by_listing(client, admin_headers, upstream) -> None:
    client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"base_url": "https://api.example.com/v1", "api_key": "sk-x"},
    )
    db = get_sessionmaker()()
    try:
        assert db.scalars(select(AIProviderConfig)).all() == []
    finally:
        db.close()


def test_a_wrong_key_comes_back_as_a_reason_not_a_server_error(
    client, admin_headers, upstream
) -> None:
    _, state = upstream
    state["status"], state["body"] = 401, {"error": "invalid"}

    response = client.post(
        "/admin/ai-providers/models",
        headers=admin_headers,
        json={"base_url": "https://api.example.com/v1", "api_key": "sk-wrong"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and "401" in body["error"] and body["models"] == []


def test_an_unknown_adapter_is_refused(client, admin_headers) -> None:
    response = client.post(
        "/admin/ai-providers/models", headers=admin_headers, json={"adapter_name": "nope"}
    )
    assert response.status_code == 422


def test_only_an_admin_may_ask(client, auth_headers) -> None:
    response = client.post("/admin/ai-providers/models", headers=auth_headers, json={})
    assert response.status_code in (401, 403)
