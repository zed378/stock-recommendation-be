"""Entry points: `run`, `healthcheck`, `generate-master-key`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.config import get_settings
from aidss_trader.credentials import generate_master_key_file
from aidss_trader.service import heartbeat_age_s, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aidss_trader")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("healthcheck")
    gen = sub.add_parser("generate-master-key")
    gen.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "generate-master-key":
        # Needs no database or settings: it must work on a fresh host.
        generate_master_key_file(args.out)
        print(f"wrote a new master key to {args.out}; keep it out of git and out of backups")
        return 0

    settings = get_settings()
    if args.command == "healthcheck":
        # Healthy means a recent cycle completed. The cycle itself reports a lease
        # that is not held; the container stays up but the dashboard says so.
        age = heartbeat_age_s(settings.heartbeat_file)
        limit = settings.lease_heartbeat_s * 3
        return 0 if age is not None and age <= limit else 1

    logging.basicConfig(level=settings.log_level)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    run(settings, sessionmaker(engine, expire_on_commit=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
