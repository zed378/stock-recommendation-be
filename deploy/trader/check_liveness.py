#!/usr/bin/env python3
"""Out-of-process host liveness monitor for AIDSS Trader (T6-04, ADR-039, ADR-043).

Runs on the deployment host outside the Trader container. Connects to PostgreSQL
with the read-only role ``trader_monitor`` (which has ``SELECT ON trading.lease``
only) and sends a ``CRITICAL`` alert **directly to Telegram** when the Trader's
heartbeat is missing or older than ``max_age_s`` (15 s by default, matching the
ADR-043 lease TTL).

Security rules enforced by this script:
- No credentials or tokens exist in the repository.
- The Telegram bot token and chat ID are read from a root-only file on the host
  (default ``/root/.aidss-monitor-telegram.env``).
- Neither the bot token, the chat ID, nor the database password is ever written
  to stdout, stderr, or exception messages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

DEFAULT_LEASE_NAME = "trader"
DEFAULT_MAX_AGE_S = 15.0
DEFAULT_TOKEN_FILE = "/root/.aidss-monitor-telegram.env"
DEFAULT_TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_COOLDOWN_S = 300.0

_REDACT_PATTERNS = (
    re.compile(r"bot[0-9]{5,}:[A-Za-z0-9_-]{10,}"),
    re.compile(r"://[^:@/\s]+:[^@/\s]+@"),
)


def _redact(msg: str, secrets: tuple[str, ...] = ()) -> str:
    out = msg
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "[REDACTED]")
    for pat in _REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    api_base: str = DEFAULT_TELEGRAM_API_BASE


@dataclass(frozen=True, slots=True)
class LivenessStatus:
    ok: bool
    reason: str
    holder: str | None
    heartbeat_at: datetime | None
    age_s: float | None
    alert_sent: bool


def load_telegram_config(
    path: str | Path,
    *,
    require_secure_permissions: bool = True,
) -> TelegramConfig:
    """Read TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from a host env file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise RuntimeError(f"Telegram token file not found: {file_path}")

    if require_secure_permissions and os.name == "posix":
        mode = stat.S_IMODE(file_path.stat().st_mode)
        if mode & 0o077:
            raise RuntimeError(
                f"Telegram token file {file_path} has group/other permissions "
                f"({oct(mode)}); expected 0600 or 0400"
            )

    values: dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip("'").strip('"')

    bot_token = values.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = values.get("TELEGRAM_CHAT_ID", "")
    api_base = values.get("TELEGRAM_API_BASE", DEFAULT_TELEGRAM_API_BASE).rstrip("/")
    if not bot_token or not chat_id:
        raise RuntimeError(
            f"Telegram token file {file_path} must define non-empty "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )
    return TelegramConfig(bot_token=bot_token, chat_id=chat_id, api_base=api_base)


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
    if isinstance(val, str):
        parsed = datetime.fromisoformat(val)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Unsupported heartbeat_at type: {type(val).__name__}")


def read_lease_heartbeat(
    conn: Connection,
    *,
    lease_name: str = DEFAULT_LEASE_NAME,
) -> tuple[str, datetime] | None:
    """Return ``(holder, heartbeat_at)`` from ``trading.lease``, or ``None`` if absent."""
    dialect = conn.dialect.name
    table = "trading.lease" if dialect == "postgresql" else "lease"
    row = conn.execute(
        text(f"SELECT holder, heartbeat_at FROM {table} WHERE name = :name"),
        {"name": lease_name},
    ).first()
    if row is None:
        return None
    return str(row[0]), _parse_dt(row[1])


def send_telegram_alert(
    cfg: TelegramConfig,
    message: str,
    *,
    timeout_s: float = 5.0,
) -> None:
    """POST ``message`` directly to Telegram without passing through the Trader."""
    url = f"{cfg.api_base}/bot{cfg.bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": cfg.chat_id,
            "text": _redact(message, (cfg.bot_token, cfg.chat_id)),
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            if status < 200 or status >= 300:
                raise RuntimeError(f"Telegram HTTP status {status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram HTTP error {exc.code}") from None
    except Exception as exc:
        safe_err = _redact(str(exc), (cfg.bot_token, cfg.chat_id))
        raise RuntimeError(f"Telegram delivery failed: {safe_err}") from None


def _should_send_alert(
    state_file: Path | None,
    *,
    now: datetime,
    cooldown_s: float,
) -> bool:
    if state_file is None or not state_file.is_file():
        return True
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        last_sent = _parse_dt(data["last_alert_at"])
        return (now - last_sent).total_seconds() >= cooldown_s
    except Exception:
        return True


def _write_state(state_file: Path | None, *, now: datetime, ok: bool) -> None:
    if state_file is None:
        return
    if ok:
        if state_file.is_file():
            state_file.unlink(missing_ok=True)
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"last_alert_at": now.isoformat(), "ok": False}),
        encoding="utf-8",
    )


def check_liveness(
    engine_or_conn: Engine | Connection,
    telegram: TelegramConfig,
    *,
    now: datetime | None = None,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    lease_name: str = DEFAULT_LEASE_NAME,
    state_file: Path | None = None,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
) -> LivenessStatus:
    """Check ``trading.lease`` and send a direct Telegram alert if missing or stale."""
    at = now or datetime.now(UTC)
    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            lease = read_lease_heartbeat(conn, lease_name=lease_name)
    else:
        lease = read_lease_heartbeat(engine_or_conn, lease_name=lease_name)

    if lease is None:
        reason = f"missing lease row '{lease_name}'"
        holder = None
        heartbeat_at = None
        age_s = None
        stale = True
    else:
        holder, heartbeat_at = lease
        age_s = round((at - heartbeat_at).total_seconds(), 3)
        stale = age_s > max_age_s
        reason = "ok" if not stale else f"heartbeat stale ({age_s:.1f}s > {max_age_s:.1f}s)"

    if not stale:
        _write_state(state_file, now=at, ok=True)
        return LivenessStatus(
            ok=True,
            reason=reason,
            holder=holder,
            heartbeat_at=heartbeat_at,
            age_s=age_s,
            alert_sent=False,
        )

    alert_sent = False
    if _should_send_alert(state_file, now=at, cooldown_s=cooldown_s):
        msg = (
            f"[CRITICAL] AIDSS Trader liveness check failed: {reason} "
            f"(lease='{lease_name}', holder='{holder or 'none'}'). "
            "Bot-side stop-loss monitoring (ADR-007) is inactive while the Trader is down. "
            "Follow Runbook R1 immediately."
        )
        send_telegram_alert(telegram, msg)
        _write_state(state_file, now=at, ok=False)
        alert_sent = True

    return LivenessStatus(
        ok=False,
        reason=reason,
        holder=holder,
        heartbeat_at=heartbeat_at,
        age_s=age_s,
        alert_sent=alert_sent,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Out-of-process AIDSS Trader heartbeat check (ADR-039)."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("AIDSS_MONITOR_DATABASE_URL", ""),
        help="PostgreSQL URL for role trader_monitor (default: $AIDSS_MONITOR_DATABASE_URL)",
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("AIDSS_MONITOR_TELEGRAM_FILE", DEFAULT_TOKEN_FILE),
        help="Root-only file with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
    )
    parser.add_argument(
        "--max-age-s",
        type=float,
        default=float(os.environ.get("AIDSS_MONITOR_MAX_AGE_S", str(DEFAULT_MAX_AGE_S))),
        help="Maximum heartbeat age in seconds before alerting (default: 15, ADR-043)",
    )
    parser.add_argument(
        "--lease-name",
        default=DEFAULT_LEASE_NAME,
        help="Lease row name in trading.lease (default: trader)",
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get("AIDSS_MONITOR_STATE_FILE", ""),
        help="Optional file recording last alert timestamp for cooldown",
    )
    parser.add_argument(
        "--cooldown-s",
        type=float,
        default=DEFAULT_COOLDOWN_S,
        help="Seconds between repeated alerts when --state-file is set (default: 300)",
    )
    parser.add_argument(
        "--allow-insecure-permissions",
        action="store_true",
        help="Skip POSIX 0600/0400 permission check on --token-file (for tests only)",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        sys.stderr.write("error: --database-url or AIDSS_MONITOR_DATABASE_URL is required\n")
        return 2

    try:
        tg = load_telegram_config(
            args.token_file,
            require_secure_permissions=not args.allow_insecure_permissions,
        )
    except Exception as exc:
        sys.stderr.write(f"error: {_redact(str(exc))}\n")
        return 2

    secrets = (tg.bot_token, tg.chat_id, args.database_url)
    state_path = Path(args.state_file) if args.state_file else None
    try:
        engine = create_engine(args.database_url)
        try:
            status = check_liveness(
                engine,
                tg,
                max_age_s=args.max_age_s,
                lease_name=args.lease_name,
                state_file=state_path,
                cooldown_s=args.cooldown_s,
            )
        finally:
            engine.dispose()
    except Exception as exc:
        # If the database itself is unreachable, attempt to alert Telegram directly.
        err_summary = _redact(str(exc), secrets)
        try:
            send_telegram_alert(
                tg,
                "[CRITICAL] AIDSS Trader liveness monitor could not query "
                f"trading.lease: {err_summary}. Follow Runbook R1.",
            )
        except Exception as tg_exc:
            sys.stderr.write(f"error: {_redact(str(tg_exc), secrets)}\n")
        sys.stderr.write(f"error: {err_summary}\n")
        return 1

    if status.ok:
        sys.stdout.write(
            f"ok: lease={args.lease_name} holder={status.holder} age_s={status.age_s}\n"
        )
        return 0

    sys.stderr.write(
        f"stale: lease={args.lease_name} reason={status.reason} alert_sent={status.alert_sent}\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
