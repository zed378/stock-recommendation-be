"""Summary numbers over the 4-hour signals' simulated outcomes (ADR-067).

Everything here describes a simulation from public candles, never fills. The point of the module is
to keep the numbers honest: a mean with its standard error, no win rate without a count, and a
score-versus-outcome correlation that is withheld until there is enough data to mean something.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

#: Below this many closed signals a correlation is noise; the API says so instead of printing it.
MIN_FOR_CORRELATION = 30
SCORE_BUCKETS = ((0, 59), (60, 79), (80, 100))


@dataclass(frozen=True, slots=True)
class Row:
    strategy: str
    side: str
    score: int
    state: str
    outcome: str | None
    tp_hits: int
    net_r: float | None


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation; None when it is undefined (fewer than 3 points or a constant series)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / (sx * sy)


def _group(rows: Iterable[Row]) -> dict[str, Any]:
    closed = [r for r in rows if r.state == "CLOSED" and r.net_r is not None]
    n = len(closed)
    out: dict[str, Any] = {"closed": n, "wins": 0, "win_rate": None, "tp1_rate": None}
    out.update({"mean_net_r": None, "stderr_net_r": None, "sum_net_r": None})
    if n == 0:
        return out
    nets = [float(r.net_r) for r in closed if r.net_r is not None]
    mean = sum(nets) / n
    out["wins"] = sum(1 for v in nets if v > 0)
    out["win_rate"] = out["wins"] / n
    out["tp1_rate"] = sum(1 for r in closed if r.tp_hits >= 1) / n
    out["mean_net_r"] = mean
    out["sum_net_r"] = sum(nets)
    if n >= 2:
        var = sum((v - mean) ** 2 for v in nets) / (n - 1)
        out["stderr_net_r"] = math.sqrt(var / n)
    return out


def summarize(rows: Sequence[Row]) -> dict[str, Any]:
    states: dict[str, int] = {}
    for r in rows:
        states[r.state] = states.get(r.state, 0) + 1
    by_strategy = {
        s: _group(r for r in rows if r.strategy == s) for s in sorted({r.strategy for r in rows})
    }
    by_side = {s: _group(r for r in rows if r.side == s) for s in sorted({r.side for r in rows})}
    by_score = {
        f"{lo}-{hi}": _group(r for r in rows if lo <= r.score <= hi) for lo, hi in SCORE_BUCKETS
    }
    closed = [r for r in rows if r.state == "CLOSED" and r.net_r is not None]
    corr = None
    if len(closed) >= MIN_FOR_CORRELATION:
        corr = spearman([float(r.score) for r in closed], [float(r.net_r or 0) for r in closed])
    outcomes: dict[str, int] = {}
    for r in rows:
        if r.outcome:
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    return {
        "total": len(rows),
        "states": states,
        "outcomes": outcomes,
        "overall": _group(rows),
        "by_strategy": by_strategy,
        "by_side": by_side,
        "by_score": by_score,
        "score_correlation": corr,
        "correlation_min_closed": MIN_FOR_CORRELATION,
        "simulated": True,
    }
