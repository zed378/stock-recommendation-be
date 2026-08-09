"""Screens an investor writes themselves.

The built-in horizons answer questions somebody else chose. This lets a reader
state their own - "RSI under 35, volume at least twice its average, price
between 100 and 2000" - and run it over every issuer the scan covers.

Three things decide the whole design.

**The vocabulary is closed, and that is the security of it.** A field name is
looked up in a registry derived from the signal dataclass; an operator is
looked up in a table; a value is coerced to the field's declared type. Nothing
a caller sends ever reaches SQL as text. The alternative - letting a rule carry
a fragment of an expression - is an injection surface on a screen that reads
the whole database.

**Every number in the stored signals is a JSON *string*.** `_serialisable`
writes Decimals as `"9.5000"` so no precision is lost, which means a comparison
done the obvious way is lexical: `"9.5" > "10.0"` is true, and a filter for
"RSI below 10" would quietly return everything in the nineties. Every numeric
comparison here casts first. This is the single most dangerous detail in the
module, because getting it wrong produces a plausible list rather than an
error.

**A filter matching half the exchange is not a filter.** The platform already
learned that measuring a criterion against the real market is the only way to
know it discriminates - two built-in criteria were caught matching 44% and 36%.
A screen written by hand deserves the same feedback, so every run reports how
many issuers it considered alongside how many it matched.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, Select, and_, cast, select
from sqlalchemy.orm import Session

from aidss.db.models import AlertKind, MarketScanResult
from aidss.monitoring.signals import TechnicalSignals


class FieldType(StrEnum):
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    #: The matched-criteria list, which is a set rather than a scalar.
    CRITERIA = "criteria"


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    type: FieldType
    #: Where the value lives. JSON fields are read out of `signals`; column
    #: fields are real columns and need no extraction.
    in_signals: bool = True

    def as_payload(self) -> dict[str, Any]:
        return {"key": self.key, "type": self.type.value, "operators": OPERATORS_FOR[self.type]}


def _signal_fields() -> dict[str, Field]:
    """Every stored signal, typed from the dataclass annotation.

    Derived rather than listed. A hand-written copy goes out of date the first
    time somebody adds a signal, and the failure is a field that exists in the
    data and cannot be filtered on - invisible until a reader goes looking for
    it.
    """
    hints = typing.get_type_hints(TechnicalSignals)
    found: dict[str, Field] = {}
    for name in TechnicalSignals.__slots__:
        annotation = hints.get(name)
        text = str(annotation)
        if "bool" in text:
            kind = FieldType.BOOLEAN
        elif "date" in text and "datetime" not in text:
            kind = FieldType.DATE
        elif "Decimal" in text or "int" in text or "float" in text:
            kind = FieldType.NUMBER
        else:
            # An unrecognised type is left out rather than guessed at. Offered
            # as a number and compared as one, a field of some other shape
            # returns a wrong list rather than an error.
            continue
        found[name] = Field(key=name, type=kind)
    return found


#: Real columns worth filtering on, beside the JSON signals.
_COLUMN_FIELDS: dict[str, Field] = {
    "close": Field("close", FieldType.NUMBER, in_signals=False),
    "matched_count": Field("matched_count", FieldType.NUMBER, in_signals=False),
    "matched": Field("matched", FieldType.CRITERIA, in_signals=False),
}

FIELDS: dict[str, Field] = {**_signal_fields(), **_COLUMN_FIELDS}

OPERATORS_FOR: dict[FieldType, list[str]] = {
    FieldType.NUMBER: ["lt", "lte", "gt", "gte", "eq", "between"],
    FieldType.BOOLEAN: ["is"],
    FieldType.DATE: ["on_or_after", "on_or_before"],
    FieldType.CRITERIA: ["includes_any", "includes_all", "excludes"],
}


class InvalidRule(ValueError):
    """A rule the builder will not compile, with a reason meant for the author."""


@dataclass(frozen=True, slots=True)
class Rule:
    field: str
    operator: str
    value: Any

    def as_payload(self) -> dict[str, Any]:
        return {"field": self.field, "operator": self.operator, "value": self.value}


def _number(raw: Any, *, field: str) -> float:
    if isinstance(raw, bool):
        raise InvalidRule(f"{field!r} expects a number, not a true/false value")
    try:
        return float(Decimal(str(raw)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidRule(f"{raw!r} is not a number, which {field!r} expects") from exc


def parse(raw_rules: list[dict[str, Any]]) -> list[Rule]:
    """Validate rules against the vocabulary, or refuse them.

    Refusing is the point. Every branch here is a place where an unchecked
    value would otherwise reach a query.
    """
    rules: list[Rule] = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise InvalidRule(f"rule {index + 1} is not an object")

        key = str(raw.get("field", ""))
        field = FIELDS.get(key)
        if field is None:
            raise InvalidRule(
                f"{key!r} is not a field this screen can read. "
                f"Known fields: {', '.join(sorted(FIELDS))}"
            )

        operator = str(raw.get("operator", ""))
        if operator not in OPERATORS_FOR[field.type]:
            raise InvalidRule(
                f"{operator!r} cannot be applied to a {field.type.value} field. "
                f"Allowed: {', '.join(OPERATORS_FOR[field.type])}"
            )

        value = raw.get("value")

        if field.type is FieldType.NUMBER:
            if operator == "between":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise InvalidRule(f"{key!r} between needs exactly two numbers")
                low, high = (_number(v, field=key) for v in value)
                if low > high:
                    # Silently swapping would accept a rule its author wrote
                    # backwards and return a range they did not ask for.
                    raise InvalidRule(f"{key!r} between: {low} is above {high}")
                value = [low, high]
            else:
                value = _number(value, field=key)

        elif field.type is FieldType.BOOLEAN:
            if not isinstance(value, bool):
                raise InvalidRule(f"{key!r} expects true or false")

        elif field.type is FieldType.DATE:
            try:
                value = date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise InvalidRule(f"{value!r} is not a date (YYYY-MM-DD)") from exc

        else:  # criteria
            if not isinstance(value, (list, tuple)) or not value:
                raise InvalidRule(f"{key!r} needs at least one criterion")
            known = {kind.value for kind in AlertKind}
            chosen = [str(v) for v in value]
            unknown = [v for v in chosen if v not in known]
            if unknown:
                raise InvalidRule(f"unknown criteria: {', '.join(sorted(unknown))}")
            value = chosen

        rules.append(Rule(field=key, operator=operator, value=value))

    return rules


def _numeric_expression(field: Field):
    """The field as a number the database can compare.

    An explicit `cast` rather than `.as_float()`, and the difference is not
    stylistic. `.as_float()` leaves the extraction uncast on SQLite, because
    `json_extract` is normally type-preserving there - true for a JSON number,
    false for ours, which `_serialisable` writes as strings so no precision is
    lost. SQLite then compares a TEXT value against a number by storage class,
    where text always sorts above numbers, so `"2.0" > 10` is true and
    `"9.5" < 10` is false. Measured: both, on the first run of these tests.

    PostgreSQL casts either way, so the bug would have been invisible in
    production and permanent in the suite.

    Casting the *string* form is what makes both dialects agree: a missing key
    extracts as NULL, casts to NULL, and the comparison is NULL - which drops
    the row, matching the rule that a condition nobody could check is not a
    condition that passed.
    """
    if not field.in_signals:
        return getattr(MarketScanResult, field.key)
    return cast(MarketScanResult.signals[field.key].as_string(), Float)


def _condition(rule: Rule):
    field = FIELDS[rule.field]

    if field.type is FieldType.NUMBER:
        column = _numeric_expression(field)
        if rule.operator == "between":
            low, high = rule.value
            return and_(column >= low, column <= high)
        return {
            "lt": lambda: column < rule.value,
            "lte": lambda: column <= rule.value,
            "gt": lambda: column > rule.value,
            "gte": lambda: column >= rule.value,
            "eq": lambda: column == rule.value,
        }[rule.operator]()

    if field.type is FieldType.BOOLEAN:
        return MarketScanResult.signals[field.key].as_boolean() == rule.value

    if field.type is FieldType.DATE:
        column = MarketScanResult.signals[field.key].as_string()
        # ISO-8601 dates compare correctly as text, which is the one place in
        # this module where a string comparison is right rather than a trap.
        return column >= rule.value if rule.operator == "on_or_after" else column <= rule.value

    # Criteria. Evaluated in Python by `matches_criteria` because the JSON
    # containment operators differ by dialect; the SQL layer only narrows.
    return None


def matches_criteria(row: MarketScanResult, rules: list[Rule]) -> bool:
    """The set-valued rules, applied to a fetched row.

    Kept out of SQL deliberately: `?|` and `@>` are PostgreSQL-only, the test
    suite runs on SQLite, and a filter that behaves differently on the two is
    worse than one that costs a pass in Python over rows already narrowed by
    every other rule.
    """
    for rule in rules:
        if FIELDS[rule.field].type is not FieldType.CRITERIA:
            continue
        present = set(row.matched or [])
        wanted = set(rule.value)
        if rule.operator == "includes_any" and not (present & wanted):
            return False
        if rule.operator == "includes_all" and not wanted <= present:
            return False
        if rule.operator == "excludes" and (present & wanted):
            return False
    return True


def build_query(rules: list[Rule], *, on_date: date) -> Select:
    """Every rule ANDed together.

    AND rather than OR, and unlike the criteria checkboxes - which are OR
    because ticking three of them means "show me anything with one of these".
    A rule someone wrote by hand is a requirement: adding one must narrow the
    list, or the builder does the opposite of what building it felt like.

    OR *between* rules is deliberately not offered yet. It needs grouping to
    mean anything ("A and (B or C)"), grouping needs a nested editor, and a
    flat list of rules that silently ORs is a screen nobody can predict.
    """
    stmt = select(MarketScanResult).where(MarketScanResult.session_date == on_date)
    for rule in rules:
        condition = _condition(rule)
        if condition is not None:
            stmt = stmt.where(condition)
    return stmt


@dataclass(slots=True)
class ScreenRun:
    """What a custom screen found, and what it looked at."""

    on_date: date | None
    considered: int
    matched: int
    rows: list[MarketScanResult]
    caveat: str

    @property
    def share(self) -> float:
        return self.matched / self.considered if self.considered else 0.0

    def as_payload(self) -> dict[str, Any]:
        return {
            "session_date": self.on_date.isoformat() if self.on_date else None,
            "considered": self.considered,
            "matched": self.matched,
            "share": round(self.share, 4),
            "results": [
                {
                    "ticker": row.ticker,
                    "close": str(row.close) if row.close is not None else None,
                    "matched": list(row.matched or []),
                    "matched_count": row.matched_count,
                    "signals": row.signals,
                }
                for row in self.rows
            ],
            "caveat": self.caveat,
        }


SCREEN_CAVEAT = (
    "A screen, not a forecast. It lists issuers for which the conditions you "
    "wrote are currently true, and says nothing about what any of them will do "
    "next. An issuer whose value for a condition could not be computed is left "
    "out rather than assumed to pass."
)


def run(
    session: Session,
    rules: list[Rule],
    *,
    on_date: date | None = None,
    limit: int = 100,
) -> ScreenRun:
    """Run a screen over the latest stored scan.

    `considered` is reported next to `matched` on purpose. A filter matching
    most of the exchange is not filtering, and the only way to know is to see
    the denominator - the same lesson two built-in criteria taught by matching
    44% and 36% of the market before anybody measured them.
    """
    from sqlalchemy import func

    from aidss.monitoring.scan import latest_scan_date

    on_date = on_date or latest_scan_date(session)
    if on_date is None:
        return ScreenRun(None, 0, 0, [], SCREEN_CAVEAT)

    considered = (
        session.scalar(
            select(func.count())
            .select_from(MarketScanResult)
            .where(MarketScanResult.session_date == on_date)
        )
        or 0
    )

    stmt = build_query(rules, on_date=on_date)
    narrowed = list(session.scalars(stmt.order_by(MarketScanResult.ticker)).all())
    kept = [row for row in narrowed if matches_criteria(row, rules)]

    return ScreenRun(
        on_date=on_date,
        considered=considered,
        matched=len(kept),
        rows=kept[:limit],
        caveat=SCREEN_CAVEAT,
    )


def describe_fields() -> list[dict[str, Any]]:
    """The vocabulary, for an interface that must not hold a second copy."""
    return [FIELDS[key].as_payload() for key in sorted(FIELDS)]
