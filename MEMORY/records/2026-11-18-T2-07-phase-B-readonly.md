# T2-07 phase B: signed read-only calls with a Read-only key (2026-11-18)

Run by the owner from their own terminal (key and secret typed at a no-echo prompt, never in chat or history), a Read-only key made for this check. 12 signed GET calls to `api.indodax.com`, none stopped it. The agent read only the redacted report and the record draft the script wrote (shapes, no balances, uid, key, secret or signature). The integration documents are NOT yet amended: that stays a person's step under the deviation protocol.

Observed:
- **B1** `GET /api/v2/account` answered 200 with `canTrade` false, `canWithdraw` false, `canWithdrawFiat` false for a Read-only key. **Our signing (HMAC-SHA256 of the transmitted query string, `X-APIKEY` and `Sign` headers, `timestamp`) is accepted by the real exchange for a GET.** First observed success of a signed call.
- **B5** a deliberately wrong signature answered **HTTP 401, code -1002**. So `-1002` is what a bad signature or bad credentials look like, not only "invalid credentials" in the narrow sense. This is almost certainly what the owner's earlier key-test refusal `AUTH (code -1002, HTTP 401)` was (a mistyped key or secret); the key test later passed.
- **B6** a stale timestamp with a tiny `recvWindow` answered HTTP 400, code -1021. **B7** a request with both `timestamp` and `nonce` answered 200.
- **B3** a non-existent order, by `orderId` and by `origClientOrderId`: HTTP 404, code -2013 for both (D2 and D3 read side: both forms are understood). **B4** order histories and `myTrades` with a symbol: 200; without a symbol: HTTP 400 (the symbol is required). **B2** open orders with and without `symbol`: 200.
- Error bodies carry a negative numeric `code` and a `msg`, as the connector assumes (D17).

Not observed and still open: field names in history and trade rows (the report records shapes only for the error cases), order creation and cancel (phase C, needs a Trade key, T5-06), `timeInForce`, order status values, create-order rate limit, visibility lag, B8 and the Deadman Switch. The Read+Trade key held by the Trader has therefore still never placed an order.
Owner steps after the run: revoke the Read-only key; delete the raw directory (`~/livecheck/raw`, it holds account responses); the redacted output can stay or go.
