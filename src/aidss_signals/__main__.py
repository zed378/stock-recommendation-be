"""`python -m aidss_signals once` runs a single pass (SHADOW unless PUBLISH is confirmed and a
receiver is connected); `serve` runs the Socket.IO server and a pass after every daily close."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from aidss_signals.config import ConfigError, load_config
from aidss_signals.market import MarketData
from aidss_signals.worker import State, run_pass

logger = logging.getLogger("aidss_signals")
PASS_DELAY = timedelta(
    minutes=5
)  # after the 00:00 UTC close, when the exchange has settled the candle


def _recorder(path):
    def record(entry: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    return record


def _reviewer():
    from aidss.db import get_sessionmaker
    from aidss.llm import build_gateway
    from aidss_signals.ai_review import gateway_reviewer

    with get_sessionmaker()() as session:
        return gateway_reviewer(build_gateway(session))


def _next_pass(now: datetime) -> datetime:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0) + PASS_DELAY
    return today if today > now else today + timedelta(days=1)


async def _serve_db(env) -> None:
    """Database mode: the owner's settings come from the operator screen (ADR-066)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from aidss_signals.runner import poll_h4, poll_once
    from aidss_signals.store import SignalStore

    url = env["AIDSS_SIGNALS_DATABASE_URL"]
    store = SignalStore(
        sessionmaker(create_engine(url, pool_pre_ping=True), expire_on_commit=False)
    )
    token = env.get("AIDSS_SIGNALS_CLIENT_TOKEN", "").strip()
    port = int(env.get("AIDSS_SIGNALS_PORT", "0") or 0)
    host = env.get("AIDSS_SIGNALS_HOST", "").strip() or "127.0.0.1"
    hub = None
    if len(token) >= 16 and port > 0:
        import uvicorn

        from aidss_signals.server import SignalHub

        hub = SignalHub(token)
        hub.on_ack = store.save_ack
        asyncio.create_task(
            uvicorn.Server(
                uvicorn.Config(hub.app, host=host, port=port, log_level="warning")
            ).serve()
        )
        logger.info("receiver listening on %s:%s", host, port)
    loop = asyncio.get_running_loop()
    log = lambda lvl, msg: logger.log(getattr(logging, lvl, 20), msg)  # noqa: E731

    def publish(signal: dict[str, Any]) -> None:
        if hub is not None:
            asyncio.run_coroutine_threadsafe(hub.publish(signal), loop).result(timeout=15)

    poll_s = int(os.environ.get("AIDSS_SIGNALS_POLL_SECONDS", "30") or 30)
    while True:
        try:
            report = await asyncio.to_thread(
                poll_once,
                store,
                lambda cfg: MarketData(cfg.klines_base),
                _reviewer,
                publish,
                dict(env),
                datetime.now(UTC),
                log,
                hub is not None,
            )
            if report is not None:
                logger.info("pass done: %s", report.outcomes)
            h4_report = await asyncio.to_thread(
                poll_h4,
                store,
                lambda cfg: MarketData(cfg.klines_base),
                publish,
                dict(env),
                datetime.now(UTC),
                log,
                hub is not None,
            )
            if h4_report is not None:
                logger.info("4h pass done: %s", h4_report.outcomes)
        except Exception:  # noqa: BLE001 - the loop must survive a bad poll
            logger.exception("poll failed")
        await asyncio.sleep(max(5, poll_s))


async def _serve(cfg) -> None:
    import uvicorn

    from aidss_signals.server import SignalHub

    hub = SignalHub(cfg.client_token, cfg.ack_log_path) if cfg.mode == "PUBLISH" else None
    server = None
    if hub is not None:
        server = uvicorn.Server(
            uvicorn.Config(hub.app, host=cfg.host, port=cfg.port, log_level="warning")
        )
        asyncio.create_task(server.serve())
    market = MarketData(cfg.klines_base)
    state = State(cfg.state_path)
    loop = asyncio.get_running_loop()
    while True:

        def publish(signal: dict[str, Any]) -> None:
            if hub is not None:
                asyncio.run_coroutine_threadsafe(hub.publish(signal), loop).result(timeout=15)

        report = await asyncio.to_thread(
            run_pass,
            cfg,
            market,
            _reviewer(),
            publish,
            datetime.now(UTC),
            state,
            _recorder(cfg.decision_log_path),
            lambda lvl, msg: logger.log(getattr(logging, lvl, 20), msg),
        )
        logger.info("pass done: %s", {k: v for k, v in report.outcomes.items()})
        wait = (_next_pass(datetime.now(UTC)) - datetime.now(UTC)).total_seconds()
        await asyncio.sleep(max(60.0, wait))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import os

    command = argv[1] if len(argv) > 1 else "once"
    if command == "serve" and os.environ.get("AIDSS_SIGNALS_DATABASE_URL"):
        asyncio.run(_serve_db(os.environ))
        return 0
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"aidss_signals: not started: {exc}", file=sys.stderr)
        return 2
    if cfg is None:
        print("aidss_signals: AIDSS_SIGNALS_ENABLED is not true; nothing to do")
        return 0
    for note in cfg.notes:
        logger.warning(note)
    if command == "serve":
        asyncio.run(_serve(cfg))
        return 0
    if command == "once":
        market = MarketData(cfg.klines_base)
        report = run_pass(
            cfg,
            market,
            _reviewer(),
            lambda s: logger.info("SHADOW only: %s", s["id"]),
            datetime.now(UTC),
            State(cfg.state_path),
            _recorder(cfg.decision_log_path),
            lambda lvl, msg: logger.log(getattr(logging, lvl, 20), msg),
        )
        print(
            json.dumps(
                {"universe": report.universe, "outcomes": report.outcomes, "errors": report.errors},
                indent=2,
            )
        )
        return 0
    print("usage: python -m aidss_signals [once|serve]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
