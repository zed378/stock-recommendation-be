"""Indodax context worker: public candles in, model reviews out, no exchange client.

Requires AIDSS_BUILDER_TRADER_URL and AIDSS_BUILDER_TRADER_TOKEN. The latter is
an operator credential with CONFIGURE_STRATEGY; never put it into a definition.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from aidss.forecasting.service import KronosForecaster
from aidss_signals.ai_review import Reviewer
from aidss_signals.builder import BuilderConfig, BuilderInput, Forecast, decide, kronos_adapter


def evaluate_work(
    work: dict[str, Any], forecast: Forecast, review: Reviewer, now: datetime
) -> dict[str, Any]:
    definition = work["definition"]
    cfg = BuilderConfig.model_validate(
        {
            "name": work["strategy_id"],
            "symbol": work["pair"],
            "exchange": "INDODAX",
            "timeframe": work["timeframe"].lower(),
            **{
                k: definition[k]
                for k in (
                    "entry",
                    "exit",
                    "max_data_age_seconds",
                    "forecast_bars",
                    "forecast_samples",
                    "min_projected_return_pct",
                    "ai_min_score",
                )
            },
        }
    )
    data = BuilderInput.model_validate({"long": False, "candles": work["candles"]})
    decision = decide(cfg, data, now, forecast, review)
    # Minimize the wire evidence: projected prices and model prose cannot become
    # order fields. The API independently derives the typed PASS/BLOCKED outcome.
    keys = (
        "provider",
        "model_id",
        "ticker",
        "exchange",
        "timeframe",
        "as_of",
        "pred_len",
        "samples",
        "projected_return_pct",
    )
    kronos = decision.get("kronos")
    return {
        "identity": work["identity"],
        "strategy_id": work["strategy_id"],
        "pair": work["pair"],
        "kronos": {k: kronos[k] for k in keys} if kronos else None,
        "ai": decision.get("ai"),
    }


def run_once(
    client: httpx.Client, forecast: Forecast, review: Reviewer, now: datetime | None = None
) -> int:
    response = client.get("/trader/v1/signal-builder/work")
    response.raise_for_status()
    completed = 0
    for work in response.json()["data"]:
        result = evaluate_work(work, forecast, review, now or datetime.now(UTC))
        response = client.post(
            "/trader/v1/signal-builder/reviews",
            json=result,
            headers={"Idempotency-Key": work["identity"]},
        )
        response.raise_for_status()
        completed += 1
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("once", "serve"))
    parser.add_argument("--poll-seconds", type=int)
    parser.add_argument("--models", action="store_true", help="Explicitly enable model calls")
    args = parser.parse_args()
    url = os.environ.get("AIDSS_BUILDER_TRADER_URL", "")
    token = os.environ.get("AIDSS_BUILDER_TRADER_TOKEN", "")
    if not url or not token or not args.models:
        parser.error("Trader URL, operator token and --models must be set explicitly")
    if args.mode == "serve" and (args.poll_seconds is None or args.poll_seconds <= 0):
        parser.error("serve requires a positive --poll-seconds chosen by the owner")
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1:")):
        parser.error("use HTTPS, or an explicit local loopback HTTP port")
    from aidss_signals.__main__ import _reviewer

    def review(dossier: dict[str, Any]) -> Any:
        return _reviewer()(dossier)

    forecast = kronos_adapter(KronosForecaster())
    with httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        follow_redirects=False,
    ) as client:
        while True:
            try:
                print(f"Indodax reviews recorded: {run_once(client, forecast, review)}", flush=True)
            except Exception as exc:
                # Never print a URL, token, response body or gateway exception text.
                print(f"Indodax review pass unavailable: {type(exc).__name__}", flush=True)
                if args.mode == "once":
                    raise SystemExit(1) from None
            if args.mode == "once":
                return
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
