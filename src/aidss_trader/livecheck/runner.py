"""The owner-led, read-only live verification of Indodax (T2-07, docs/06-INTEGRATIONS/14).

**An agent prepares this and stops.** Nothing here has ever been run against the real exchange.
It exists so that the owner can run it once, on purpose, and get observations instead of
assumptions.

What it can do, and the limits that are enforced in code rather than promised in a document:

* GET requests only. This module has no function that sends anything else, and it has no
  order endpoint: the allowlist below is the whole list of paths it can reach.
* Phase A is public and needs no key. Phase B signs read-only calls with a key the owner puts in
  their own terminal's environment; the key is never an argument, never printed, never written.
* A hard cap on requests, a minimum delay between them, and stop conditions from the plan: access
  denied, rate limit, two server errors in a row, or any sign that the key can do more than read.
* Raw responses go to a directory outside the repository; what is written for the repository is
  redacted, and responses that belong to an account are reduced to their shape only.
* The report says what was called, what was observed, and what was **not** called. A step that did
  not run is never reported as verified.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from aidss_trader.livecheck.redact import describe_shape, redact_public, scrub

CONFIRM_FLAG = "--i-understand-this-calls-the-real-exchange"
MAX_REQUESTS = 60
MIN_DELAY_S = 1.5
DEFAULT_HOSTS = {
    "public": "https://indodax.com",
    "api": "https://api.indodax.com",
    "tapi": "https://tapi.indodax.com",
}

# Every (host, path) this module may touch. Nothing else is reachable. No order path appears.
PUBLIC_PATHS = {
    ("public", "/api/server_time"),
    ("public", "/api/pairs"),
    ("public", "/api/price_increments"),
    ("public", "/tradingview/history_v2"),
    ("api", "/api/v2/ticker/price"),
    ("api", "/api/v2/ticker/bookTicker"),
    ("api", "/api/v2/ticker/24hr"),
    ("api", "/api/v2/depth"),
    ("api", "/api/v2/trades"),
    ("tapi", "/api/v2/ticker/price"),
}
SIGNED_PATHS = {
    ("api", "/api/v2/account"),
    ("api", "/api/v2/openOrders"),
    ("api", "/api/v2/order"),  # GET only, and only for ids that do not exist
    ("api", "/api/v2/order/histories"),
    ("api", "/api/v2/myTrades"),
}
ALLOWED = PUBLIC_PATHS | SIGNED_PATHS

NOT_RUN_ALWAYS = [
    "B8 (private WebSocket token): not implemented; the owner decides separately",
    "Phase C (cancel, timeInForce, statuses, create rate limit, lag): needs a Trade key, T5-06",
    "the Deadman Switch (OQ-3): cancels orders, left unavailable",
]


class Refused(Exception):
    """The run was not allowed to start."""


class Stop(Exception):
    """A stop condition from the plan was met."""


@dataclass(slots=True)
class Config:
    phase: str  # "A" or "B"
    raw_dir: Path
    out_dir: Path
    confirmed: bool
    key: str = ""
    secret: str = ""
    hosts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOSTS))
    max_requests: int = MAX_REQUESTS
    delay_s: float = MIN_DELAY_S
    symbol: str = "BTCIDR"


@dataclass(slots=True)
class Call:
    id: str
    at: str
    host: str
    path: str
    params: dict[str, str]
    status: int | None
    ok: bool
    note: str
    body: Any  # redacted, or shape-only for a signed response


@dataclass(slots=True)
class Report:
    phase: str
    started_at: str
    calls: list[Call] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)
    stopped: str | None = None
    not_run: list[str] = field(default_factory=list)


def _inside_a_repository(path: Path) -> bool:
    for parent in [path.resolve(), *path.resolve().parents]:
        if (parent / ".git").exists():
            return True
    return False


def check_config(cfg: Config) -> None:
    """Every refusal the plan requires, before a single request is made."""
    if not cfg.confirmed:
        raise Refused(f"this calls the real exchange; pass {CONFIRM_FLAG} to say you mean it")
    if cfg.phase not in {"A", "B"}:
        raise Refused("phase must be A (public, no key) or B (signed, read-only key)")
    if cfg.max_requests > MAX_REQUESTS or cfg.delay_s < MIN_DELAY_S:
        raise Refused(f"at most {MAX_REQUESTS} requests and at least {MIN_DELAY_S} s between them")
    for name, path in (("raw", cfg.raw_dir), ("output", cfg.out_dir)):
        if _inside_a_repository(path):
            raise Refused(
                f"the {name} directory is inside a git repository; use a scratch one outside it "
                "(raw responses must never be committed)"
            )
    if cfg.phase == "B" and not (cfg.key and cfg.secret):
        raise Refused(
            "phase B needs AIDSS_LIVECHECK_KEY and AIDSS_LIVECHECK_SECRET in your own terminal's "
            "terminal, a Read-only key made for this check"
        )
    if cfg.phase == "A" and (cfg.key or cfg.secret):
        raise Refused("phase A is public and must not be given a key; unset the key variables")


class LiveCheck:
    def __init__(
        self,
        cfg: Config,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        check_config(cfg)
        self.cfg, self._http, self._sleep, self._clock = cfg, http, sleep, clock
        self._secrets = [cfg.key, cfg.secret]
        self.report = Report(cfg.phase, datetime.fromtimestamp(clock(), UTC).isoformat())
        self._count = 0
        self._consecutive_5xx = 0
        self._raw: dict[str, Any] = {}
        cfg.raw_dir.mkdir(parents=True, exist_ok=True)
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- request

    def _sign(self, payload: str, *, wrong: bool = False) -> str:
        secret = "not-the-secret" if wrong else self.cfg.secret
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def get(
        self,
        call_id: str,
        host: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        signed: bool = False,
        mode: str = "valid",
        note: str = "",
    ) -> Call:
        """One GET. `mode` shapes the signature or timestamp of a signed call for B5 to B7."""
        if (host, path) not in ALLOWED:
            raise Refused(f"{host} {path} is not in the live verification plan")
        if signed and (host, path) not in SIGNED_PATHS:
            raise Refused(f"{path} is not a signed read-only endpoint of the plan")
        if self._count >= self.cfg.max_requests:
            raise Stop(f"request cap of {self.cfg.max_requests} reached")
        if self._count:
            self._sleep(self.cfg.delay_s)
        self._count += 1

        pairs = list((params or {}).items())
        headers = {"Accept": "application/json"}
        if signed:
            now_ms = int(self._clock() * 1000)
            if mode == "stale":
                pairs += [("timestamp", str(now_ms - 60_000)), ("recvWindow", "1000")]
            elif mode == "both":
                pairs += [("timestamp", str(now_ms)), ("nonce", str(now_ms))]
            else:
                pairs.append(("timestamp", str(now_ms)))
            query = urlencode(pairs)
            headers["X-APIKEY"] = self.cfg.key
            headers["Sign"] = self._sign(query, wrong=(mode == "wrong"))
        else:
            query = urlencode(pairs)
        url = f"{self.cfg.hosts[host]}{path}" + (f"?{query}" if query else "")

        status: int | None = None
        body: Any = None
        try:
            resp = self._http.get(url, headers=headers)
            status = resp.status_code
            try:
                body = resp.json()
            except ValueError:
                body = {"non_json_prefix": scrub(resp.text[:200], self._secrets)}
        except httpx.HTTPError as exc:
            body = {"transport_error": type(exc).__name__}
        self._raw[call_id] = body
        (self.cfg.raw_dir / f"{call_id}.json").write_text(
            json.dumps({"status": status, "body": body}, indent=2, default=str), encoding="utf-8"
        )

        shown = describe_shape(body) if signed else redact_public(body)
        call = Call(
            id=call_id,
            at=datetime.fromtimestamp(self._clock(), UTC).isoformat(),
            host=host,
            path=path,
            params={k: v for k, v in (params or {}).items()},
            status=status,
            ok=status is not None and 200 <= status < 300,
            note=note,
            body=shown,
        )
        self.report.calls.append(call)
        self._check_stop(call, body)
        return call

    def _check_stop(self, call: Call, raw_body: Any) -> None:
        code = raw_body.get("code") if isinstance(raw_body, dict) else None
        try:
            numeric = abs(int(code)) if code is not None else None
        except (TypeError, ValueError):
            numeric = None
        if numeric == 2015:
            raise Stop(f"{call.id}: access denied (-2015); not retried")
        if numeric == 1003 or call.status == 429:
            raise Stop(f"{call.id}: rate limit; stopping")
        if call.status is None or call.status >= 500:
            self._consecutive_5xx += 1
            if self._consecutive_5xx >= 2:
                raise Stop(f"{call.id}: two server or transport errors in a row")
        else:
            self._consecutive_5xx = 0

    # ------------------------------------------------------------------ phases

    def run(self) -> Report:
        try:
            self._phase_a() if self.cfg.phase == "A" else self._phase_b()
        except Stop as stop:
            self.report.stopped = str(stop)
        self.report.not_run = self._not_run()
        self._write()
        return self.report

    def _phase_a(self) -> None:
        sym = self.cfg.symbol
        end = int(self._clock())
        self.get("A1-server-time", "public", "/api/server_time")
        self.get("A2-pairs", "public", "/api/pairs")
        self.get("A3-price-increments", "public", "/api/price_increments")
        for tf in ("240", "1D"):
            self.get(
                f"A4-ohlc-{tf}",
                "public",
                "/tradingview/history_v2",
                {"symbol": sym, "tf": tf, "from": str(end - 14 * 86_400), "to": str(end)},
            )
        for spelling in (sym, sym.lower(), f"{sym[:-3].lower()}_idr"):
            self.get(
                f"A5-ticker-price-{spelling}", "api", "/api/v2/ticker/price", {"symbol": spelling}
            )
        self.get(
            "A5-ticker-price-multi", "api", "/api/v2/ticker/price", {"symbols": f"{sym},ETHIDR"}
        )
        self.get("A5-book-ticker", "api", "/api/v2/ticker/bookTicker", {"symbol": sym})
        self.get("A5-ticker-24hr", "api", "/api/v2/ticker/24hr", {"symbol": sym})
        self.get("A5-depth", "api", "/api/v2/depth", {"symbol": sym, "limit": "5"})
        self.get("A5-trades", "api", "/api/v2/trades", {"symbol": sym, "limit": "5"})
        self.get(
            "A6-host-api",
            "api",
            "/api/v2/ticker/price",
            {"symbol": sym},
            note="same call, host api",
        )
        self.get(
            "A6-host-tapi",
            "tapi",
            "/api/v2/ticker/price",
            {"symbol": sym},
            note="same call, host tapi",
        )
        self.get(
            "A7-error-invalid-symbol", "api", "/api/v2/ticker/price", {"symbol": "NOTAPAIRIDR"}
        )
        self.get("A7-error-invalid-limit", "api", "/api/v2/depth", {"symbol": sym, "limit": "-1"})
        self.get("A7-error-missing-param", "api", "/api/v2/depth", {})

    def _phase_b(self) -> None:
        sym = self.cfg.symbol
        acct = self.get("B1-account", "api", "/api/v2/account", signed=True)
        self._permission_stop(self._raw.get("B1-account"), acct)
        self.get("B2-open-orders", "api", "/api/v2/openOrders", signed=True)
        self.get("B2-open-orders-symbol", "api", "/api/v2/openOrders", {"symbol": sym}, signed=True)
        # Ids that cannot exist, so no real order is read or touched.
        self.get(
            "B3-order-by-id", "api", "/api/v2/order", {"symbol": sym, "orderId": "1"}, signed=True
        )
        self.get(
            "B3-order-by-client-id",
            "api",
            "/api/v2/order",
            {"symbol": sym, "origClientOrderId": "livecheck-nonexistent"},
            signed=True,
        )
        self.get("B4-histories", "api", "/api/v2/order/histories", {"symbol": sym}, signed=True)
        self.get("B4-histories-no-symbol", "api", "/api/v2/order/histories", signed=True)
        self.get("B4-my-trades", "api", "/api/v2/myTrades", {"symbol": sym}, signed=True)
        self.get("B4-my-trades-no-symbol", "api", "/api/v2/myTrades", signed=True)
        self.get("B5-wrong-signature", "api", "/api/v2/account", signed=True, mode="wrong")
        self.get("B6-stale-timestamp", "api", "/api/v2/account", signed=True, mode="stale")
        self.get("B7-timestamp-and-nonce", "api", "/api/v2/account", signed=True, mode="both")

    def _permission_stop(self, raw: Any, call: Call) -> None:
        """A Read-only key must report no trade and no withdrawal. Anything else stops the run."""
        if not isinstance(raw, dict):
            return
        flags = {k: raw.get(k) for k in ("canTrade", "canWithdraw", "canWithdrawFiat")}
        self.report.observations["B1_permission_flags"] = flags
        if raw.get("canWithdraw") or raw.get("canWithdrawFiat"):
            raise Stop("B1: the key can withdraw; revoke it now. Nothing further was called")
        if raw.get("canTrade"):
            raise Stop(
                "B1: the key can trade, so it is not Read-only; the plan allows Read-only only. "
                "Nothing further was called"
            )

    # ------------------------------------------------------------ observations

    def _observe(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        by_id = {c.id: c for c in self.report.calls}
        raw = self._raw

        def digits(v: Any) -> int | None:
            try:
                return len(str(int(v)))
            except (TypeError, ValueError):
                return None

        if "A1-server-time" in raw and isinstance(raw["A1-server-time"], dict):
            st = raw["A1-server-time"].get("server_time")
            obs["D11_server_time_digits"] = digits(st)  # 13 means milliseconds, 10 seconds
        pairs = raw.get("A2-pairs")
        if isinstance(pairs, list) and pairs and isinstance(pairs[0], dict):
            obs["D20_fee_fields_present_on"] = sum(
                1 for p in pairs if "trade_fee_percent_maker" in p
            )
            obs["D20_pairs_total"] = len(pairs)
            obs["D12_price_precision_type"] = type(pairs[0].get("price_precision")).__name__
            obs["pair_fields"] = sorted(pairs[0].keys())
        inc, prs = raw.get("A3-price-increments"), raw.get("A2-pairs")
        if isinstance(inc, dict) and isinstance(prs, list):
            table = inc.get("increments", inc)
            checked = agree = 0
            for p in prs:
                if isinstance(p, dict) and p.get("ticker_id") in table and "pricescale" in p:
                    checked += 1
                    agree += str(table[p["ticker_id"]]) == str(p["pricescale"])
            obs["A3_increment_vs_pricescale"] = {"checked": checked, "agree": agree}
        for tf in ("240", "1D"):
            rows = raw.get(f"A4-ohlc-{tf}")
            if isinstance(rows, list) and rows and isinstance(rows[-1], dict):
                t = rows[-1].get("Time")
                size = 14_400 if tf == "240" else 86_400
                try:
                    t_int = int(t)
                    obs[f"A4_{tf}"] = {
                        "time_digits": digits(t),
                        "last_candle_time_utc": datetime.fromtimestamp(t_int, UTC).isoformat()
                        if digits(t) == 10
                        else "not seconds",
                        "last_candle_mod_timeframe_seconds": t_int % size,
                        "candles_returned": len(rows),
                        "last_candle_still_open_when_fetched": t_int + size > int(self._clock()),
                        "numeric_types": {k: type(v).__name__ for k, v in rows[-1].items()},
                    }
                except (TypeError, ValueError):
                    obs[f"A4_{tf}"] = "Time was not an integer"
        spell = {
            i.split("A5-ticker-price-", 1)[1]: c.status
            for i, c in by_id.items()
            if i.startswith("A5-ticker-price-") and i != "A5-ticker-price-multi"
        }
        if spell:
            obs["D10_symbol_spellings_status"] = spell
        a, t = by_id.get("A6-host-api"), by_id.get("A6-host-tapi")
        if a and t:
            obs["D1_host_status"] = {"api": a.status, "tapi": t.status}
            obs["D1_same_shape"] = json.dumps(a.body, sort_keys=True) == json.dumps(
                t.body, sort_keys=True
            )
        errs = {}
        for cid in (
            "A7-error-invalid-symbol",
            "A7-error-invalid-limit",
            "A7-error-missing-param",
            "B3-order-by-id",
            "B3-order-by-client-id",
            "B5-wrong-signature",
            "B6-stale-timestamp",
            "B7-timestamp-and-nonce",
        ):
            r = raw.get(cid)
            if isinstance(r, dict) and ("code" in r or "msg" in r):
                errs[cid] = {
                    "http": by_id[cid].status,
                    "code": r.get("code"),
                    "code_is_negative": isinstance(r.get("code"), int) and r["code"] < 0,
                    "has_msg": "msg" in r,
                }
        if errs:
            obs["D17_error_shapes"] = errs
        for cid in ("B4-histories", "B4-my-trades"):
            r = raw.get(cid)
            rows = r.get("data") if isinstance(r, dict) else r
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                obs[f"{cid}_fields"] = sorted(rows[0].keys())  # names only, never values
                obs[f"{cid}_has_oriQty"] = "oriQty" in rows[0]
                obs[f"{cid}_has_origQty"] = "origQty" in rows[0]
        return obs

    def _not_run(self) -> list[str]:
        planned_a = {"A1", "A2", "A3", "A4", "A5", "A6", "A7"}
        planned_b = {"B1", "B2", "B3", "B4", "B5", "B6", "B7"}
        ran = {c.id.split("-")[0] for c in self.report.calls}
        missed = sorted((planned_a if self.cfg.phase == "A" else planned_b) - ran)
        notes = [f"{m}: not called (the run stopped or failed before it)" for m in missed]
        other = "B" if self.cfg.phase == "A" else "A"
        notes.append(f"phase {other}: not part of this run")
        return notes + NOT_RUN_ALWAYS

    # ------------------------------------------------------------------ output

    def _write(self) -> None:
        self.report.observations.update(self._observe())
        data = asdict(self.report)
        text = scrub(json.dumps(data, indent=2, default=str), self._secrets)
        (self.cfg.out_dir / f"report-phase-{self.cfg.phase}.json").write_text(
            text, encoding="utf-8"
        )
        (self.cfg.out_dir / f"record-draft-phase-{self.cfg.phase}.md").write_text(
            scrub(self._markdown(), self._secrets), encoding="utf-8"
        )

    def _markdown(self) -> str:
        r = self.report
        lines = [
            f"# T2-07 live read-only verification, phase {r.phase}: DRAFT",
            "",
            f"**Started (UTC):** {r.started_at}",
            f"**Stopped early:** {r.stopped or 'no'}",
            "",
            "Written by the script from what the exchange answered. A person must read it, "
            "decide what each observation means, and amend the integration documents through the "
            "deviation protocol. **Nothing here is a conclusion.**",
            "",
            "## Called",
            "",
            "| Id | Host | Path | Status | Note |",
            "|---|---|---|---|---|",
        ]
        for c in r.calls:
            lines.append(f"| {c.id} | {c.host} | {c.path} | {c.status} | {c.note} |")
        lines += [
            "",
            "## Observed",
            "",
            "```json",
            json.dumps(r.observations, indent=2, default=str),
            "```",
            "",
            "## Not called, so not verified",
            "",
        ]
        lines += [f"- {n}" for n in r.not_run]
        lines += [
            "",
            "## Next steps for the owner",
            "",
            "1. Revoke or rotate the key used for phase B.",
            "2. Delete the raw directory after the redacted fixtures are made.",
            "3. Review the redacted output, then copy what is safe into "
            "`tests/trader/fixtures/recorded/`.",
            "4. Correct the mock first, with a test that would have caught each difference, "
            "then amend "
            "`docs/06-INTEGRATIONS/03` to `11`.",
        ]
        return "\n".join(lines) + "\n"
