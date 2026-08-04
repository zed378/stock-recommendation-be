"""Does the IDX endpoint still answer, and still mean what the parser thinks?

Opt-in, like the other live checks:

    pytest -m network

This adapter depends on an undocumented endpoint reached through Cloudflare, so
it has more ways to break than the others and each one fails differently. The
tests below separate them, because "IDX is down" and "the bot protection was
tightened" and "the units changed" need three different responses.

The units get the most attention. Nothing in the payload states that money is
in billions of rupiah or that `roe` is a percentage; both were established by
comparing issuers against known figures. If IDX ever changes either, every
downstream number is wrong by a hundred or a billion and nothing else would
notice - so the check is a plausibility range, wide enough not to be brittle
and narrow enough to catch a change of scale.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aidss.plugins.adapters.market_idx import IDXMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

pytestmark = pytest.mark.network

#: A large bank and a large miner. Two very different balance sheets, so a
#: scale error cannot hide behind one issuer's shape.
BANK = "BBCA"
MINER = "ADRO"


@pytest.fixture(scope="module")
def adapter() -> IDXMarketDataProvider:
    """One instance for the module, so the adapter's own pacing applies."""
    return IDXMarketDataProvider()


@pytest.fixture(scope="module")
def bank(adapter: IDXMarketDataProvider) -> dict[str, Decimal]:
    try:
        points = adapter.get_fundamentals(BANK)
    except ProviderUnavailableError as exc:
        if exc.retryable:
            pytest.skip(f"IDX is unavailable right now: {exc}")
        # A permanent refusal is a finding, not a reason to skip: it means the
        # route closed or the protection tightened, which is exactly what this
        # file exists to report.
        raise
    if not points:
        pytest.fail(f"IDX returned no fundamentals for {BANK} - the query or filter has changed")
    return {p.metric: p.value for p in points}


def test_the_expected_metrics_are_all_present(bank) -> None:
    for metric in (
        "pe_ratio",
        "price_to_book",
        "debt_to_equity",
        "return_on_equity",
        "return_on_assets",
        "total_assets",
        "total_equity",
        "total_revenue",
        "net_income",
        "eps_trailing",
    ):
        assert metric in bank, f"{metric} disappeared from the IDX payload"


def test_money_is_still_in_billions_of_rupiah(bank) -> None:
    """A large Indonesian bank's assets belong in the hundreds of trillions.

    If IDX switched to absolute rupiah or to millions, this is where it shows.
    """
    assets = bank["total_assets"]
    assert Decimal("1e14") < assets < Decimal("1e16"), (
        f"total_assets is {assets:,.0f}, which is not a plausible figure in rupiah - "
        "the reporting scale has probably changed"
    )


def test_ratios_are_still_fractions_not_percentages(bank) -> None:
    """IDX reports 20.66 and this column holds 0.2066.

    A bank's return on equity sits in the tens of percent; as a fraction that
    is comfortably under one. Seeing a number above one means the conversion
    stopped happening.
    """
    for metric in ("return_on_equity", "return_on_assets"):
        value = bank[metric]
        assert Decimal("-1") < value < Decimal("1"), (
            f"{metric} is {value}, which reads as a percentage rather than a fraction"
        )


def test_plain_ratios_were_not_divided_by_a_hundred(bank) -> None:
    """The same error in the other direction: PE and PBV are already unitless."""
    assert Decimal("1") < bank["pe_ratio"] < Decimal("200")
    assert Decimal("0.01") < bank["price_to_book"] < Decimal("50")


def test_the_balance_sheet_still_reconciles(bank) -> None:
    """Liabilities over equity must reproduce the reported ratio.

    An arithmetic check the conversions cannot pass by accident, and one that
    catches a scale applied to one field but not another.
    """
    derived = bank["total_liabilities"] / bank["total_equity"]
    assert abs(derived - bank["debt_to_equity"]) < Decimal("0.05")


def test_earnings_are_smaller_than_revenue(bank) -> None:
    """Trivially true of any real company, and false the moment two fields are
    scaled differently."""
    assert Decimal(0) < bank["net_income"] < bank["total_revenue"]


def test_a_second_issuer_of_a_different_size_agrees(adapter) -> None:
    """One issuer could be right by coincidence; a miner two orders of
    magnitude smaller could not."""
    try:
        points = adapter.get_fundamentals(MINER)
    except ProviderUnavailableError as exc:
        if exc.retryable:
            pytest.skip(f"IDX is unavailable right now: {exc}")
        raise

    assert points, f"no fundamentals for {MINER}"
    parsed = {p.metric: p.value for p in points}
    assert Decimal("1e12") < parsed["total_assets"] < Decimal("1e15")
    assert Decimal("-1") < parsed["return_on_equity"] < Decimal("1")


def test_the_period_is_a_fiscal_year_end(bank, adapter) -> None:
    """The stored period keys the fiscal year, so a refetch revises the same
    row rather than creating a new one."""
    points = adapter.get_fundamentals(BANK)
    periods = {p.period for p in points}
    assert len(periods) == 1
    period = periods.pop()
    assert period.month in {3, 6, 9, 12}
    assert period.day in {30, 31}
    assert {p.period_type for p in points} <= {"ytd", "annual"}


def test_an_unknown_ticker_reports_no_coverage(adapter) -> None:
    """Not an error - the collector records it as unsupported."""
    assert adapter.get_fundamentals("ZZZZ") == []
