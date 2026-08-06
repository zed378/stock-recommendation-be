"""Deciding which listed companies a news story is about.

Every case here came from running the matcher against the real IDX directory -
962 issuers, pulled live - rather than from imagining what might go wrong. The
imagined version of this test would have passed on the first, badly broken
implementation.
"""

from __future__ import annotations

import pytest

from aidss.db.models import TagMethod
from aidss.news.tagging import (
    IssuerMatcher,
    IssuerPattern,
    derive_aliases,
    is_usable_alias,
    normalise,
    shouting,
    trading_name,
)


def pattern(ticker: str, name: str) -> IssuerPattern:
    return IssuerPattern(ticker, ticker, name, tuple(derive_aliases(name)))


#: A slice of the real directory, chosen for the collisions it contains: BANK,
#: LABA and AGRO are genuine codes and ordinary Indonesian words.
DIRECTORY = [
    pattern("BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk"),
    pattern("BBCA", "PT Bank Central Asia Tbk"),
    pattern("AALI", "Astra Agro Lestari Tbk"),
    pattern("ASII", "PT Astra International Tbk"),
    pattern("AADI", "PT Adaro Andalan Indonesia Tbk"),
    pattern("TLKM", "PT Telkom Indonesia (Persero) Tbk"),
    pattern("BANK", "PT Bank Aladin Syariah Tbk"),
    pattern("LABA", "PT Ladangbaja Murni Tbk"),
    pattern("AGRO", "PT Bank Raya Indonesia Tbk"),
]


@pytest.fixture(scope="module")
def matcher() -> IssuerMatcher:
    return IssuerMatcher(DIRECTORY)


def tickers(matcher: IssuerMatcher, text: str) -> set[str]:
    return {tag.ticker for tag in matcher.match(text)}


# --- the collisions that made case-sensitivity necessary --------------------


def test_an_ordinary_word_that_is_also_a_ticker_is_not_a_mention(matcher) -> None:
    """`BANK`, `LABA` and `AGRO` are all listed companies. Matched without
    regard to case - which is what the first implementation did - "bank sentral
    menaikkan suku bunga" tags Bank Aladin and "laba bersih" tags Ladangbaja.
    On real headlines that was not a rare edge, it was most sentences."""
    assert tickers(matcher, "Bank sentral menaikkan suku bunga acuan") == set()
    assert tickers(matcher, "Laba bersih perbankan tumbuh sepanjang tahun") == set()
    assert tickers(matcher, "Sektor agro mencatat pertumbuhan") == set()


def test_the_code_in_capitals_is_a_mention(matcher) -> None:
    assert tickers(matcher, "Saham BBRI menguat 2 persen") == {"BBRI"}
    assert tickers(matcher, "BANK mencatatkan pertumbuhan kredit") == {"BANK"}


def test_a_headline_in_capitals_does_not_match_codes(matcher) -> None:
    """Capitalisation is the whole signal for codes, so text that is entirely
    capitals carries none - every common word would look like a ticker. The
    name still matches, which is why the tag is not simply lost."""
    shouted = "RUPS BANK ALADIN SYARIAH MENYETUJUI PERUBAHAN PENGURUS PERSEROAN"
    assert shouting(shouted)
    found = matcher.match(shouted)
    assert {t.ticker for t in found} == {"BANK"}
    assert found[0].method is TagMethod.ALIAS, "matched as a name, not as a code"


def test_a_short_capitalised_headline_is_not_treated_as_shouting() -> None:
    """"BBRI naik" is mostly capital letters and entirely ordinary."""
    assert not shouting("BBRI naik")


# --- names, which is how most Indonesian coverage refers to a company -------


def test_the_company_name_is_matched_when_the_code_is_absent(matcher) -> None:
    tags = matcher.match("Bank Rakyat Indonesia catatkan laba bersih Rp 60 triliun")
    assert [(t.ticker, t.method) for t in tags] == [("BBRI", TagMethod.ALIAS)]


def test_the_registered_name_is_matched_including_its_corporate_form(matcher) -> None:
    tags = matcher.match("PT Astra Agro Lestari Tbk umumkan dividen")
    assert [(t.ticker, t.method) for t in tags] == [("AALI", TagMethod.COMPANY_NAME)]


def test_two_companies_sharing_a_first_word_are_not_confused(matcher) -> None:
    """Astra Agro Lestari and Astra International are different issuers."""
    assert tickers(matcher, "Astra Agro Lestari membukukan kenaikan") == {"AALI"}
    assert tickers(matcher, "Astra International menaikkan target") == {"ASII"}


def test_the_code_wins_over_the_name_for_the_same_issuer(matcher) -> None:
    """Both appear; the tag should record the stronger reason, not whichever
    pattern happened to be tried second."""
    tags = matcher.match("PT Bank Rakyat Indonesia (BBRI) mengumumkan dividen")
    assert len(tags) == 1
    assert tags[0].method is TagMethod.TICKER_CODE


def test_a_word_boundary_is_required(matcher) -> None:
    """Without it "BBRIS" matches BBRI and every article containing "banking"
    is filed under BANK."""
    assert tickers(matcher, "Saham BBRIS dan BANKX diperdagangkan") == set()


# --- refusing aliases that are categories rather than names -----------------


def test_a_generic_word_is_not_a_usable_alias() -> None:
    for word in ("bank", "energi", "nusantara", "sejahtera", "indonesia"):
        assert not is_usable_alias(word), word


def test_a_derived_two_word_prefix_of_generic_words_is_refused() -> None:
    """Derivation gets no benefit of the doubt, and this is where the two rules
    part company. "Kawasan Industri Jababeka" yields the prefix "kawasan
    industri" - Indonesian for "industrial estate" - which matched a story about
    an estate in Madura. The index may say "Bank Mandiri" because a person
    vetted it; derivation may not invent the equivalent."""
    assert "kawasan industri" not in derive_aliases("PT Kawasan Industri Jababeka Tbk")
    assert "kawasan industri jababeka" in derive_aliases("PT Kawasan Industri Jababeka Tbk")


def test_two_generic_words_together_are_a_name() -> None:
    """This test used to assert the opposite, and the opposite was wrong.

    "an alias made entirely of generic words is generic" rejects "Bank
    Mandiri", "Semen Indonesia", "Kimia Farma" and "Bank Raya" - every one an
    everyday name for a real issuer, and for most of them *the* everyday name.
    The phrase the rule was meant to catch costs one uncertain tag; the rule
    itself cost the coverage of several of the largest companies on the
    exchange."""
    assert is_usable_alias("bank mandiri")
    assert is_usable_alias("semen indonesia")
    assert is_usable_alias("adaro andalan")


def test_a_name_two_issuers_share_belongs_to_neither() -> None:
    """Ambiguity cannot be resolved by picking one, so the alias is dropped and
    both issuers lose it. A guessed tag is worse than an absent one: it puts
    another company's news into the evidence an analysis reasons from."""
    twins = IssuerMatcher(
        [pattern("AAAA", "PT Sumber Alam Tbk"), pattern("BBBB", "PT Sumber Alam Tbk")]
    )
    assert twins.match("Sumber Alam mengumumkan ekspansi") == []


def test_a_listing_of_many_issuers_is_not_coverage_of_any(matcher) -> None:
    """An index recap naming everything is not a story about each of them, and
    tagging it to all makes every one of those feeds useless."""
    recap = " ".join(p.ticker for p in DIRECTORY) + " bergerak di zona hijau"
    assert matcher.match(recap) == []


# --- derivation -------------------------------------------------------------


def test_the_corporate_form_is_stripped_from_the_trading_name() -> None:
    assert trading_name("PT Adaro Andalan Indonesia Tbk") == "adaro andalan indonesia"
    assert trading_name("PT Bank Rakyat Indonesia (Persero) Tbk") == "bank rakyat indonesia"


def test_derivation_produces_a_shorter_form_for_a_long_name() -> None:
    aliases = derive_aliases("Astra Agro Lestari Tbk")
    assert "astra agro lestari" in aliases
    assert "astra agro" in aliases


def test_derivation_never_produces_a_bare_generic_word() -> None:
    """"PT Bank Aladin Syariah Tbk" must not yield "bank"."""
    for alias in derive_aliases("PT Bank Aladin Syariah Tbk"):
        assert is_usable_alias(alias), alias


def test_punctuation_and_case_do_not_change_a_name() -> None:
    assert normalise("Astra Agro Lestari, Tbk.") == normalise("ASTRA AGRO LESTARI TBK")


def test_matching_is_unaffected_by_punctuation(matcher) -> None:
    assert tickers(matcher, "PT. Adaro Andalan Indonesia, Tbk. melaporkan") == {"AADI"}


def test_initialisms_are_not_derived() -> None:
    """Measured, not assumed. Deriving first letters produces "BRI" from "Bank
    Rakyat Indonesia" - and, over the real directory and a day of real feeds,
    also produced "bps" for HOKI (matching Badan Pusat Statistik in 17 economics
    stories), "bagi" for INPC, "siap" for INET, "apa" for NASA, "sri" for SRIL
    (matching Sri Mulyani) and "mei" for MEDC. One right, eight wrong.

    Nothing in the letters separates "bni" from "apa", so the rule cannot be
    tightened into correctness - it can only be removed and the useful cases
    typed in by someone who knows them.
    """
    for name, accident in [
        ("PT Buyung Poetra Sembada Tbk", "bps"),
        ("PT Bank Artha Graha Internasional Tbk", "bagi"),
        ("PT Sri Rejeki Isman Tbk", "sri"),
        ("PT Medco Energi Internasional Tbk", "mei"),
    ]:
        assert accident not in derive_aliases(name), f"{name} derived {accident!r}"


def test_a_curated_initialism_still_matches() -> None:
    """Removing the derivation must not remove the capability: "BRI" typed in
    by hand has to work, or the reason for dropping the rule collapses."""
    bbri = IssuerPattern("BBRI", "BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk", ("bri",))
    matcher = IssuerMatcher([bbri])
    assert {t.ticker for t in matcher.match("BRI salurkan kredit UMKM")} == {"BBRI"}
