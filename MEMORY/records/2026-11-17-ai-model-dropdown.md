# Provider form: model dropdown fetched from the endpoint (2026-11-17)

The owner asked that entering an API key fetch the available models automatically, so the model is chosen from a dropdown. This is the AI provider screen of the analysis platform (Admin, AI providers), not the Trader's exchange credential.

## What changed

- Adapters: `AIProvider.list_models()` (optional; the default raises "cannot list its models"). `openai_compatible` reads `GET /models` (the OpenAI shape or a bare list; drops ids that are plainly not chat models: embedding, whisper, tts-, dall-e, moderation).
  `anthropic` reads `GET /models` with its own headers and keeps the API's newest-first order. `gemini` reads `GET /models` page by page (up to 5 pages), keeps only models that support `generateContent`, strips the `models/` prefix, and sends the key in a header, not the URL.
  Each adapter's `_post` now goes through a shared `_send`, with a `_get` beside it.
- Endpoint: `POST /admin/ai-providers/models` (permission `MANAGE_PROVIDERS`), body `{adapter_name, base_url?, api_key?, provider_id?}`, answer `{ok, models, error}`. Nothing is saved. A wrong key is `ok: false` with a reason, not a server error.
- Two limits on purpose: the deployment's own `AIDSS_AI_API_KEY` is never lent to the probe (`provider_from_row(..., inherit_environment_key=False)`), because the URL may have just been typed; and a stored key is used only against the URL it was saved with, otherwise the
  answer is "Enter the key again" and no request is made.
- Form (`frontend/src/components/admin/AIProviders.tsx`): the model field becomes a dropdown once models are known. It fetches by itself 700 ms after a key is typed (or on opening an edit that has a stored key), and has a "Fetch models" button for keyless local servers (Ollama, LM Studio).
  Choosing "Type a model name…" or any failure goes back to the plain text box, with the reason shown. A saved model that is not in the list stays selectable, marked as current. Only the newest request may write its answer.
- Tests: `tests/test_ai_model_listing.py` (13: each adapter's shape and headers, which key goes to which URL, nothing saved, errors, permission) and `frontend/src/components/admin/__tests__/AIProviders.test.tsx` (5). `frontend/src/api/schema.d.ts` regenerated from the app (90 added lines, no other change).

## Not verified

- No real vendor was called: the adapters are tested against canned responses in each vendor's documented shape. The first real use may show a field this did not expect (a gateway that nests the list differently, an id filter that hides a chat model).
- The endpoint forwards the typed key to whatever URL the admin types, as the existing connection test already does for a saved row; it is admin-only (`MANAGE_PROVIDERS`) and returns only model ids and an error line.
- Not deployed: this needs a new `aidss-api` image and a new `aidss-frontend` image. The deployed images do not have it.
