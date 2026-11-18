"""The Indodax connector: the only module that speaks Indodax (docs/06-INTEGRATIONS).

Trade API 2.0 only (ADR-002). Everything here is **documented, not yet observed**
against the live exchange (T2-07 is the owner-led check). Where the
documentation disagrees with itself, both forms are accepted and the
discrepancy table says so (docs/06-INTEGRATIONS/11).

Design rules enforced here:

* The public surface is an allowlist (`ALLOWED_METHODS`). There is no withdrawal,
  deposit, fiat, or generic "call any path" method, and a test fails if one is
  added (ADR-013).
* The API secret is fetched from a provider for the length of one signature and
  is never stored on the client, logged, or placed in an exception.
* A request is signed over exactly the string that is transmitted (query string
  for GET/DELETE, form body for POST), with every parameter in that one place.
* A timeout or 5xx on a *write* raises with `outcome_unknown=True`. The write is
  never retried here (ADR-024).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import statistics
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

from aidss_trader.connector.errors import ConnectorError, ErrorClass, classify
from aidss_trader.connector.throttle import Throttle
from aidss_trader.connector.types import (
    Account,
    BookTicker,
    Candle,
    OrderInfo,
    PairInfo,
    TradeFill,
)

logger = logging.getLogger("aidss_trader.connector")

ALLOWED_METHODS = frozenset(
    {
        # public
        "get_server_time",
        "get_pairs",
        "get_price_increments",
        "get_ohlc",
        "get_last_prices",
        "get_book_tickers",
        # private, read
        "get_account",
        "get_open_orders",
        "get_order",
        "get_order_history",
        "get_my_trades",
        # private, write
        "create_order",
        "cancel_order",
        # clock
        "check_clock",
    }
)

#: Readings per clock check; odd, so the median is one of them. See `check_clock`.
CLOCK_SAMPLES = 5
CLOCK_RETRY_PAUSE_S = 0.5

_CLIENT_ORDER_ID = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_TIMEFRAMES = {"4H": "240", "1D": "1D"}  # the OHLC endpoint has no 5 minute timeframe


def canonical(symbol: str) -> str:
    """BTCIDR, btcidr, btc_idr are one pair (docs/06-INTEGRATIONS/11, D10)."""
    return re.sub(r"[^A-Za-z0-9]", "", symbol).upper()


def fmt(value: Decimal) -> str:
    """A decimal as a plain string: never exponent notation, never a float."""
    return format(value.normalize(), "f") if value != 0 else "0"


def _dec(value: Any, field: str, operation: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ConnectorError(
            ErrorClass.MALFORMED, f"{field} is not a number", operation=operation
        ) from exc


def _need(obj: Any, key: str, operation: str) -> Any:
    if not isinstance(obj, dict) or key not in obj or obj[key] is None:
        raise ConnectorError(ErrorClass.MALFORMED, f"missing field {key!r}", operation=operation)
    return obj[key]


def _optional_decimal(raw: dict[str, Any], op: str) -> Callable[[str], Decimal | None]:
    """A reader for fields that really are optional in the documented examples."""

    def read(key: str) -> Decimal | None:
        return _dec(raw[key], key, op) if raw.get(key) is not None else None

    return read


def _first(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


class IndodaxClient:
    def __init__(
        self,
        *,
        exchange_base_url: str,
        public_base_url: str,
        credentials: Callable[[], tuple[str, str]] | None,
        throttle: Throttle,
        timeout_s: float,
        clock_check_interval_s: float,
        max_skew_ms: int,
        recv_window_ms: int | None = None,
        max_read_retries: int = 2,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._exchange = exchange_base_url.rstrip("/")
        self._public = public_base_url.rstrip("/")
        self._credentials = credentials
        self._throttle = throttle
        self._clock_check_interval_s = clock_check_interval_s
        self._max_skew_ms = max_skew_ms
        self._recv_window_ms = recv_window_ms
        self._max_read_retries = max_read_retries
        self._clock = clock
        self._sleep = sleep
        self._http = httpx.Client(transport=transport, timeout=timeout_s)
        self._last_clock_ok: float | None = None
        # Per thread: the runtime loop and the operator API share this client.
        self._wire = threading.local()

    # ------------------------------------------------------------------ core

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _send(
        self,
        operation: str,
        method: str,
        base: str,
        path: str,
        params: list[tuple[str, str]],
        *,
        scope: str,
        signed: bool,
        write: bool,
    ) -> Any:
        self._throttle.acquire(scope)
        pairs = list(params)
        headers = {"Accept": "application/json"}
        if signed:
            pairs.append(("timestamp", str(self._now_ms())))
            if self._recv_window_ms is not None:
                pairs.append(("recvWindow", str(self._recv_window_ms)))
        payload = urlencode(pairs)
        content: bytes | None = None
        url = f"{base}{path}"
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            content = payload.encode()
        elif payload:
            url = f"{url}?{payload}"

        if signed:
            if self._credentials is None:
                raise ConnectorError(
                    ErrorClass.AUTH, "no credential provider configured", operation=operation
                )
            key, secret = self._credentials()
            # The signature covers exactly the transmitted string.
            headers["X-APIKEY"] = key
            headers["Sign"] = hmac.new(
                secret.encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
            del secret  # not kept beyond this signature

        sent_ms = self._now_ms()
        try:
            response = self._http.request(method, url, headers=headers, content=content)
            self._wire.span = (sent_ms, self._now_ms())
        except httpx.TimeoutException as exc:
            raise ConnectorError(
                ErrorClass.TIMEOUT,
                "no response in time",
                operation=operation,
                outcome_unknown=write,
            ) from exc
        except httpx.TransportError as exc:
            raise ConnectorError(
                ErrorClass.UNAVAILABLE,
                "transport failure",
                operation=operation,
                outcome_unknown=write,
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400 or (
            isinstance(body, dict) and "code" in body and "msg" in body
        ):
            code = body.get("code") if isinstance(body, dict) else None
            msg = str(body.get("msg")) if isinstance(body, dict) else "unreadable error body"
            error_class = classify(response.status_code, code)
            raise ConnectorError(
                error_class,
                msg,
                operation=operation,
                code=code,
                http_status=response.status_code,
                # A 5xx on a write: the exchange may have acted.
                outcome_unknown=write and error_class is ErrorClass.UNAVAILABLE,
            )
        if body is None:
            raise ConnectorError(
                ErrorClass.MALFORMED,
                "response is not JSON",
                operation=operation,
                http_status=response.status_code,
            )
        return body

    def _call(
        self,
        operation: str,
        method: str,
        base: str,
        path: str,
        params: list[tuple[str, str]] | None = None,
        *,
        scope: str,
        signed: bool = False,
        write: bool = False,
    ) -> Any:
        if signed:
            self._ensure_clock(operation)
        attempts = 0 if write else self._max_read_retries
        skew_retried = False
        while True:
            try:
                return self._send(
                    operation,
                    method,
                    base,
                    path,
                    params or [],
                    scope=scope,
                    signed=signed,
                    write=write,
                )
            except ConnectorError as exc:
                if exc.error_class is ErrorClass.CLOCK_SKEW and signed and not skew_retried:
                    # Re-measure once; a genuine skew raises from check_clock.
                    skew_retried = True
                    self.check_clock()
                    continue
                if (
                    not write
                    and exc.error_class
                    in {ErrorClass.UNAVAILABLE, ErrorClass.TIMEOUT, ErrorClass.RATE_LIMIT}
                    and attempts > 0
                ):
                    attempts -= 1
                    self._sleep(0.5)
                    continue
                raise

    # ----------------------------------------------------------------- clock

    def check_clock(self) -> int:
        """Measure the offset to Indodax's clock; raise CLOCK_SKEW beyond tolerance.

        Indodax rejects a request whose timestamp is 1 s or more *ahead* of its
        clock, so the tolerance must sit well below that. The offset is measured
        at the midpoint of the round trip so network latency is not mistaken for
        skew.
        """
        # Two layers against a noisy reference, neither of which loosens the limit (ADR-041).
        # Indodax serves `/api/server_time` through caches: from the VM most readings sat within
        # 50 ms of the host clock (NTP-synced, a few ms off) but about one in six was a stale value
        # off by roughly one second, which a single sample reports as a skew and halts on.
        #  1. The offset is the median of several readings. A clock that really is off moves every
        #     reading, so the median moves with it; a stale minority does not.
        #  2. A median beyond the limit is measured once more before it counts (docs 06/08: re-sync,
        #     retry once, then halt). Two bad measurements in a row halt; one does not.
        offset = self._median_offset()
        if abs(offset) > self._max_skew_ms:
            self._sleep(CLOCK_RETRY_PAUSE_S)
            offset = self._median_offset()
        if abs(offset) > self._max_skew_ms:
            raise ConnectorError(
                ErrorClass.CLOCK_SKEW,
                f"clock offset {offset} ms (median of {CLOCK_SAMPLES}, measured twice) exceeds "
                f"the {self._max_skew_ms} ms limit",
                operation="check_clock",
            )
        self._last_clock_ok = self._clock()
        return offset

    def _median_offset(self) -> int:
        offsets: list[int] = []
        for _ in range(CLOCK_SAMPLES):
            server_ms = self.get_server_time()
            # Only the time on the wire counts. Measuring around the call would include the
            # throttle's wait, and a drained bucket would read as a clock skew that is not there.
            t0, t1 = self._wire.span
            offsets.append(server_ms - (t0 + t1) // 2)
        return int(statistics.median(offsets))

    def _ensure_clock(self, operation: str) -> None:
        if self._last_clock_ok is None or (
            self._clock() - self._last_clock_ok > self._clock_check_interval_s
        ):
            self.check_clock()

    # ---------------------------------------------------------------- public

    def get_server_time(self) -> int:
        op = "get_server_time"
        body = self._call(op, "GET", self._public, "/api/server_time", scope="public_legacy")
        return int(_need(body, "server_time", op))

    def get_pairs(self) -> list[PairInfo]:
        op = "get_pairs"
        body = self._call(op, "GET", self._public, "/api/pairs", scope="public_legacy")
        if not isinstance(body, list):
            raise ConnectorError(ErrorClass.MALFORMED, "expected a list of pairs", operation=op)
        out: list[PairInfo] = []
        for raw in body:
            ticker_id = str(_need(raw, "ticker_id", op))
            optional = _optional_decimal(raw, op)
            out.append(
                PairInfo(
                    pair=canonical(str(_first(raw, "symbol", "id") or ticker_id)),
                    ticker_id=ticker_id,
                    base_asset=str(_need(raw, "base_currency", op)).upper(),
                    quote_asset=str(_need(raw, "traded_currency", op)).upper(),
                    quantity_increment=optional("quantity_increment"),
                    min_base_idr=optional("trade_min_base_currency"),
                    min_traded_qty=optional("trade_min_traded_currency"),
                    maintenance=bool(raw.get("is_maintenance", 0)),
                    suspended=bool(raw.get("is_market_suspended", 0)),
                    maker_fee_pct=optional("trade_fee_percent_maker"),
                    taker_fee_pct=optional("trade_fee_percent_taker"),
                    raw=raw,
                )
            )
        return out

    def get_price_increments(self) -> dict[str, Decimal]:
        op = "get_price_increments"
        body = self._call(op, "GET", self._public, "/api/price_increments", scope="public_legacy")
        incs = _need(body, "increments", op)
        return {str(k): _dec(v, k, op) for k, v in incs.items()}

    def get_ohlc(self, symbol: str, timeframe: str, start_s: int, end_s: int) -> list[Candle]:
        op = "get_ohlc"
        if timeframe not in _TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {sorted(_TIMEFRAMES)}")
        params = [
            ("from", str(start_s)),
            ("symbol", canonical(symbol)),
            ("tf", _TIMEFRAMES[timeframe]),
            ("to", str(end_s)),
        ]
        body = self._call(
            op, "GET", self._public, "/tradingview/history_v2", params, scope="public_legacy"
        )
        if not isinstance(body, list):
            raise ConnectorError(ErrorClass.MALFORMED, "expected a list of candles", operation=op)
        out = []
        for row in body:
            # `Time` is Unix seconds in the documented example (D11).
            ts = datetime.fromtimestamp(int(_need(row, "Time", op)), UTC)
            out.append(
                Candle(
                    open_time=ts,
                    open=_dec(_need(row, "Open", op), "Open", op),
                    high=_dec(_need(row, "High", op), "High", op),
                    low=_dec(_need(row, "Low", op), "Low", op),
                    close=_dec(_need(row, "Close", op), "Close", op),
                    volume=_dec(_need(row, "Volume", op), "Volume", op),
                )
            )
        return out

    def get_last_prices(self, symbols: Iterable[str] | None = None) -> dict[str, Decimal]:
        op = "get_last_prices"
        params = [("symbols", ",".join(canonical(s) for s in symbols))] if symbols else []
        body = self._call(
            op, "GET", self._exchange, "/api/v2/ticker/price", params, scope="public_v2"
        )
        rows = body if isinstance(body, list) else [body]
        return {
            canonical(str(_need(r, "symbol", op))): _dec(_need(r, "price", op), "price", op)
            for r in rows
        }

    def get_book_tickers(self, symbols: Iterable[str] | None = None) -> dict[str, BookTicker]:
        op = "get_book_tickers"
        params = [("symbols", ",".join(canonical(s) for s in symbols))] if symbols else []
        body = self._call(
            op, "GET", self._exchange, "/api/v2/ticker/bookTicker", params, scope="public_v2"
        )
        rows = body if isinstance(body, list) else [body]
        out = {}
        for r in rows:
            sym = canonical(str(_need(r, "symbol", op)))
            out[sym] = BookTicker(
                symbol=sym,
                bid_price=_dec(_need(r, "bidPrice", op), "bidPrice", op),
                bid_qty=_dec(_need(r, "bidQty", op), "bidQty", op),
                ask_price=_dec(_need(r, "askPrice", op), "askPrice", op),
                ask_qty=_dec(_need(r, "askQty", op), "askQty", op),
            )
        return out

    # --------------------------------------------------------------- private

    def get_account(self) -> Account:
        op = "get_account"
        body = self._call(
            op,
            "GET",
            self._exchange,
            "/api/v2/account",
            [("omitZeroBalances", "true")],
            scope="private",
            signed=True,
        )
        balances = {
            str(_need(b, "asset", op)).upper(): (
                _dec(_need(b, "free", op), "free", op),
                _dec(_need(b, "locked", op), "locked", op),
            )
            for b in _need(body, "balances", op)
        }
        return Account(
            can_trade=bool(_need(body, "canTrade", op)),
            can_withdraw=bool(_need(body, "canWithdraw", op)),
            can_withdraw_fiat=bool(_need(body, "canWithdrawFiat", op)),
            balances=balances,
        )

    def get_open_orders(self, symbol: str | None = None) -> list[OrderInfo]:
        op = "get_open_orders"
        params = [("symbol", canonical(symbol))] if symbol else []
        body = self._call(
            op, "GET", self._exchange, "/api/v2/openOrders", params, scope="private", signed=True
        )
        if not isinstance(body, list):
            raise ConnectorError(ErrorClass.MALFORMED, "expected a list of orders", operation=op)
        return [self._order(r, op) for r in body]

    def get_order(
        self, symbol: str, *, order_id: int | None = None, client_order_id: str | None = None
    ) -> OrderInfo:
        op = "get_order"
        if (order_id is None) == (client_order_id is None):
            raise ValueError("give exactly one of order_id and client_order_id")
        params = [("symbol", canonical(symbol))]
        # orderId wins when both are present, so only one is ever sent.
        params.append(
            ("orderId", str(order_id))
            if order_id is not None
            else ("origClientOrderId", str(client_order_id))
        )
        body = self._call(
            op, "GET", self._exchange, "/api/v2/order", params, scope="private", signed=True
        )
        return self._order(body, op)

    def get_order_history(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[OrderInfo]:
        op = "get_order_history"
        params = self._window(symbol, start_ms, end_ms, limit)
        body = self._call(
            op,
            "GET",
            self._exchange,
            "/api/v2/order/histories",
            params,
            scope="private",
            signed=True,
        )
        return [self._order(r, op) for r in _need(body, "data", op)]

    def get_my_trades(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]:
        op = "get_my_trades"
        params = self._window(symbol, start_ms, end_ms, limit)
        body = self._call(
            op, "GET", self._exchange, "/api/v2/myTrades", params, scope="private", signed=True
        )
        return [
            TradeFill(
                trade_id=str(_need(r, "tradeId", op)),
                full_order_id=str(_need(r, "orderId", op)),
                client_order_id=r.get("clientOrderId"),
                symbol=canonical(str(_need(r, "symbol", op))),
                price=_dec(_need(r, "price", op), "price", op),
                qty=_dec(_need(r, "qty", op), "qty", op),
                quote_qty=_dec(_need(r, "quoteQty", op), "quoteQty", op),
                commission=_dec(_need(r, "commission", op), "commission", op),
                commission_asset=str(_need(r, "commissionAsset", op)),
                is_buyer=bool(_need(r, "isBuyer", op)),
                is_maker=bool(_need(r, "isMaker", op)),
                time_ms=int(_need(r, "time", op)),
            )
            for r in _need(body, "data", op)
        ]

    def create_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        client_order_id: str,
        price: Decimal | None = None,
        quantity: Decimal | None = None,
        quote_order_qty: Decimal | None = None,
        time_in_force: str | None = None,
        stp_mode: str | None = None,
    ) -> OrderInfo:
        """Create an order. Never retried: a timeout leaves the outcome unknown (ADR-024)."""
        op = "create_order"
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if order_type not in {"LIMIT", "MARKET"}:
            # STOP_LIMIT is rejected by the exchange (D6, ADR-007); never even attempted.
            raise ValueError("order_type must be LIMIT or MARKET")
        if not _CLIENT_ORDER_ID.match(client_order_id):
            raise ValueError("client_order_id must be 1-36 chars of letters, digits, _ or -")
        if order_type == "LIMIT" and (price is None or quantity is None):
            raise ValueError("a LIMIT order needs price and quantity")
        if order_type == "MARKET":
            if side == "BUY" and (quote_order_qty is None or quantity is not None):
                raise ValueError("BUY MARKET takes quote_order_qty and not quantity")
            if side == "SELL" and quantity is None:
                raise ValueError("SELL MARKET needs quantity")
        if time_in_force is not None and time_in_force not in {"GTC", "MOC"}:
            # FOK is listed for MARKET in the enums but not for Create Order (D4).
            raise ValueError("time_in_force must be GTC or MOC")
        if stp_mode is not None and stp_mode not in {"EXPIRE_TAKER", "EXPIRE_MAKER", "EXPIRE_BOTH"}:
            raise ValueError("invalid selfTradePreventionMode")

        params = [("symbol", canonical(symbol)), ("side", side), ("type", order_type)]
        if price is not None:
            params.append(("price", fmt(price)))
        if quantity is not None:
            params.append(("quantity", fmt(quantity)))
        if quote_order_qty is not None:
            params.append(("quoteOrderQty", fmt(quote_order_qty)))
        params.append(("newClientOrderId", client_order_id))
        if time_in_force is not None:
            params.append(("timeInForce", time_in_force))
        if stp_mode is not None:
            params.append(("selfTradePreventionMode", stp_mode))

        body = self._call(
            op,
            "POST",
            self._exchange,
            "/api/v2/order",
            params,
            scope=f"create:{canonical(symbol)}",
            signed=True,
            write=True,
        )
        return self._order(body, op)

    def cancel_order(
        self, symbol: str, *, order_id: int | None = None, client_order_id: str | None = None
    ) -> OrderInfo:
        """Cancel an order. The caller confirms the outcome by reading the order."""
        op = "cancel_order"
        if (order_id is None) == (client_order_id is None):
            raise ValueError("give exactly one of order_id and client_order_id")
        params = [("symbol", canonical(symbol))]
        params.append(
            ("orderId", str(order_id))
            if order_id is not None
            else ("origClientOrderId", str(client_order_id))
        )
        body = self._call(
            op,
            "DELETE",
            self._exchange,
            "/api/v2/order",
            params,
            scope="cancel",
            signed=True,
            write=True,
        )
        return self._order(body, op)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _window(
        symbol: str, start_ms: int | None, end_ms: int | None, limit: int | None
    ) -> list[tuple[str, str]]:
        params = [("symbol", canonical(symbol).lower())]
        if start_ms is not None and end_ms is not None and end_ms - start_ms > 7 * 86_400_000:
            # Both history endpoints cap the interval at 7 days; callers split larger spans.
            raise ValueError("history windows are limited to 7 days; split the span")
        if start_ms is not None:
            params.append(("startTime", str(start_ms)))
        if end_ms is not None:
            params.append(("endTime", str(end_ms)))
        if limit is not None:
            params.append(("limit", str(limit)))
        return params

    @staticmethod
    def _order(raw: Any, op: str) -> OrderInfo:
        if not isinstance(raw, dict):
            raise ConnectorError(ErrorClass.MALFORMED, "order is not an object", operation=op)
        symbol = canonical(str(_need(raw, "symbol", op)))
        # `origQty` everywhere except order history, which spells it `oriQty` (D9).
        orig = _first(raw, "origQty", "oriQty")
        if orig is None:
            raise ConnectorError(ErrorClass.MALFORMED, "missing field 'origQty'", operation=op)
        order_id = raw.get("orderId")
        # The numeric id on create/cancel/get, but a full id such as "btcidr-limit-6423"
        # in history (D8). Keep both representations.
        numeric = int(order_id) if isinstance(order_id, int) or str(order_id).isdigit() else None
        full = raw.get("fullOrderId") or (str(order_id) if numeric is None and order_id else None)
        status = raw.get("status")
        if status is not None and status not in {
            "NEW",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }:
            # An unrecognised status is never guessed at (docs/03-DATA-MODEL/02).
            raise ConnectorError(
                ErrorClass.MALFORMED, f"unrecognised order status {status!r}", operation=op
            )
        price = raw.get("price")
        return OrderInfo(
            symbol=symbol,
            order_id=numeric,
            full_order_id=full,
            client_order_id=_first(raw, "clientOrderId", "origClientOrderId"),
            side=str(_need(raw, "side", op)),
            type=raw.get("type"),
            price=_dec(price, "price", op) if price not in (None, "") else None,
            orig_qty=_dec(orig, "origQty", op),
            executed_qty=_dec(_need(raw, "executedQty", op), "executedQty", op),
            status=status,
            time_ms=_first(raw, "time", "submitTime"),
            cancel_reason=raw.get("cancelReason"),
        )
