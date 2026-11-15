"""Tests for the out-of-process host liveness monitor (T6-04, ADR-039, Acceptance A13).

Uses a local HTTP server as a fake Telegram receiver and SQLite for ``trading.lease``.
No real Telegram chat, database, or exchange is contacted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import Base
from aidss_trader.db.models import OrderRow, PositionStop
from aidss_trader.lease import LeaseHolder
from tests.trader.test_runtime_wiring import World, entered

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "deploy" / "trader" / "check_liveness.py"


def _load_liveness_module():
    spec = importlib.util.spec_from_file_location("check_liveness", _SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_liveness"] = mod
    spec.loader.exec_module(mod)
    return mod


liveness = _load_liveness_module()

FAKE_TOKEN = "123456789:AAFakeTelegramBotTokenForTestOnly00"
FAKE_CHAT_ID = "-100987654321"
T0 = datetime(2026, 11, 15, 2, 0, tzinfo=UTC)


class _FakeTelegramServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status_code: int = 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                body = json.loads(raw) if raw else {}
                outer.requests.append({"path": self.path, "body": body})
                self.send_response(outer.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def fake_telegram():
    srv = _FakeTelegramServer()
    try:
        yield srv
    finally:
        srv.close()


@pytest.fixture
def lease_engine():
    eng = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_fresh_heartbeat_sends_no_alert(lease_engine, fake_telegram) -> None:
    factory = sessionmaker(lease_engine, expire_on_commit=False)
    with factory() as s:
        assert LeaseHolder(holder="trader-1", ttl_s=15).acquire(s, now=T0)
        s.commit()

    tg = liveness.TelegramConfig(
        bot_token=FAKE_TOKEN,
        chat_id=FAKE_CHAT_ID,
        api_base=fake_telegram.api_base,
    )
    status = liveness.check_liveness(
        lease_engine,
        tg,
        now=T0 + timedelta(seconds=5),
        max_age_s=15.0,
    )
    assert status.ok is True
    assert status.alert_sent is False
    assert status.holder == "trader-1"
    assert status.age_s == 5.0
    assert fake_telegram.requests == []


def test_stale_or_missing_heartbeat_alerts_telegram_directly_with_cooldown(
    lease_engine, fake_telegram, tmp_path: Path
) -> None:
    tg = liveness.TelegramConfig(
        bot_token=FAKE_TOKEN,
        chat_id=FAKE_CHAT_ID,
        api_base=fake_telegram.api_base,
    )
    state_file = tmp_path / "liveness-state.json"

    # 1. Missing lease row alerts immediately.
    missing = liveness.check_liveness(
        lease_engine,
        tg,
        now=T0,
        max_age_s=15.0,
        state_file=state_file,
        cooldown_s=300.0,
    )
    assert missing.ok is False and missing.alert_sent is True
    assert len(fake_telegram.requests) == 1
    first_msg = fake_telegram.requests[0]["body"]["text"]
    assert "[CRITICAL]" in first_msg
    assert "missing lease row" in first_msg
    assert "ADR-007" in first_msg and "Runbook R1" in first_msg
    assert FAKE_TOKEN not in first_msg

    # 2. Second check within cooldown_s is suppressed.
    suppressed = liveness.check_liveness(
        lease_engine,
        tg,
        now=T0 + timedelta(seconds=60),
        max_age_s=15.0,
        state_file=state_file,
        cooldown_s=300.0,
    )
    assert suppressed.ok is False and suppressed.alert_sent is False
    assert len(fake_telegram.requests) == 1

    # 3. After cooldown_s elapses, re-alerts.
    realerted = liveness.check_liveness(
        lease_engine,
        tg,
        now=T0 + timedelta(seconds=305),
        max_age_s=15.0,
        state_file=state_file,
        cooldown_s=300.0,
    )
    assert realerted.ok is False and realerted.alert_sent is True
    assert len(fake_telegram.requests) == 2

    # 4. Once Trader renews heartbeat, state file is cleared.
    factory = sessionmaker(lease_engine, expire_on_commit=False)
    with factory() as s:
        assert LeaseHolder(holder="trader-1", ttl_s=15).acquire(
            s, now=T0 + timedelta(seconds=310)
        )
        s.commit()

    recovered = liveness.check_liveness(
        lease_engine,
        tg,
        now=T0 + timedelta(seconds=312),
        max_age_s=15.0,
        state_file=state_file,
        cooldown_s=300.0,
    )
    assert recovered.ok is True and recovered.alert_sent is False
    assert not state_file.exists()


def test_cli_main_reads_token_file_and_redacts_secrets_on_failure(
    fake_telegram, tmp_path: Path, capsys
) -> None:
    db_file = tmp_path / "monitor.sqlite"
    db_url = f"sqlite:///{db_file.as_posix()}"
    eng = create_engine(db_url).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(eng)
    eng.dispose()

    token_file = tmp_path / "telegram.env"
    token_file.write_text(
        f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\n"
        f"TELEGRAM_CHAT_ID={FAKE_CHAT_ID}\n"
        f"TELEGRAM_API_BASE={fake_telegram.api_base}\n",
        encoding="utf-8",
    )

    # Simulate Telegram HTTP 500 error and verify token is never printed to stderr/stdout.
    fake_telegram.status_code = 500
    rc = liveness.main(
        [
            "--database-url",
            db_url,
            "--token-file",
            str(token_file),
            "--allow-insecure-permissions",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out
    assert FAKE_TOKEN not in captured.err
    assert FAKE_CHAT_ID not in captured.out
    assert FAKE_CHAT_ID not in captured.err


def test_acceptance_a13_stop_trader_with_open_position_alerts_and_evaluates_stops_first_on_restart(
    fake_telegram,
) -> None:
    """Acceptance A13 (docs/11-TESTING-QUALITY/04):
    Stop the Trader with an open position -> the out-of-process check alerts;
    on restart stops are evaluated first.
    """
    w = World("AUTO")
    entered(w)
    w.cycle()

    # Trader holds an open BTCIDR position with an active bot-side stop and a fresh lease.
    stops = w.rows(PositionStop)
    assert len(stops) == 1
    stop_price = stops[0].stop_price

    with w.factory() as s:
        assert LeaseHolder(holder="trader-main", ttl_s=15).acquire(s, now=w.now())
        s.commit()

    # 1. Simulate the Trader stopping for 25 seconds (> 15 s lease TTL) while position is open.
    w.env.mock.advance(25_000)
    tg = liveness.TelegramConfig(
        bot_token=FAKE_TOKEN,
        chat_id=FAKE_CHAT_ID,
        api_base=fake_telegram.api_base,
    )
    status = liveness.check_liveness(
        w.engine,
        tg,
        now=w.now(),
        max_age_s=15.0,
    )
    assert status.ok is False and status.alert_sent is True
    assert len(fake_telegram.requests) == 1
    assert "heartbeat stale (25.0s > 15.0s)" in fake_telegram.requests[0]["body"]["text"]

    # 2. While the Trader was stopped, BTCIDR price crossed below the stop price.
    w.env.mock.prices["BTCIDR"] = str(int(stop_price) - 5_000_000)
    w.env.mock.market_fill_price = w.env.mock.prices["BTCIDR"]

    # 3. On restart (first cycle back), the Trader evaluates stops FIRST and sends the MARKET exit.
    w.runtime.cycle()
    stop_orders = [o for o in w.rows(OrderRow) if o.purpose == "STOP"]
    assert len(stop_orders) == 1
    assert stop_orders[0].type == "MARKET" and stop_orders[0].side == "SELL"
