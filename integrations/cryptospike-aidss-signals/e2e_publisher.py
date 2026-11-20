"""End to end, all local: the AIDSS signal worker publishes to the REAL CryptoSpike client.

    PYTHONPATH=src python integrations/cryptospike-aidss-signals/e2e_publisher.py

Starts the AIDSS signal server on 127.0.0.1:3099, waits for the client (see
`simulation/run-client-only.ts` in the sibling folder) to connect, runs one worker pass over
synthetic daily candles with a scripted AI, publishes what survives, and prints the outcome of every
coin and the receiver's acknowledgements. No exchange, no AI provider and no outside network.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import uvicorn

from aidss.domain.types import Candle
from aidss_signals.ai_review import AiUnavailable, Verdict
from aidss_signals.config import load_config
from aidss_signals.market import MarketData
from aidss_signals.server import SignalHub
from aidss_signals.worker import State, run_pass

TOKEN = "sim-aidss-signal-token-0001"
PORT = 3099
NOW = datetime.now(UTC).replace(hour=0, minute=10, second=0, microsecond=0)


def candles(n: int, drift: float, seed: int, start: float) -> list[Candle]:
    rng, price = random.Random(seed), start
    t0 = NOW.replace(minute=0) - timedelta(days=n)
    out = []
    for i in range(n):
        price *= 1 + drift + rng.uniform(-0.01, 0.01)
        out.append(
            Candle(
                t0 + timedelta(days=i),
                D(f"{price * 0.995:.6f}"),
                D(f"{price * 1.01:.6f}"),
                D(f"{price * 0.99:.6f}"),
                D(f"{price:.6f}"),
                D(str(1000 + rng.randint(0, 500))),
            )
        )
    return out


def rows(cs: list[Candle]) -> list[list[object]]:
    return [
        [
            int(c.timestamp.timestamp() * 1000),
            str(c.open),
            str(c.high),
            str(c.low),
            str(c.close),
            str(c.volume),
            int(c.timestamp.timestamp() * 1000) + 86_399_999,
        ]
        for c in cs
    ]


DATA = {
    "BTCUSDT": rows(candles(260, 0.006, 1, 60000)),
    "ETHUSDT": rows(candles(260, 0.006, 2, 3000)),  # strong: scored, AI takes it
    "SOLUSDT": rows(candles(260, -0.006, 3, 150)),  # weak: below the threshold
    "ADAUSDT": rows(candles(260, 0.006, 4, 0.5)),  # strong: scored, AI says SKIP
    "XRPUSDT": rows(candles(260, 0.006, 5, 0.6)),  # strong: scored, AI unreachable
}
VOLUMES = [{"symbol": s, "quoteVolume": "5000000000"} for s in DATA]


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/ticker/24hr":
        return httpx.Response(200, json=VOLUMES)
    return httpx.Response(200, json=DATA[request.url.params["symbol"]])


def review(dossier: dict) -> Verdict:
    symbol = dossier["symbol"]
    if symbol == "ETHUSDT":
        return Verdict(
            86,
            "TAKE",
            "HIGH",
            ("trend, ADX and DI agree", "above the 200-bar average"),
            ("extended",),
        )
    if symbol == "ADAUSDT":
        return Verdict(35, "SKIP", "MEDIUM", ("stop looks too tight for the volatility",), ())
    raise AiUnavailable("provider unreachable")


async def main() -> int:
    cfg = load_config(
        {
            "AIDSS_SIGNALS_ENABLED": "true",
            "AIDSS_SIGNALS_MODE": "PUBLISH",
            "AIDSS_SIGNALS_CONFIRM_PUBLISH": "yes",
            "AIDSS_SIGNALS_CLIENT_TOKEN": TOKEN,
            "AIDSS_SIGNALS_SYMBOLS": "ETHUSDT,SOLUSDT,ADAUSDT,XRPUSDT",
            "AIDSS_SIGNALS_TOP_N": "0",
            "AIDSS_SIGNALS_MIN_QUOTE_VOLUME_USDT": "1000000",
            "AIDSS_SIGNALS_HORIZONS": "14d,30d",
            "AIDSS_SIGNALS_MIN_SCORE_RATIO": "0.8",
            "AIDSS_SIGNALS_ATR_STOP_MULTIPLE": "2",
            "AIDSS_SIGNALS_TP_R1": "1.5",
            "AIDSS_SIGNALS_TP_R2": "2.5",
            "AIDSS_SIGNALS_TP_R3": "4",
            "AIDSS_SIGNALS_AI_MIN_SCORE": "70",
            "AIDSS_SIGNALS_AI_MAX_CALLS": "10",
        }
    )
    assert cfg is not None
    hub = SignalHub(TOKEN)
    server = uvicorn.Server(uvicorn.Config(hub.app, host="127.0.0.1", port=PORT, log_level="error"))
    task = asyncio.create_task(server.serve())
    print(
        f"AIDSS signal server listening on 127.0.0.1:{PORT}; waiting for the client to connect...",
        flush=True,
    )
    for _ in range(240):
        if hub.sio.manager.rooms.get("/", {}).get(None):
            break
        await asyncio.sleep(0.25)
    else:
        print("no client connected within 60 s")
        return 1
    print("client connected; running one worker pass", flush=True)
    market = MarketData(
        "https://synthetic",
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
    )
    loop = asyncio.get_running_loop()

    def publish(signal: dict) -> None:
        delivered = asyncio.run_coroutine_threadsafe(hub.publish(signal), loop).result(timeout=15)
        print(
            f"published {signal['id']} (score {signal['score']}, "
            f"ai {signal['analytics']['ai']['score']}) to {delivered} client(s)",
            flush=True,
        )

    report = await asyncio.to_thread(
        run_pass,
        cfg,
        market,
        review,
        publish,
        NOW,
        State(None),
        lambda e: None,
        lambda lvl, msg: print(f"  [{lvl}] {msg}", flush=True),
    )
    print("\noutcome per coin:")
    for symbol, outcome in sorted(report.outcomes.items()):
        print(f"  {symbol}: {outcome}")
    for _ in range(60):
        if any(a.get("stage") == "RESULT" for a in hub.acks):
            break
        await asyncio.sleep(0.25)
    print("\nacknowledgements from the receiver:")
    for ack in hub.acks:
        print("  " + json.dumps(ack))
    server.should_exit = True
    await task
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
