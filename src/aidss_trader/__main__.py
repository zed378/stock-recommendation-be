"""Entry points: `run`, `healthcheck`, `generate-master-key`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.audit import AuditChainBroken, record_head_anchor, verify_head_anchor
from aidss_trader.config import get_settings
from aidss_trader.credentials import (
    MasterKeyUnavailable,
    generate_master_key_file,
    load_master_key,
)
from aidss_trader.livecheck import CONFIRM_FLAG
from aidss_trader.runtime.assembly import build_api, build_runtime, serve_in_thread
from aidss_trader.service import heartbeat_age_s, run


def _live_check(args: argparse.Namespace) -> int:
    import os

    import httpx

    from aidss_trader.livecheck import Config, LiveCheck, Refused

    cfg = Config(
        phase=args.phase,
        raw_dir=args.raw_dir,
        out_dir=args.out,
        confirmed=args.confirmed,
        key=os.environ.get("AIDSS_LIVECHECK_KEY", ""),
        secret=os.environ.get("AIDSS_LIVECHECK_SECRET", ""),
        symbol=args.symbol,
    )
    try:
        with httpx.Client(timeout=15) as http:
            report = LiveCheck(cfg, http).run()
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"{len(report.calls)} calls made; stopped early: {report.stopped or 'no'}")
    print(f"report and record draft written to {cfg.out_dir}; raw responses are in {cfg.raw_dir}")
    print("next: revoke the key, review the redacted output, then delete the raw directory")
    return 1 if report.stopped else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aidss_trader")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("healthcheck")
    live = sub.add_parser(
        "live-check",
        help="owner-led, read-only check of the real exchange (T2-07); never run by an agent",
    )
    live.add_argument("--phase", choices=["A", "B"], required=True)
    live.add_argument("--raw-dir", type=Path, required=True, help="outside any git repository")
    live.add_argument("--out", type=Path, required=True, help="outside any git repository")
    live.add_argument(CONFIRM_FLAG, dest="confirmed", action="store_true")
    live.add_argument("--symbol", default="BTCIDR")
    gen = sub.add_parser("generate-master-key")
    gen.add_argument("--out", type=Path, required=True)
    anchor = sub.add_parser(
        "audit-anchor",
        help="record or verify the external audit-log head hash (T1-05)",
    )
    anchor.add_argument("--out", type=Path, required=True)
    anchor.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "generate-master-key":
        # Needs no database or settings: it must work on a fresh host.
        generate_master_key_file(args.out)
        print(f"wrote a new master key to {args.out}; keep it out of git and out of backups")
        return 0

    if args.command == "live-check":
        # Needs no database or settings. The key comes only from this terminal's environment.
        return _live_check(args)

    settings = get_settings()
    if args.command == "audit-anchor":
        return _audit_anchor(args, settings.database_url)
    if args.command == "healthcheck":
        # Healthy means a recent cycle completed. The cycle itself reports a lease
        # that is not held; the container stays up but the dashboard says so.
        age = heartbeat_age_s(settings.heartbeat_file)
        limit = settings.lease_heartbeat_s * 3
        return 0 if age is not None and age <= limit else 1

    logging.basicConfig(level=settings.log_level)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        fernet = load_master_key(settings.master_key_file)
    except MasterKeyUnavailable as exc:
        # The service still starts and says so; with no key it cannot read a credential.
        logging.getLogger("aidss_trader").error("master key unavailable: %s", exc)
        fernet = None
    runtime = build_runtime(settings, factory, fernet)
    app = build_api(settings, factory, runtime, fernet)
    if app is not None:
        serve_in_thread(app, settings.api_host, settings.api_port)
    run(settings, factory, runtime=runtime)
    return 0


def _audit_anchor(args: argparse.Namespace, database_url: str) -> int:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as session:
            try:
                result = (
                    verify_head_anchor(session, args.out)
                    if args.verify_only
                    else record_head_anchor(session, args.out)
                )
            except AuditChainBroken as exc:
                print(f"audit chain broken: {exc}", file=sys.stderr)
                return 2
        if result is None:
            print("audit log is empty")
            return 0
        seq, head_hash = result
        action = "verified" if args.verify_only else "anchored"
        print(f"{action} seq={seq} head_hash={head_hash} file={args.out}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
