"""Backtest (docs/05-MODULE-SPECIFICATIONS/06). It produces evidence, not reassurance.

Rules this engine enforces:

* **No look-ahead.** A decision at candle *t* is given only candles up to and
  including *t*. Orders it places can fill no earlier than *t+1*.
* **Closed candles only**, the same as live.
* Costs (maker, taker, tax, clearing) and slippage come from the configuration;
  they are the owner's numbers (OQ-5), so a backtest cannot run without them.
* Same sizing, same intent builder, same limits as live.

Candle-level approximations, stated so nobody mistakes them for fact: the best
bid used to price an entry is the candle's close (the real book is not in OHLCV);
an entry rests for one candle and is then abandoned; if the stop is hit in the
same candle an entry fills, the stop is assumed hit (the intrabar order is
unknowable), which is the pessimistic choice; a stop exits at the worse of the
candle's open (a gap) and the stop price, plus slippage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.config.limits import RiskLimits
from aidss_trader.connector.types import Candle
from aidss_trader.db.models import BacktestRunRow
from aidss_trader.intents.builder import build_entry_intent
from aidss_trader.ledger.position import Position, apply_fill
from aidss_trader.market_data.pairs import PairRules
from aidss_trader.paper.executor import PaperConfig, PaperExecutor
from aidss_trader.strategy.base import PositionState, SignalKind, Strategy

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    strategy: Strategy
    limits: RiskLimits
    rules: PairRules
    paper: PaperConfig
    start_equity_idr: Decimal
    pair: str


@dataclass(frozen=True, slots=True)
class Trade:
    entry_time: datetime
    exit_time: datetime
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    pnl_net: Decimal
    exit_reason: str
    fees: Decimal = ZERO  # entry and exit costs together; `pnl_net` is already after them


@dataclass(slots=True)
class BacktestResult:
    origin: str = "BACKTEST"  # never shown or summed as live
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[Decimal] = field(default_factory=list)
    final_equity: Decimal = ZERO
    open_position: Position = field(default_factory=Position)
    metrics: dict[str, Decimal | int] = field(default_factory=dict)
    data_fingerprint: str = ""
    candles_used: int = 0


def fingerprint(candles: Sequence[Candle], config: BacktestConfig) -> str:
    """A reproducibility handle: the same data and parameters give the same value."""
    blob = json.dumps(
        {
            "candles": [
                [
                    c.open_time.isoformat(),
                    str(c.open),
                    str(c.high),
                    str(c.low),
                    str(c.close),
                    str(c.volume),
                ]
                for c in candles
            ],
            "version": config.strategy.version_id(),
            "slippage": str(config.paper.slippage_pct),
            "partial": str(config.paper.partial_fill_fraction),
            "costs": [str(v) for v in vars_of(config.paper.costs)],
            "equity": str(config.start_equity_idr),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def vars_of(costs: object) -> list[Decimal]:
    return [
        getattr(costs, n) for n in ("maker_fee_pct", "taker_fee_pct", "tax_pct", "clearing_pct")
    ]


def run_backtest(
    candles: Sequence[Candle],
    config: BacktestConfig,
    *,
    on_decision: Callable[[int, int], None] | None = None,
) -> BacktestResult:
    """`on_decision(index, history_length)` is called at every decision, for look-ahead tests."""
    strategy, paper = config.strategy, PaperExecutor(config.paper)
    result = BacktestResult(
        data_fingerprint=fingerprint(candles, config), candles_used=len(candles)
    )
    cash = config.start_equity_idr
    position = Position()
    stop: Decimal | None = None
    entry_time: datetime | None = None
    entry_cost = ZERO
    last_exit_at: datetime | None = None

    def close_position(when: datetime, price: Decimal, reason: str, cost: Decimal) -> None:
        nonlocal cash, position, stop, entry_time, last_exit_at, entry_cost
        qty = position.quantity
        new_pos, realised = apply_fill(position, "SELL", qty, price, cost)
        cash += qty * price - cost
        assert entry_time is not None
        result.trades.append(
            Trade(
                entry_time,
                when,
                qty,
                position.avg_cost,
                price,
                realised,
                reason,
                fees=entry_cost + cost,
            )
        )
        entry_cost = ZERO
        position, stop, entry_time, last_exit_at = new_pos, None, None, when

    for i, candle in enumerate(candles):
        # 1. Protective stop first, on the candle that has just happened. It uses only
        #    this candle, which is already complete at its own close.
        if position.quantity > 0 and stop is not None and candle.low <= stop:
            exit_price = paper.market("SELL", position.quantity, min(candle.open, stop))
            close_position(candle.open_time, exit_price.price, "stop", exit_price.cost)

        result.equity_curve.append(cash + position.quantity * candle.close)
        if i < strategy.min_history() - 1 or i == len(candles) - 1:
            continue  # no decision without history, and none on the last candle (no t+1 to fill)

        history = candles[: i + 1]
        if on_decision is not None:
            on_decision(i, len(history))
        signal = strategy.evaluate(
            history, PositionState(position.quantity > 0, None, last_exit_at)
        )
        nxt = candles[i + 1]

        if (
            signal.kind is SignalKind.NONE
            and position.quantity > 0
            and stop is not None
            and signal.stop_hint is not None
            and signal.stop_hint > stop
        ):
            stop = signal.stop_hint  # a trailing stop only ever rises (ADR-007)

        if signal.kind is SignalKind.EXIT and position.quantity > 0:
            fill = paper.market("SELL", position.quantity, nxt.open)
            close_position(nxt.open_time, fill.price, "signal", fill.cost)
        elif signal.kind is SignalKind.ENTRY and position.quantity == 0:
            equity = cash + position.quantity * candle.close
            built = build_entry_intent(
                signal,
                strategy_version=strategy.version_id(),
                pair=config.pair,
                candle_open=candle.open_time,
                equity_idr=equity,
                limits=config.limits,
                rules=config.rules,
                best_bid=candle.close,
                mode="PAPER",
            )
            if built.intent is None:
                continue
            intent = built.intent
            fill = paper.limit_against_candle("BUY", intent.entry_price, intent.quantity, nxt)
            if fill is None:
                continue  # one candle to fill, then abandoned
            position, _ = apply_fill(position, "BUY", fill.quantity, fill.price, fill.cost)
            cash -= fill.quantity * fill.price + fill.cost
            stop, entry_time, entry_cost = intent.stop_price, nxt.open_time, fill.cost
            if stop is not None and nxt.low <= stop:  # pessimistic: the stop is assumed hit
                exit_price = paper.market("SELL", position.quantity, min(nxt.open, stop))
                close_position(nxt.open_time, exit_price.price, "stop_same_candle", exit_price.cost)

    result.open_position = position
    result.final_equity = cash + position.quantity * (candles[-1].close if candles else ZERO)
    result.metrics = _metrics(result, config.start_equity_idr)
    return result


def _metrics(result: BacktestResult, start: Decimal) -> dict[str, Decimal | int]:
    wins = [t.pnl_net for t in result.trades if t.pnl_net > 0]
    losses = [t.pnl_net for t in result.trades if t.pnl_net <= 0]
    peak, max_dd = start, ZERO
    for eq in result.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100)
    gross_loss = -sum(losses, ZERO)
    count = len(result.trades)
    hold_hours = sum(
        (Decimal((t.exit_time - t.entry_time).total_seconds()) / 3600 for t in result.trades),
        ZERO,
    )
    return {
        "trades": count,
        "wins": len(wins),
        "win_rate_pct": (Decimal(len(wins)) / count * 100) if count else ZERO,
        "total_return_pct": (result.final_equity - start) / start * 100 if start else ZERO,
        "max_drawdown_pct": max_dd,
        "profit_factor": (sum(wins, ZERO) / gross_loss) if gross_loss > 0 else Decimal(-1),
        # Raw sums, so results of several pairs can be added up and the averages taken afterwards
        # (an average of per-pair averages would weight a one-trade pair like a fifty-trade one).
        "closed_pnl_idr": sum((t.pnl_net for t in result.trades), ZERO),
        "win_sum_idr": sum(wins, ZERO),
        "loss_sum_idr": sum(losses, ZERO),
        "hold_hours_total": hold_hours,
        "fees_idr": sum((t.fees for t in result.trades), ZERO),
    }


EXTRA_METRICS = ("closed_pnl_idr", "win_sum_idr", "loss_sum_idr", "hold_hours_total", "fees_idr")


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


def record_backtest(
    session: Session,
    result: BacktestResult,
    config: BacktestConfig,
    *,
    strategy_id: str | None = None,
    timeframe: str = "4H",
    by: str = "system",
    now: datetime | None = None,
) -> BacktestRunRow:
    """Persist a reproducible backtest run as promotion-gate evidence (labelled BACKTEST)."""
    at = now or datetime.now(UTC)
    sid = strategy_id or getattr(config.strategy, "strategy_id", "ema_adx")
    parameters = _json_safe(asdict(config.strategy.params))
    cost_model = _json_safe(asdict(config.paper))
    assert isinstance(parameters, dict)
    if config.strategy.name == "signal_builder":
        parameters["evaluation_scope"] = "RULES_ONLY_NO_MODEL_REVIEWS"
    assert isinstance(cost_model, dict)
    row = BacktestRunRow(
        origin=result.origin,
        strategy_id=sid,
        strategy_version=config.strategy.version_id(),
        pair=config.pair,
        timeframe=timeframe,
        candles_used=result.candles_used,
        trades=int(result.metrics.get("trades", 0)),
        wins=int(result.metrics.get("wins", 0)),
        win_rate_pct=Decimal(str(result.metrics.get("win_rate_pct", ZERO))),
        total_return_pct=Decimal(str(result.metrics.get("total_return_pct", ZERO))),
        max_drawdown_pct=Decimal(str(result.metrics.get("max_drawdown_pct", ZERO))),
        profit_factor=Decimal(str(result.metrics.get("profit_factor", Decimal(-1)))),
        start_equity_idr=config.start_equity_idr,
        final_equity_idr=result.final_equity,
        cost_model=cost_model,
        parameters=parameters,
        data_fingerprint=result.data_fingerprint,
        extra_metrics={k: str(result.metrics.get(k, ZERO)) for k in EXTRA_METRICS},
        ran_at=at,
        ran_by=by,
    )
    session.add(row)
    session.flush()
    AuditLogger(session).record(
        actor=by,
        action="backtest.recorded",
        subject_type="backtest_run",
        subject_id=str(row.id),
        after={
            "origin": row.origin,
            "strategy_id": row.strategy_id,
            "strategy_version": row.strategy_version,
            "pair": row.pair,
            "total_return_pct": str(row.total_return_pct),
            "trades": row.trades,
            "data_fingerprint": row.data_fingerprint,
        },
    )
    session.commit()
    return row


def latest_backtest_return_pct(
    session: Session, strategy_id: str, strategy_version: str
) -> Decimal | None:
    """Return the latest stored backtest total_return_pct for the given strategy & version."""
    row = session.scalar(
        select(BacktestRunRow)
        .where(
            BacktestRunRow.strategy_id == strategy_id,
            BacktestRunRow.strategy_version == strategy_version,
        )
        .order_by(BacktestRunRow.ran_at.desc())
        .limit(1)
    )
    return None if row is None else Decimal(str(row.total_return_pct))

