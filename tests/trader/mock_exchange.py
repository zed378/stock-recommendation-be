"""A mock Indodax, shaped from the official documentation (commit 8d1b409).

SYNTHETIC. Nothing here was observed on the real exchange. It exists so the
whole order path can be tested without contact with production, because Indodax
publishes no sandbox (docs/10-OPERATIONS/00).

What it models: signature verification (over the transmitted string, with
test-only keys defined by the test), the `timestamp`/`recvWindow` rule, the
documented error codes, duplicate `newClientOrderId` (-2010), a visibility lag
for freshly accepted orders, the documented rate limits, the 7-day history
cap, `symbol` being required on history, and both documented spellings of a few
quirky fields.

What it does NOT model: real latency, queue position, real fees, matching beyond
"a LIMIT rests until `fill()` is called and a MARKET fills at the configured
price", MOC crossing behaviour (not documented), or anything the documentation
does not state. Its guarantees are about the Trader's handling, not the exchange.

It is in-process (an `httpx.MockTransport`): no port is opened.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict, deque
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

import httpx

TEST_KEY = "test-key-generated-in-this-test-file"
TEST_SECRET = "test-secret-generated-in-this-test-file"


class MockExchange:
    def __init__(self, *, now_ms: int = 1_800_000_000_000) -> None:
        self.now_ms = now_ms
        self.keys: dict[str, dict[str, Any]] = {
            TEST_KEY: {"secret": TEST_SECRET, "can_trade": True}
        }
        self.can_withdraw = False
        self.can_withdraw_fiat = False
        self.balances: dict[str, tuple[str, str]] = {"IDR": ("100000000", "0"), "BTC": ("1", "0")}
        self.pairs: list[dict[str, Any]] = [
            {
                "id": "btcidr",
                "symbol": "BTCIDR",
                "base_currency": "idr",
                "traded_currency": "btc",
                "ticker_id": "btc_idr",
                "quantity_increment": "0.00000001",
                "price_precision": 1000,
                "pricescale": 1000,
                "trade_min_base_currency": 50000,
                "trade_min_traded_currency": 0.0001,
                "trade_fee_percent_maker": 0.1,
                "trade_fee_percent_taker": 0.2,
            }
        ]
        self.increments = {"btc_idr": "1000"}
        self.prices = {"BTCIDR": "1236777000"}
        self.books = {"BTCIDR": ("1236777000", "0.5", "1236800000", "0.5")}
        self.candles: dict[tuple[str, str], list[tuple[int, str, str, str, str, str]]] = {}
        self.candle_numbers_as_strings = False
        self.market_fill_price = "1236800000"

        self.visibility_lag_ms = 0
        self.history_uses_ori_qty = True  # D9: history spells it `oriQty`
        self.orders: dict[int, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self._next_order = 1000
        self._next_trade = 1

        self.requests: list[dict[str, Any]] = []  # a record for assertions
        self._injected: dict[tuple[str, str], deque[Callable[[], httpx.Response]]] = defaultdict(
            deque
        )
        self._hits: dict[str, deque[int]] = defaultdict(deque)

    # --------------------------------------------------------------- control

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def client_clock(self, skew_ms: int = 0) -> Callable[[], float]:
        """A clock for the client, optionally skewed relative to the exchange."""
        return lambda: (self.now_ms + skew_ms) / 1000

    def inject(self, method: str, path: str, response: Callable[[], httpx.Response]) -> None:
        """Make the next request to (method, path) return/raise this instead."""
        self._injected[(method, path)].append(response)

    def inject_timeout(self, method: str, path: str) -> None:
        def raise_timeout() -> httpx.Response:
            raise httpx.ReadTimeout("injected timeout")

        self.inject(method, path, raise_timeout)

    def inject_error(self, method: str, path: str, status: int, code: int, msg: str) -> None:
        self.inject(method, path, lambda: _json(status, {"code": code, "msg": msg}))

    def fill(
        self, order_id: int, qty: str, price: str | None = None, *, maker: bool = True
    ) -> None:
        """Script a (partial) fill of a resting order."""
        o = self.orders[order_id]
        q = Decimal(qty)
        o["executed"] = str(Decimal(o["executed"]) + q)
        p = price or o.get("price") or self.market_fill_price
        o["status"] = (
            "FILLED" if Decimal(o["executed"]) >= Decimal(o["orig"]) else "PARTIALLY_FILLED"
        )
        self.trades.append(
            {
                "tradeId": str(72057594037936570 + self._next_trade),
                "orderId": o["full"],
                "clientOrderId": o["client"],
                "symbol": o["symbol"].lower(),
                "price": p,
                "qty": qty,
                "quoteQty": str(int(Decimal(p) * q)),
                "commission": "468",
                "commissionAsset": "idr",
                "isBuyer": o["side"] == "BUY",
                "isMaker": maker,
                "time": self.now_ms,
            }
        )
        self._next_trade += 1

    # --------------------------------------------------------------- handler

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(
            {
                "method": request.method,
                "path": path,
                "query": request.url.query.decode(),
                "headers": dict(request.headers),
                "body": request.content.decode(),
            }
        )
        queued = self._injected.get((request.method, path))
        if queued:
            return queued.popleft()()

        limited = self._rate_limit(request)
        if limited is not None:
            return limited

        routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {
            ("GET", "/api/server_time"): self._server_time,
            ("GET", "/api/pairs"): lambda r: _json(200, self.pairs),
            ("GET", "/api/price_increments"): lambda r: _json(200, {"increments": self.increments}),
            ("GET", "/tradingview/history_v2"): self._ohlc,
            ("GET", "/api/v2/ticker/price"): self._ticker_price,
            ("GET", "/api/v2/ticker/bookTicker"): self._book_ticker,
            ("GET", "/api/v2/account"): self._signed(self._account),
            ("GET", "/api/v2/openOrders"): self._signed(self._open_orders),
            ("GET", "/api/v2/order"): self._signed(self._get_order),
            ("POST", "/api/v2/order"): self._signed(self._create, trade=True),
            ("DELETE", "/api/v2/order"): self._signed(self._cancel, trade=True),
            ("GET", "/api/v2/order/histories"): self._signed(self._histories),
            ("GET", "/api/v2/myTrades"): self._signed(self._my_trades),
        }
        handler = routes.get((request.method, path))
        if handler is None:
            return _err(404, -1099, "The requested resource does not exist.")
        return handler(request)

    # ----------------------------------------------------------- rate limits

    def _rate_limit(self, request: httpx.Request) -> httpx.Response | None:
        path = request.url.path
        private = path.startswith("/api/v2/") and path not in {
            "/api/v2/ticker/price",
            "/api/v2/ticker/bookTicker",
            "/api/v2/depth",
        }
        checks: list[tuple[str, int, int]] = []  # (bucket, limit, window_ms)
        if private:
            checks.append(("private", 300, 60_000))
        elif path.startswith("/api/v2/"):
            checks.append(("public_v2", 300, 60_000))
        else:
            checks.append(("public_legacy", 180, 60_000))
        if request.method == "POST" and path == "/api/v2/order":
            symbol = dict(parse_qsl(request.content.decode())).get("symbol", "")
            checks.append((f"create:{symbol}", 20, 1_000))
        if request.method == "DELETE" and path == "/api/v2/order":
            checks.append(("cancel", 30, 1_000))
        for bucket, limit, window in checks:
            hits = self._hits[bucket]
            while hits and hits[0] <= self.now_ms - window:
                hits.popleft()
            if len(hits) >= limit:
                return _err(429, -1003, "Too many requests.")
            hits.append(self.now_ms)
        return None

    # --------------------------------------------------------------- signing

    def _signed(self, handler, *, trade: bool = False):
        def wrapper(request: httpx.Request) -> httpx.Response:
            key = request.headers.get("X-APIKEY")
            if not key:
                return _err(400, -2014, "API key not found in header.")
            sign = request.headers.get("Sign")
            if not sign:
                return _err(400, -1022, "sign not found in the header.")
            account = self.keys.get(key)
            if account is None:
                return _err(
                    401, -1002, "Invalid credentials. API not found or session has expired."
                )
            payload = (
                request.content.decode() if request.method == "POST" else request.url.query.decode()
            )
            expected = hmac.new(
                account["secret"].encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, sign.lower()):
                return _err(400, -1022, "Invalid nonce/signature.")
            params = dict(parse_qsl(payload))
            if "timestamp" not in params and "nonce" not in params:
                return _err(400, -1102, "A mandatory parameter was not sent.")
            if "timestamp" in params:
                window = int(params.get("recvWindow", "5000"))
                ts = int(params["timestamp"])
                if ts >= self.now_ms + 1000 or self.now_ms - ts > window:
                    return _err(
                        400,
                        -1021,
                        "Invalid timestamp. Timestamp for this request is "
                        "outside of the recvWindow.",
                    )
            if trade and not account["can_trade"]:
                return _err(403, -2015, "Access denied.")
            return handler(request, params)

        return wrapper

    # ---------------------------------------------------------------- public

    def _server_time(self, request: httpx.Request) -> httpx.Response:
        return _json(200, {"timezone": "UTC", "server_time": self.now_ms})

    def _ohlc(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        if not all(k in q for k in ("from", "to", "symbol", "tf")):
            return _err(400, -1102, "A mandatory parameter was not sent.")
        rows = self.candles.get((q["symbol"], q["tf"]), [])
        out = []
        for ts, o, h, low, c, v in rows:
            if int(q["from"]) <= ts <= int(q["to"]):
                nums = (lambda x: x) if self.candle_numbers_as_strings else (lambda x: float(x))
                out.append(
                    {
                        "Time": ts,
                        "Open": nums(o),
                        "High": nums(h),
                        "Low": nums(low),
                        "Close": nums(c),
                        "Volume": v,
                    }
                )
        return _json(200, out)

    def _ticker_price(self, request: httpx.Request) -> httpx.Response:
        syms = _symbols(request)
        if syms is None:
            return _json(200, [{"symbol": s, "price": p} for s, p in self.prices.items()])
        bad = [s for s in syms if s not in self.prices]
        if bad:
            return _err(400, -1121, "Invalid symbol.")
        rows = [{"symbol": s, "price": self.prices[s]} for s in syms]
        return _json(200, rows if len(rows) > 1 or "symbols" in request.url.params else rows[0])

    def _book_ticker(self, request: httpx.Request) -> httpx.Response:
        syms = _symbols(request) or list(self.books)
        if any(s not in self.books for s in syms):
            return _err(400, -1121, "Invalid symbol.")
        rows = [
            {"symbol": s, "bidPrice": b[0], "bidQty": b[1], "askPrice": b[2], "askQty": b[3]}
            for s, b in ((s, self.books[s]) for s in syms)
        ]
        return _json(200, rows if len(rows) > 1 or "symbols" in request.url.params else rows[0])

    # --------------------------------------------------------------- private

    def _account(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        return _json(
            200,
            {
                "canTrade": self.keys.get(request.headers.get("X-APIKEY", ""), {}).get(
                    "can_trade", True
                ),
                "canWithdraw": self.can_withdraw,
                "canWithdrawFiat": self.can_withdraw_fiat,
                "accountType": "individual",
                "balances": [
                    {"asset": a, "free": f, "locked": lk} for a, (f, lk) in self.balances.items()
                ],
                "uid": 1,
            },
        )

    def _visible(self, o: dict[str, Any]) -> bool:
        return self.now_ms >= o["visible_at"]

    def _out(
        self, o: dict[str, Any], *, history: bool = False, create: bool = False
    ) -> dict[str, Any]:
        qty_key = "oriQty" if history and self.history_uses_ori_qty else "origQty"
        body: dict[str, Any] = {
            "symbol": o["symbol"],
            "orderId": o["full"] if history else o["id"],
            "clientOrderId": o["client"],
            "side": o["side"],
            "type": o["type"],
            qty_key: o["orig"],
            "executedQty": o["executed"],
            "fullOrderId": o["full"],
        }
        if o.get("price"):
            body["price"] = o["price"]
        if not create:
            body["status"] = o["status"]
            body["time"] = o["time"]
        if history:
            body["symbol"] = o["symbol"].lower()
            body["submitTime"] = body.pop("time")
            body["finishTime"] = o["time"]
            if o.get("cancel_reason"):
                body["cancelReason"] = o["cancel_reason"]
        return body

    def _find(self, symbol: str, params: dict[str, str]) -> dict[str, Any] | None:
        for o in self.orders.values():
            if o["symbol"] != symbol or not self._visible(o):
                continue
            if "orderId" in params and str(o["id"]) == params["orderId"]:
                return o
            if "origClientOrderId" in params and o["client"] == params["origClientOrderId"]:
                return o
        return None

    def _open_orders(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        sym = params.get("symbol")
        if sym and sym not in self.prices:
            return _err(400, -1121, "Invalid symbol.")
        return _json(
            200,
            [
                self._out(o)
                for o in self.orders.values()
                if self._visible(o)
                and o["status"] in {"NEW", "PARTIALLY_FILLED"}
                and (not sym or o["symbol"] == sym)
            ],
        )

    def _get_order(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        sym = params.get("symbol", "")
        if sym not in self.prices:
            return _err(400, -1121, "Invalid symbol.")
        o = self._find(sym, params)
        if o is None:
            return _err(404, -2013, "Order not found or not yet available.")
        return _json(200, self._out(o))

    def _create(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        sym, side, typ = params.get("symbol", ""), params.get("side"), params.get("type")
        if sym not in self.prices:
            return _err(400, -1121, "Invalid symbol.")
        if side not in {"BUY", "SELL"}:
            return _err(
                400,
                -1130,
                "Invalid parameter value.\n\nInvalid parameter 'side', must be BUY or SELL",
            )
        if typ == "STOP_LIMIT":
            return _err(
                400,
                -1130,
                "Invalid parameter value.\n\nInvalid parameter 'type', stop_limit_not_available",
            )
        if typ not in {"LIMIT", "MARKET"}:
            return _err(
                400,
                -1130,
                "Invalid parameter value.\n\nInvalid parameter 'type', must be LIMIT or MARKET",
            )
        if typ == "LIMIT" and "price" not in params:
            return _err(
                400,
                -1130,
                "Invalid parameter value.\n\nInvalid parameter 'price', required for LIMIT order",
            )
        qty = params.get("quantity")
        if qty is not None and -Decimal(qty).as_tuple().exponent > 8:
            return _err(400, -1130, "[quantity] amount has more precision than allowed (8)")
        client = params.get("newClientOrderId") or f"auto-{self._next_order}"
        if any(o["client"] == client for o in self.orders.values()):
            return _err(400, -2010, "Order was rejected. Duplicate client order ID.")
        if side == "BUY" and typ == "LIMIT":
            cost = Decimal(params["price"]) * Decimal(qty or "0")
            if cost > Decimal(self.balances["IDR"][0]):
                return _err(400, -2010, "Order was rejected. Insufficient balance.")
        self._next_order += 1
        oid = self._next_order
        o = {
            "id": oid,
            "full": f"{sym.lower()}-{typ.lower()}-{oid}",
            "client": client,
            "symbol": sym,
            "side": side,
            "type": typ,
            "price": params.get("price"),
            "orig": qty or params.get("quoteOrderQty", "0"),
            "executed": "0",
            "status": "NEW",
            "time": self.now_ms,
            "visible_at": self.now_ms + self.visibility_lag_ms,
        }
        self.orders[oid] = o
        if typ == "MARKET":
            self.fill(oid, o["orig"], self.market_fill_price, maker=False)
        return _json(200, self._out(o, create=True))

    def _cancel(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        sym = params.get("symbol", "")
        if sym not in self.prices:
            return _err(400, -1121, "Invalid symbol.")
        o = self._find(sym, params)
        if o is None:
            return _err(
                404,
                -2013,
                f"order {params.get('orderId') or params.get('origClientOrderId')} is not exists",
            )
        o["status"] = "CANCELLED"
        return _json(200, {**self._out(o, create=True), "origClientOrderId": o["client"]})

    def _window(self, params: dict[str, str]) -> httpx.Response | None:
        if "symbol" not in params:
            return _err(400, -1102, "Mandatory parameters symbol were not sent")
        if params["symbol"].upper() not in self.prices:
            return _err(400, -1121, "Invalid symbol.")
        if "startTime" in params and "endTime" in params:
            span = int(params["endTime"]) - int(params["startTime"])
            if span > 7 * 86_400_000:
                return _err(
                    400,
                    -1130,
                    "Invalid parameter value.\n\nInvalid parameter 'timeRange', "
                    "time range cannot exceed 7 days",
                )
        return None

    def _histories(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        if (bad := self._window(params)) is not None:
            return bad
        sym = params["symbol"].upper()
        done = [
            o
            for o in self.orders.values()
            if o["symbol"] == sym and o["status"] in {"FILLED", "CANCELLED", "REJECTED"}
        ]
        return _json(200, {"data": [self._out(o, history=True) for o in done]})

    def _my_trades(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        if (bad := self._window(params)) is not None:
            return bad
        sym = params["symbol"].lower()
        return _json(200, {"data": [t for t in self.trades if t["symbol"] == sym]})


def _symbols(request: httpx.Request) -> list[str] | None:
    q = request.url.params
    if "symbols" in q:
        return [s.strip().upper() for s in q["symbols"].split(",") if s.strip()]
    if "symbol" in q:
        return [q["symbol"].upper()]
    return None


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status, content=json.dumps(body), headers={"content-type": "application/json"}
    )


def _err(status: int, code: int, msg: str) -> httpx.Response:
    return _json(status, {"code": code, "msg": msg})
