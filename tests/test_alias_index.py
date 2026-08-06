"""The curated alias index has to be checked, not just written.

It is hand-typed knowledge, so its failures are typos and collisions rather than
logic errors - and both are invisible on inspection. A string claimed by two
issuers, or one that happens to be another company's ticker, produces confident
wrong tags rather than an exception.
"""

from __future__ import annotations

import pytest

from aidss.news.alias_index import CURATED_ALIASES, curated_for
from aidss.news.tagging import (
    MIN_ALIAS_LENGTH,
    IssuerMatcher,
    IssuerPattern,
    effective_aliases,
    is_usable_alias,
    normalise,
)


def test_every_entry_is_a_usable_alias() -> None:
    """The index bypasses nothing. An entry too general to be derived is too
    general to be typed."""
    offenders = [
        (ticker, alias)
        for ticker, aliases in CURATED_ALIASES.items()
        for alias in aliases
        if not is_usable_alias(normalise(alias))
    ]
    assert not offenders, (
        f"these index entries would match far more than their issuer: {offenders}. "
        f"An alias must be at least {MIN_ALIAS_LENGTH} characters and must not be "
        "a single ordinary word."
    )


def test_no_alias_is_claimed_by_two_issuers() -> None:
    """A name two companies answer to identifies neither. Caught here rather
    than at match time, where the matcher silently drops it and both issuers
    quietly lose an alias somebody meant to give one of them."""
    owners: dict[str, list[str]] = {}
    for ticker, aliases in CURATED_ALIASES.items():
        for alias in aliases:
            owners.setdefault(normalise(alias), []).append(ticker)

    clashes = {alias: tickers for alias, tickers in owners.items() if len(tickers) > 1}
    assert not clashes, f"claimed by more than one issuer: {clashes}"


def test_no_alias_collides_with_a_ticker_code() -> None:
    """Codes are matched separately and case-sensitively. An index entry that
    spells another issuer's code would tag that story to both."""
    codes = {ticker.lower() for ticker in CURATED_ALIASES}
    collisions = [
        (ticker, alias)
        for ticker, aliases in CURATED_ALIASES.items()
        for alias in aliases
        if normalise(alias) in codes and normalise(alias) != ticker.lower()
    ]
    assert not collisions, f"index entries that are other issuers' codes: {collisions}"


def test_the_keys_are_four_letter_idx_codes() -> None:
    """A typo in the key is an entry that silently belongs to nobody: the
    ticker never matches an issuer, so the aliases under it are never loaded."""
    malformed = [t for t in CURATED_ALIASES if len(t) != 4 or not t.isupper() or not t.isalpha()]
    assert not malformed, f"not IDX codes: {malformed}"


def test_no_entry_duplicates_within_one_issuer() -> None:
    duplicated = {
        ticker: aliases
        for ticker, aliases in CURATED_ALIASES.items()
        if len({normalise(a) for a in aliases}) != len(aliases)
    }
    assert not duplicated, f"repeated within one entry: {duplicated}"


# --- what the index is actually for -----------------------------------------


@pytest.mark.parametrize(
    ("ticker", "name", "text"),
    [
        ("BBCA", "PT Bank Central Asia Tbk", "BCA bukukan laba bersih Rp 54 triliun"),
        ("BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk", "BRI salurkan kredit UMKM"),
        ("BBNI", "PT Bank Negara Indonesia (Persero) Tbk", "BNI perluas akses KPR"),
        ("TLKM", "PT Telkom Indonesia (Persero) Tbk", "Telkomsel luncurkan paket baru"),
        ("ICBP", "PT Indofood CBP Sukses Makmur Tbk", "Harga Indomie naik tahun ini"),
        ("SIDO", "PT Industri Jamu dan Farmasi Sido Muncul Tbk", "Penjualan Tolak Angin tumbuh"),
        ("GOTO", "PT GoTo Gojek Tokopedia Tbk", "Tokopedia rombak struktur komisi"),
        ("BBTN", "PT Bank Tabungan Negara (Persero) Tbk", "BTN targetkan penyaluran KPR"),
    ],
)
def test_the_everyday_name_reaches_the_issuer(ticker: str, name: str, text: str) -> None:
    """The names people actually print. None of these are reachable from the
    registered name by any rule: "Indomie" is not in "Indofood CBP Sukses
    Makmur", and "BCA" is not in "Bank Central Asia" as a substring."""
    matcher = IssuerMatcher(
        [IssuerPattern(ticker, ticker, name, tuple(effective_aliases(name, ticker)))]
    )
    assert {tag.ticker for tag in matcher.match(text)} == {ticker}, text


def test_a_subsidiary_reaches_the_listed_parent() -> None:
    """A story about Telkomsel's tariffs is a story about TLKM's revenue. The
    reader looking at TLKM should see it."""
    assert "telkomsel" in curated_for("TLKM")
    assert "tokopedia" in curated_for("GOTO")


def test_the_index_beats_derivation_where_they_disagree() -> None:
    """Both contribute; neither is dropped. Derivation gives the formal name a
    filing uses, the index gives the name a headline uses."""
    aliases = effective_aliases("PT Bank Central Asia Tbk", "BBCA")
    assert "bca" in aliases, "the index entry"
    assert "bank central asia" in aliases, "the derived trading name"


def test_an_issuer_imported_before_an_index_entry_existed_still_matches() -> None:
    """The reason the effective list is computed rather than stored. A row whose
    `aliases` column is empty - which is now every row, since the import writes
    nothing there - must still match on its index entry."""
    aliases = effective_aliases("PT Bank Central Asia Tbk", "BBCA", [])
    assert "bca" in aliases


def test_an_administrator_s_extra_is_added_not_substituted() -> None:
    aliases = effective_aliases("PT Bank Central Asia Tbk", "BBCA", ["Klik BCA"])
    assert "klik bca" in aliases
    assert "bca" in aliases, "typing an extra must not displace the index"


# --- the words deliberately kept out ----------------------------------------


@pytest.mark.parametrize(
    ("ticker", "excluded", "why"),
    [
        ("ARTO", "jago", "an ordinary Indonesian word for champion"),
        ("TINS", "timah", "the metal, written about without the company"),
        ("GIAA", "garuda", "the national symbol and the football team"),
        ("EXCL", "xl", "two letters match too much prose"),
    ],
)
def test_ambiguous_short_names_are_kept_out(ticker: str, excluded: str, why: str) -> None:
    assert excluded not in curated_for(ticker), f"{excluded!r} is {why}"
