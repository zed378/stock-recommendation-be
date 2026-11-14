# 04 — Indodax Authentication and Signing (Trade API 2.0)

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer, Security Engineer |
| **Decided by** | ADR-002 |
| **Open items** | OQ-18 (decided, ADR-038) |

Source: `INDODAX-TradeAPI-2-Private.md`. **Documented, not yet observed.** The two-key scheme of the legacy
API is a different thing and is not described here.

## Request Headers

| Header | Required | Value |
|---|---|---|
| `Accept` | Yes | `application/json` |
| `X-APIKEY` | Yes (signed endpoints) | The TAPIv2 API key |
| `Sign` | Yes (signed endpoints) | HMAC-SHA256 hex signature (see below) |
| `Content-Type` | For `POST` | `application/x-www-form-urlencoded` |

The docs also allow the signature as a `signature` body field or query parameter. The Trader always uses the
`Sign` header, so there is one way to do it.

## What Is Signed

The docs say the signed value is **the query string concatenated with the request body**, with the secret
key as the HMAC key, and that the signature is hex and **not case sensitive**.

To remove ambiguity the Trader sends **every parameter in exactly one place** and signs exactly the string
it sends:

| Method | Parameters sent in | Signed string |
|---|---|---|
| `GET`, `DELETE` | Query string | The query string, as transmitted |
| `POST` | Form body | The form body, as transmitted |

URL-encoding is applied once, and the signed bytes are the transmitted bytes. A signature that "looks
right" but fails is most often an encoding or ordering mismatch between what was signed and what was sent.

## Time Parameters

Each signed request needs `timestamp` (milliseconds) **or** `nonce`. If both are present, `timestamp` is
used. The Trader uses `timestamp` plus `recvWindow`.

| Parameter | Meaning |
|---|---|
| `timestamp` | Millisecond time the request was created |
| `recvWindow` | Milliseconds the request stays valid after `timestamp`. Default 5000 |

The server rejects a request if `timestamp >= serverTime + 1000` **or** `serverTime - timestamp >
recvWindow`. A rejection returns `-1021` (HTTP 400). The Trader checks local time against
`GET /api/server_time` and halts when skew approaches `recvWindow` (FR-T18). It does not widen
`recvWindow` to hide a bad clock.

## Illustrative Signing (placeholders only)

```python
# secret and api_key are placeholders; real values come from the credential store, never from source.
params = {"symbol": "BTCIDR", "side": "BUY", "type": "LIMIT", "price": "...", "quantity": "...",
          "timestamp": now_ms, "recvWindow": 5000}
body = urlencode(params)
sign = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
headers = {"Accept": "application/json", "X-APIKEY": api_key, "Sign": sign,
           "Content-Type": "application/x-www-form-urlencoded"}
```

## Error Responses Related to Auth

| Code | HTTP | Meaning |
|---|---|---|
| `-1002` | 401 | Invalid credentials; API not found or session expired |
| `-1022` | 400 | Invalid nonce or signature; signature missing |
| `-1021` | 400 | Timestamp outside `recvWindow` |
| `-2014` | 400 | API key not found in header |
| `-2015` | 403 | Access denied: Trade API disabled, account locked, no permission, unauthorized IP, or invalid TAPI version key |

`-2015` is the signal for a key whose permission or version is wrong; the Trader stays `DISABLED` and
alerts (`08`).

## Rules

- Never log the key, the secret, the signature, or a full signed request.
- Never cache a signature; each request has its own.
- The secret lives decrypted only while one signature is computed.
- Tests use fixtures and a mock server that verify the signature scheme with **test-only** values defined in
  the test, never a key from Indodax's pages.

## To Verify Live (OQ-18)

The exact ordering of mixed query and body parameters; whether `Accept` is enforced; and the exact response
to a deliberately wrong signature. Observe with the Read-only key, then correct this document.
