"""The signal the receiver understands. Field names follow the CryptoSpike client's own payload
(`id`, `symbol`, `side`, `entryPrice`, `tp1..tp3`, `sl`, `strategy`, `score`, `btcTrendBias`)."""

from __future__ import annotations

from typing import Any

from aidss_signals.ai_review import Verdict
from aidss_signals.screen import AssetScore

STRATEGY = "aidss-crypto-pick"


def build_signal(
    symbol: str, day: str, score: AssetScore, levels: dict[str, float], verdict: Verdict, bias: str
) -> dict[str, Any]:
    return {
        "id": f"aidss-{symbol}-{day}",
        "symbol": symbol,
        "side": "LONG",
        "entryPrice": levels["entry"],
        "sl": levels["stop"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],
        "strategy": STRATEGY,
        # The screen's own score as a percentage, so the client's minScore filter means "this share
        # of the named conditions". The AI's score travels beside it, it does not replace it.
        "score": int(round(score.ratio * 100)),
        "btcTrendBias": bias,
        "analytics": {
            "source": "aidss-signals",
            "as_of": day,
            "horizons": {
                h: {"met": score.met[h], "not_met": score.failed[h]} for h in score.horizons
            },
            "score_ratio": round(score.ratio, 3),
            "ai": verdict.as_dict(),
        },
    }
