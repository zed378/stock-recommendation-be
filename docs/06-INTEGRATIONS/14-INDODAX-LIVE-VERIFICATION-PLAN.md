# 14 — Indodax Live Verification Plan

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer, with the Owner |
| **Decided by** | ADR-002, ADR-013 |
| **Open items** | OQ-3, OQ-4, OQ-5, OQ-18 (decided, ADR-038), OQ-19 (resolved, ADR-041) |

The procedure for task **T2-07**: the first contact with the real exchange. It turns "documented, not yet
observed" into observed facts, **read-only first**, on the owner's instruction. It is owner-led: an agent
prepares and stops.

## Timing (ADR-038)

Done as T2-07 at the end of phase T2, after the connector and the mock exist. Phase A (public endpoints, no key)
can be run earlier at the owner's discretion; it needs no key and no instruction beyond the owner's go-ahead.

## Principles

1. **No order, ever, in T2-07.** Nothing here creates, cancels, or modifies an order. Anything that needs a
   Trade key waits for `T5-06` with a trivial amount and the owner present.
2. **Smallest key that works.** Phase A needs no key. Phase B uses a **Read-only** TAPIv2 key, ideally one
   created only for this check and revoked afterwards.
3. **The key never touches the repository or the chat.** The owner supplies it in their own terminal session
   (for example an environment variable for the run), and it is revoked or rotated after.
4. **Slow and bounded.** Sequential requests with delays, a hard cap on the count, and a stop on the first
   repeated failure. No loops, no load tests.
5. **Record what happened, not what was expected.** A result that contradicts the documentation is the useful
   outcome.

## Stop Conditions

Stop and report if: any `-2015` (access denied) appears (do not retry); a `-1003` or HTTP 429 appears; two
consecutive 5xx; any response suggests the key has more permission than Read; or anything is unclear.

## Phase A: Public endpoints (no key)

| # | Call | Observes | Resolves |
|---|---|---|---|
| A1 | `GET indodax.com/api/server_time` | Response shape; units | D11 |
| A2 | `GET indodax.com/api/pairs` | Which fields exist per pair; `trade_fee_percent*` presence; type of `price_precision`; maintenance flags | D12, D20 |
| A3 | `GET indodax.com/api/price_increments` | Agreement with `pairs` | `06/05` |
| A4 | `GET indodax.com/tradingview/history_v2` for `BTCIDR`, `tf=240` and `1D` over a known range | Time unit, candle boundary and time zone (compare with Indodax's own chart), whether the latest candle is unfinished, maximum range per request, number vs string typing | **OQ-4**, D11, D12, D18 |
| A5 | `GET api.indodax.com/api/v2/ticker/price`, `bookTicker`, `ticker/24hr`, `depth`, `trades` (single and multi-symbol) | Shapes, multi-symbol behavior, `symbol` spellings accepted (`BTCIDR`, `btcidr`, `btc_idr`) | D10, `06/05` |
| A6 | The same public endpoint on `api.indodax.com` and on `tapi.indodax.com` | Which host serves Trade API 2.0 | **D1** |
| A7 | Provoke errors: invalid symbol, invalid `limit`, missing parameter | Error body shape, sign of the code | D17 |
| A8 | Count requests per minute well below the documented limits | Any usage headers; no limit is exceeded on purpose | D19 |

## Phase B: Signed read-only endpoints (Read-only key)

| # | Call | Observes | Resolves |
|---|---|---|---|
| B1 | `GET /api/v2/account` | The permission flags a Read-only key reports (`canTrade`, `canWithdraw`, `canWithdrawFiat`); balances' shape; **redact `uid` and balances before storing** | `06/07`, ADR-013 start check |
| B2 | `GET /api/v2/openOrders` | Empty-array form; `symbol` filter | `06/06` |
| B3 | `GET /api/v2/order` for a **non-existent** `orderId` and `origClientOrderId` | Error code and form (`-2013` vs `1112`), param types | **D2 (read side), D3**, D17 |
| B4 | `GET /api/v2/order/histories` and `myTrades` for a symbol with history, and without `symbol` | `symbol` required; field names (`oriQty` vs `origQty`); order-id forms; window cap behavior; `commission` contents | D8, D9, **OQ-5 (partial)** |
| B5 | A signed call with a **deliberately wrong signature** | The exact error | `06/04` |
| B6 | A signed call with a **deliberately stale timestamp** and a tiny `recvWindow` | `-1021` shape; whether a server time hint is returned | D13 (skew limit decided, ADR-041) |
| B7 | A signed call with both `timestamp` and `nonce` | Which is used | `06/04` |
| B8 | The Private WebSocket token request (`POST .../private_ws/v1/generate_token`) with the TAPIv2 key, **token generation only** | Whether a TAPIv2 key is accepted by a legacy-auth endpoint. **No WebSocket connection is opened** | **OQ-3 (partial)**, D15 |

B8 is a signed request to a legacy path. It creates a token, not an order; the owner decides whether to run
it at all.

## Phase C: Needs a Trade key. Not part of T2-07

| Item | Why it cannot be read-only | Where it goes |
|---|---|---|
| Cancel with only `orderId` or only `origClientOrderId` (D2) | Needs a live order | `T5-06`, tiny amount, owner present |
| `timeInForce` `MOC` and `FOK` behavior (D4) | Needs order creation | `T5-06` |
| Order status values and `stopPrice` in real orders (D5, D6) | Needs orders | Observed from history in `T5-06` |
| Create-order rate limit (D7) | Needs creating orders | Not tested on purpose; respect the documented limits |
| Deadman Switch (OQ-3) | Cancels orders; legacy auth | Left unavailable unless the owner decides otherwise |
| Visibility lag after accepting an order | Needs a live order | `T5-06` |

## What Is Recorded

For each call: UTC time, endpoint, parameters (no secrets), HTTP status, a **redacted** body, and the
conclusion. Redaction removes headers, keys, signatures, `uid`, and balances.

| Output | Where |
|---|---|
| Raw responses | A scratch directory **outside** the repository, deleted after the redacted fixtures are made |
| Redacted fixtures | `tests/trader/fixtures/recorded/`, labelled "recorded on <date>, <endpoint>" (`11/07`) |
| Findings | `06/11`: a dated row in "Resolved" per discrepancy, with the evidence |
| Corrected documents | `06/03` to `06/10`, through the deviation protocol; "not yet observed" removed only where observed |
| Mock corrections | The mock is changed first for each difference, with a test that would have caught it |
| Record | `MEMORY/records/YYYY-MM-DD-T2-07-live-readonly-verification.md`: what was called, what was not, and what remains unobserved |

## After the Check

- The owner **revokes** the Read-only key (or rotates it).
- OQ-3, OQ-4, OQ-5 (partly) are answered as far as the observations allow, and the rest stay open.
- Anything that contradicts a design assumption raises an ADR or a backlog entry before T3 depends on it.

## Not Allowed

A Trade-permission key; any `POST` or `DELETE` to an order endpoint; any `capital/*` or `fiat/*` endpoint; a
request loop; a key in a command line that is stored in shell history; storing a raw response in git.

## Preparation by an Agent (before the owner runs it)

The call list as a script with the caps, delays, and stop conditions above; the redaction function and its
test; the empty record template. The script refuses to run without an explicit confirmation and without the key
being supplied by the owner's environment, and it contains no endpoint outside this plan.

## How the Owner Runs It (prepared 2026-11-15; never run)

The script is `python -m aidss_trader live-check`. It is not a pytest test and has no marker. Its limits are code,
not promises, and are tested against the synthetic mock (`tests/trader/test_livecheck.py`):

- GET only; the module has no function that sends anything else and no order, deposit, withdrawal, or fiat path.
- At most 60 requests, at least 1.5 s apart; it refuses a higher cap or a shorter delay.
- It refuses to start without `--i-understand-this-calls-the-real-exchange`.
- Both output directories must be **outside any git repository**; raw responses go to `--raw-dir`, the report and
  record draft to `--out`. Responses that belong to an account are reduced to their shape, so no balance, order
  id, `uid`, key, secret, or signature reaches a file; known secrets are also scrubbed from any text.
- It stops on `-2015`, on a rate limit, on two server errors in a row, and at once if `GET /api/v2/account` says the
  key can withdraw **or can trade** (the plan allows a Read-only key only).
- The record draft lists what was **not** called, so a step that did not run is never reported as verified.
- B8 (the private WebSocket token) is not implemented; the owner decides it separately.

Phase A (public, no key), from a scratch directory outside the repository:

```
python -m aidss_trader live-check --phase A --raw-dir C:\scratch\raw --out C:\scratch\out --i-understand-this-calls-the-real-exchange
```

Phase B (a Read-only key made for this check, set in **your own terminal session only**, never typed into a command
line or chat). Type the key and secret at a prompt that does not echo, so they do not enter the shell history
(Git Bash; run from the repository root, with the output directories outside any repository):

```
read -rs -p "Read-only API key: " AIDSS_LIVECHECK_KEY; echo
read -rs -p "Secret: " AIDSS_LIVECHECK_SECRET; echo
export AIDSS_LIVECHECK_KEY AIDSS_LIVECHECK_SECRET
mkdir -p ~/livecheck/raw ~/livecheck/out
.venv/Scripts/python -m aidss_trader live-check --phase B \
  --raw-dir "$(cygpath -w ~/livecheck/raw)" --out "$(cygpath -w ~/livecheck/out)" \
  --i-understand-this-calls-the-real-exchange
unset AIDSS_LIVECHECK_KEY AIDSS_LIVECHECK_SECRET
```

If the key is restricted by source address, allow the workstation's address for this key while it runs (the
calls leave from the workstation, not from the server); a `-2015` stops the script. (Corrected 2026-11-18: the
earlier example put the key in the command line, which is stored in shell history. First run: 2026-11-18,
phases A and B, `MEMORY/records/2026-11-18-T2-07-*`.)

Afterwards: revoke the key, read `report-phase-*.json` and `record-draft-phase-*.md`, delete the raw directory, copy
only what is safe into `tests/trader/fixtures/recorded/`, correct the mock first with a test that would have caught
each difference, and amend `06/03` to `06/11` through the deviation protocol. The draft is not a conclusion.
