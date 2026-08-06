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


def test_an_alias_made_only_of_generic_words_is_refused() -> None:
    assert not is_usable_alias("energi nusantara")
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
