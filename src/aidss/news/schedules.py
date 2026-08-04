"""Cron presets and schedule validation (Phase 7, Section 6.3.4).

Users pick a preset; power users write their own expression. Either way the
same guardrail applies before a schedule is stored: a minimum interval, so a
misplaced `* * * * *` cannot hammer a provider into rate-limiting the whole
platform.

Times are expressed in the exchange's timezone. A schedule described as "before
the market opens" that fires at 07:00 UTC would run at two in the afternoon
Jakarta time, which is not what anyone selecting it meant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import CroniterBadCronError, croniter

#: IDX trades on Jakarta time; presets are written and evaluated in it.
EXCHANGE_TIMEZONE = ZoneInfo("Asia/Jakarta")

#: Section 6.3.4's floor, restated in code. Five minutes is not a technical
#: limit - it is the point below which more requests stop buying more
#: information and start buying a rate-limit.
MIN_INTERVAL_SECONDS = 300

#: How many future firings are inspected when measuring an expression's
#: cadence. Three intervals is enough to catch a pattern that is dense in one
#: place and sparse elsewhere.
_INTERVAL_SAMPLES = 4


class InvalidScheduleError(ValueError):
    """The cron expression is malformed or fires too often."""


@dataclass(frozen=True, slots=True)
class CronPreset:
    key: str
    label: str
    expression: str
    suited_to: str


#: Section 6.3.4. `1-5` restricts to trading days, because issuer news
#: concentrates on them - a user who wants weekend macro coverage can write a
#: custom expression.
PRESETS: tuple[CronPreset, ...] = (
    CronPreset(
        key="every_15_minutes",
        label="Every 15 minutes",
        expression="*/15 * * * *",
        suited_to="active investors watching a primary holding",
    ),
    CronPreset(
        key="hourly",
        label="Every hour",
        expression="0 * * * *",
        suited_to="regular monitoring",
    ),
    CronPreset(
        key="twice_daily",
        label="Twice daily, around the open and close",
        expression="0 8,15 * * 1-5",
        suited_to="a summary before and after the trading session",
    ),
    CronPreset(
        key="daily_premarket",
        label="Daily, before the market opens",
        expression="0 7 * * 1-5",
        suited_to="medium and long horizon investors",
    ),
    CronPreset(
        key="weekly",
        label="Weekly, Monday morning",
        expression="0 7 * * 1",
        suited_to="passive watchlist entries",
    ),
)

PRESETS_BY_KEY: dict[str, CronPreset] = {p.key: p for p in PRESETS}


def validate_expression(expression: str, *, min_interval: int = MIN_INTERVAL_SECONDS) -> str:
    """Check syntax and cadence, returning the normalised expression.

    Cadence is measured from actual consecutive firings rather than parsed out
    of the expression: `*/1 * * * *` and `0-59 * * * *` fire identically and
    look nothing alike.
    """
    expression = expression.strip()
    if not expression:
        raise InvalidScheduleError("a cron expression is required")

    reference = datetime(2025, 1, 6, 0, 0, tzinfo=EXCHANGE_TIMEZONE)
    try:
        iterator = croniter(expression, reference)
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise InvalidScheduleError(f"invalid cron expression: {exc}") from exc

    previous = iterator.get_next(datetime)
    for _ in range(_INTERVAL_SAMPLES):
        following = iterator.get_next(datetime)
        interval = (following - previous).total_seconds()
        if interval < min_interval:
            raise InvalidScheduleError(
                f"this schedule fires every {int(interval)}s. The minimum is "
                f"{min_interval}s - below that, extra requests buy rate-limiting "
                "rather than extra information."
            )
        previous = following

    return expression


def resolve(preset_key: str | None, expression: str | None) -> tuple[str, str | None]:
    """Turn a preset key or a custom expression into a validated pair."""
    if preset_key:
        preset = PRESETS_BY_KEY.get(preset_key)
        if preset is None:
            raise InvalidScheduleError(
                f"unknown preset {preset_key!r}; available: {sorted(PRESETS_BY_KEY)}"
            )
        return validate_expression(preset.expression), preset.label

    if not expression:
        raise InvalidScheduleError("either a preset or a cron expression is required")
    return validate_expression(expression), None


def next_run_at(expression: str, *, after: datetime | None = None) -> datetime:
    """The next firing, in UTC.

    Evaluated in exchange time and converted, so "07:00 on weekdays" means
    07:00 in Jakarta regardless of where the server happens to run.
    """
    reference = (after or datetime.now(UTC)).astimezone(EXCHANGE_TIMEZONE)
    return croniter(expression, reference).get_next(datetime).astimezone(UTC)
