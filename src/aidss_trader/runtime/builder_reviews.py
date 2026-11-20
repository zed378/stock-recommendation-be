"""Exact-candle work and review gate. No model, HTTP or exchange access."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.connector.types import Candle as RuleCandle
from aidss_trader.db.models import BuilderReview, Candle
from aidss_trader.runtime.settings_store import (
    enabled_strategy_ids,
    get_allowlist,
    get_strategy_def,
    list_strategy_defs,
)
from aidss_trader.strategy.declarative import DeclarativeStrategy, candle_fingerprint
from aidss_trader.strategy.kinds import ParameterError, build_strategy
from aidss_trader.strategy.rules import StrictModel, evaluate_group


class KronosContext(StrictModel):
    provider: Literal["huggingface", "fixture"]
    model_id: str = Field(min_length=1, max_length=160)
    ticker: str
    exchange: Literal["INDODAX"]
    timeframe: Literal["4h", "1d"]
    as_of: datetime
    pred_len: int = Field(ge=1, le=30, strict=True)
    samples: int = Field(ge=1, le=10, strict=True)
    projected_return_pct: Decimal


class AiContext(StrictModel):
    score: int = Field(ge=0, le=100, strict=True)
    verdict: Literal["TAKE", "SKIP"]
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    reasons: list[Annotated[str, Field(max_length=200)]] = Field(max_length=3)
    risks: list[Annotated[str, Field(max_length=200)]] = Field(max_length=3)


class ReviewBody(StrictModel):
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    pair: str = Field(pattern=r"^[A-Z0-9]+IDR$", max_length=16)
    kronos: KronosContext | None = None
    ai: AiContext | None = None


def review_outcome(work: dict[str, Any], body: ReviewBody) -> tuple[str, str]:
    d = work["definition"]
    k = body.kronos
    if k is None:
        return "BLOCKED", "kronos_unavailable"
    if (
        k.provider != "huggingface"
        or k.ticker != work["pair"]
        or k.timeframe.upper() != work["timeframe"]
        or k.pred_len != d["forecast_bars"]
        or k.samples != d["forecast_samples"]
        or k.as_of.utcoffset() != timedelta(0)
        or k.as_of.isoformat() != work["candle_open"]
    ):
        return "BLOCKED", "kronos_source_mismatch"
    if k.projected_return_pct < Decimal(d["min_projected_return_pct"]):
        return "BLOCKED", "kronos_veto"
    if body.ai is None:
        return "BLOCKED", "ai_unavailable"
    if body.ai.verdict != "TAKE" or body.ai.score < d["ai_min_score"]:
        return "BLOCKED", "ai_veto"
    return "PASS", "required_reviews_passed"


def aware(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def review_identity(
    sid: str, version: str, pair: str, timeframe: str, at: datetime, fingerprint: str
) -> str:
    raw = f"{sid}|{version}|{pair}|{timeframe}|{aware(at).isoformat()}|{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def build_work(s: Session, sid: str, pair: str, now: datetime) -> dict[str, Any] | None:
    d = get_strategy_def(s, sid)
    allow = get_allowlist(s)
    if (
        d is None
        or d.kind != "signal_builder"
        or sid not in enabled_strategy_ids(s)
        or allow is None
        or pair not in allow.pairs
        or not pair.endswith("IDR")
    ):
        return None
    try:
        strategy = build_strategy(d.kind, d.params)
    except ParameterError:
        return None
    assert isinstance(strategy, DeclarativeStrategy)
    definition = strategy.definition
    rows = list(
        s.scalars(
            select(Candle)
            .where(Candle.pair == pair, Candle.timeframe == definition.timeframe)
            .order_by(Candle.open_time.desc())
            .limit(strategy.min_history())
        )
    )
    if len(rows) < strategy.min_history() or any(r.source != "indodax_ohlc" for r in rows):
        return None
    rows.reverse()
    if any(
        not all(v.is_finite() for v in (r.open, r.high, r.low, r.close, r.volume))
        or not 0 < r.low <= min(r.open, r.close) <= max(r.open, r.close) <= r.high
        or r.volume < 0
        for r in rows
    ):
        return None
    step = timedelta(hours=4) if definition.timeframe == "4H" else timedelta(days=1)
    if any(
        aware(b.open_time) - aware(a.open_time) != step
        for a, b in zip(rows, rows[1:], strict=False)
    ):
        return None
    close_at = aware(rows[-1].open_time) + step
    if close_at > now or now - close_at > timedelta(seconds=definition.max_data_age_seconds):
        return None
    candles = [
        RuleCandle(aware(r.open_time), r.open, r.high, r.low, r.close, r.volume) for r in rows
    ]
    if not evaluate_group(definition.entry, candles)["passed"]:
        return None
    fingerprint = candle_fingerprint(candles)
    identity = review_identity(
        sid, strategy.version_id(), pair, definition.timeframe, candles[-1].open_time, fingerprint
    )
    return {
        "identity": identity,
        "strategy_id": sid,
        "strategy_version": strategy.version_id(),
        "pair": pair,
        "timeframe": definition.timeframe,
        "candle_open": candles[-1].open_time.isoformat(),
        "data_hash": fingerprint,
        "definition": definition.model_dump(mode="json"),
        "candles": [
            {
                "timestamp": c.open_time.isoformat(),
                **{k: str(getattr(c, k)) for k in ("open", "high", "low", "close", "volume")},
            }
            for c in candles
        ],
    }


def pending_work(s: Session, now: datetime) -> list[dict[str, Any]]:
    allow = get_allowlist(s)
    if allow is None:
        return []
    jobs = []
    for definition in list_strategy_defs(s):
        if definition.kind != "signal_builder":
            continue
        for pair in allow.pairs:
            work = build_work(s, definition.id, pair, now)
            if (
                work
                and s.scalar(
                    select(BuilderReview.id).where(BuilderReview.identity == work["identity"])
                )
                is None
            ):
                jobs.append(work)
    return jobs


def review_is_current(s: Session, row: BuilderReview, now: datetime) -> bool:
    work = build_work(s, row.strategy_id, row.pair, now)
    if work is None or work["identity"] != row.identity:
        return False
    age = (now - aware(row.generated_at)).total_seconds()
    return 0 <= age <= work["definition"]["max_review_age_seconds"]


def entry_review(
    s: Session,
    strategy: DeclarativeStrategy,
    sid: str,
    pair: str,
    timeframe: str,
    candles: list[RuleCandle],
    now: datetime,
) -> tuple[str | None, str | None]:
    if timeframe != strategy.definition.timeframe or not pair.endswith("IDR"):
        return "builder_market_mismatch", None
    window = candles[-strategy.min_history() :]
    step = timedelta(hours=4) if timeframe == "4H" else timedelta(days=1)
    close_at = aware(window[-1].open_time) + step
    if close_at > now or now - close_at > timedelta(
        seconds=strategy.definition.max_data_age_seconds
    ):
        return "builder_stale_data", None
    identity = review_identity(
        sid,
        strategy.version_id(),
        pair,
        timeframe,
        window[-1].open_time,
        candle_fingerprint(window),
    )
    work = build_work(s, sid, pair, now)
    if work is None or work["identity"] != identity:
        return "builder_input_not_current", None
    row = s.scalar(select(BuilderReview).where(BuilderReview.identity == identity))
    if row is None:
        return "builder_review_pending", None
    age = (now - aware(row.generated_at)).total_seconds()
    if age < 0 or age > strategy.definition.max_review_age_seconds:
        return "builder_review_stale", None
    if row.outcome != "PASS":
        return f"builder_review_blocked:{row.reason}", None
    return None, str(row.id)
