"""Working out which listed companies a news story is about.

The pipeline used to run the other way round: for each ticker somebody watched,
search the feeds for it. That answers "what is being said about BBRI" and
nothing else - a story is only ever seen if a ticker went looking for it, so an
article about a company nobody watches is not merely untagged, it is never
fetched. Tagging inverts it: fetch everything once, then decide who each story
is about.

Two ways a story names a company, and they are not equally reliable:

  * **The code.** "BBRI" in the text is the company, near enough always. IDX
    codes are four letters, so this is only safe with word boundaries -
    substring matching files every article containing "banks" under BANK.
  * **The name.** Most Indonesian coverage never prints the code. The
    registered name is not what gets printed either: the press says "Adaro",
    not "PT Adaro Andalan Indonesia Tbk".

The second is where the false positives live, and this module spends most of
its length on refusing matches rather than making them. A wrong tag is worse
than a missing one here: a missing tag means a story is not shown under a
ticker, while a wrong tag puts an article about somebody else into the evidence
an analysis reasons from.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from aidss.db.models import TagMethod

#: Corporate forms and legal boilerplate. Present in nearly every Indonesian
#: company name and carrying no identifying signal at all, so a match on one is
#: a match on nothing.
_CORPORATE_FORMS = (
    "pt",
    "tbk",
    "persero",
    "perseroan",
    "terbuka",
    "tbk.",
    "pt.",
)

#: Words that are a company's whole short name *and* ordinary Indonesian. An
#: alias equal to one of these matches most of the business section. They are
#: refused as standalone aliases; the full name still matches.
#:
#: Not a spam list to be extended casually - each entry costs real recall for
#: the issuer whose name it is. It exists because these specific words appeared
#: as derived aliases and would each have tagged hundreds of unrelated stories.
_TOO_COMMON = frozenset(
    {
        "bank",
        "indonesia",
        "nusantara",
        "jaya",
        "sejahtera",
        "makmur",
        "mandiri",
        "utama",
        "sentosa",
        "abadi",
        "prima",
        "global",
        "internasional",
        "international",
        "energi",
        "energy",
        "media",
        "karya",
        "graha",
        "pratama",
        "perdana",
        "agung",
        "mulia",
        "cipta",
        "citra",
        "bumi",
        "samudera",
        "trans",
        "asia",
        "asean",
        "digital",
        "teknologi",
        "technology",
        "industri",
        "industry",
        "properti",
        "property",
        "tambang",
        "mineral",
        "sawit",
        "agro",
        "farma",
        "kimia",
        "semen",
        "baja",
        "logam",
        "kabel",
        "plastik",
        "kertas",
        "tekstil",
        "otomotif",
        "motor",
        "wisata",
        "hotel",
        "resort",
        "sukses",
        "maju",
        "bersama",
        "sinar",
        "surya",
        "bintang",
        "mitra",
        "usaha",
        "niaga",
        "dagang",
        "investama",
        "investment",
        "capital",
        "finance",
        "sekuritas",
        "asuransi",
        "life",
        "group",
        "grup",
        "holding",
        "corpora",
        "corporation",
        "tirta",
        "wahana",
        "andalan",
        "raya",
        "pacific",
        "pasifik",
        "timur",
        "barat",
        "utara",
        "selatan",
        "tengah",
    }
)

#: An alias shorter than this matches too much to be worth having. Three
#: catches the initialisms that genuinely identify a company - BRI, BCA, BNI,
#: TLK - while two-letter fragments would fire on almost any sentence.
MIN_ALIAS_LENGTH = 3

#: Beyond this many issuers in one story, the "match" is a listing rather than
#: coverage - an index recap, a most-actives table - and tagging it to fifty
#: companies makes each of their news feeds useless. Left untagged, and the
#: count is recorded so the decision is visible rather than silent.
MAX_ISSUERS_PER_ITEM = 12

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Punctuation goes because "Astra Agro Lestari Tbk." and "Astra Agro
    Lestari, Tbk" are the same company written by two different sub-editors.
    """
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = _NON_WORD.sub(" ", folded.lower())
    return _WHITESPACE.sub(" ", folded).strip()


def trading_name(registered_name: str) -> str:
    """The registered name with its corporate form removed.

    "PT Adaro Andalan Indonesia Tbk" becomes "adaro andalan indonesia". This is
    the longest form worth matching: it is specific enough to be safe and is
    what a formal article prints.
    """
    words = [w for w in normalise(registered_name).split() if w not in _CORPORATE_FORMS]
    return " ".join(words)


def derive_aliases(registered_name: str) -> list[str]:
    """Shorter names the press is likely to use.

    Derivation is a starting point, not the answer. It cannot know that BBRI is
    "BRI", because that initialism comes from "Bank Rakyat Indonesia" and the
    code does not spell it - which is exactly why aliases are editable
    afterwards rather than computed on every read.

    What it can do safely:

      * the trading name itself;
      * its first two words, when the rest is generic decoration ("Astra Agro"
        for "Astra Agro Lestari").

    **Initialisms are not derived, and that was measured rather than assumed.**
    Taking first letters looks like the rule that produces "BRI" from "Bank
    Rakyat Indonesia", and it does. Run over the real 962-issuer directory
    against a day of Indonesian market feeds, it also produced:

        HOKI  <- "bps"   (Buyung Poetra Sembada; matched Badan Pusat Statistik,
                          which appears in every economics story - 17 hits)
        INPC  <- "bagi"  (an ordinary Indonesian word - 12 hits)
        INET  <- "siap"  (likewise - 7)
        NASA  <- "apa"   (likewise - 7)
        SRIL  <- "sri"   (matched Sri Mulyani - 5)
        MEDC  <- "mei"   (the month - 4)

    One correct alias for eight wrong ones. Nothing in the letters distinguishes
    "bni" from "apa", so the rule cannot be repaired by tightening it - only by
    knowing which initialisms a company is actually called, which is knowledge
    derivation does not have and a person does. That is what the editable
    alias field is for.

    Anything that reduces to a single common word is dropped, because "Bank"
    and "Energi" are not names.
    """
    full = trading_name(registered_name)
    if not full:
        return []

    words = full.split()
    candidates: list[str] = [full]

    if len(words) >= 3:
        # "Astra Agro Lestari" -> "astra agro". Two words is usually enough to
        # be unambiguous while matching the form a headline actually uses.
        candidates.append(" ".join(words[:2]))

    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        if candidate in seen or not is_usable_alias(candidate):
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


def is_usable_alias(alias: str) -> bool:
    """Whether an alias identifies a company rather than a category.

    A single word that is ordinary Indonesian is refused however long it is:
    "Sejahtera" is nine characters and still matches half the market.
    """
    alias = alias.strip()
    if len(alias) < MIN_ALIAS_LENGTH:
        return False
    words = alias.split()
    if len(words) == 1 and words[0] in _TOO_COMMON:
        return False
    # An alias made entirely of generic words is generic however many there
    # are: "energi nusantara" identifies nothing.
    return not all(word in _TOO_COMMON for word in words)


#: Above this share of upper-case letters, capitalisation has stopped carrying
#: information and every word looks like a ticker.
SHOUTING_RATIO = 0.6


def shouting(text: str) -> bool:
    """Whether the text is written in capitals throughout.

    Code matching leans entirely on capitalisation, so a headline set in caps
    would turn every common word back into a ticker - the exact failure the
    case-sensitivity was introduced to stop. In that text codes are simply not
    matched; the names still are, and a missed tag costs less than a wrong one.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        # Too short to judge: "BBRI naik" is mostly capitals and perfectly
        # ordinary.
        return False
    return sum(c.isupper() for c in letters) / len(letters) > SHOUTING_RATIO


@dataclass(frozen=True)
class IssuerPattern:
    """One issuer, reduced to what the matcher needs."""

    issuer_id: object
    ticker: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Tag:
    """A story matched to an issuer, with the reason attached."""

    issuer_id: object
    ticker: str
    method: TagMethod
    matched_text: str


class IssuerMatcher:
    """Matches text against every listed company at once.

    Built once per batch and reused. The alternative - a query per article per
    issuer - is 962 patterns times however many articles arrived, and the whole
    directory is small enough to hold in memory several times over.
    """

    def __init__(self, patterns: list[IssuerPattern]) -> None:
        self._patterns = patterns
        # Codes are matched against the original text, case-sensitively, and
        # that is not fussiness. `BANK`, `LABA`, `AGRO`, `RAYA` and `GOOD` are
        # all real IDX codes and all ordinary Indonesian words: matched
        # case-insensitively, "bank sentral menaikkan suku bunga" tags Bank
        # Aladin and "laba bersih" tags LABA. Against the real 962-issuer
        # directory that was not an edge case, it was most sentences.
        self._by_ticker = {p.ticker.upper(): p for p in patterns}
        self._ticker_re = self._alternation([p.ticker.upper() for p in patterns])

        self._alias_owner: dict[str, IssuerPattern] = {}
        ambiguous: set[str] = set()
        for pattern in patterns:
            for alias in {normalise(a) for a in (pattern.name, *pattern.aliases)}:
                if not is_usable_alias(alias):
                    continue
                if alias in self._alias_owner and self._alias_owner[alias] is not pattern:
                    # Two companies answer to the same name. Neither can be
                    # matched on it without guessing, so it belongs to nobody.
                    ambiguous.add(alias)
                    continue
                self._alias_owner[alias] = pattern
        for alias in ambiguous:
            self._alias_owner.pop(alias, None)

        # Longest first, so "bank rakyat indonesia" wins over "bank rakyat"
        # and the tag records the most specific thing that actually matched.
        self._aliases = sorted(self._alias_owner, key=len, reverse=True)
        self._alias_re = self._alternation(self._aliases)

    @staticmethod
    def _alternation(terms: list[str]) -> re.Pattern[str] | None:
        if not terms:
            return None
        joined = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        return re.compile(rf"(?<!\w)({joined})(?!\w)")

    def match(self, *texts: str | None) -> list[Tag]:
        """Every issuer named in the given text, most reliable method first."""
        original = " ".join(t for t in texts if t)
        haystack = normalise(original)
        if not haystack:
            return []

        found: dict[object, Tag] = {}

        if self._ticker_re is not None and not shouting(original):
            for hit in self._ticker_re.finditer(original):
                pattern = self._by_ticker.get(hit.group(1))
                if pattern is not None and pattern.issuer_id not in found:
                    found[pattern.issuer_id] = Tag(
                        pattern.issuer_id,
                        pattern.ticker,
                        TagMethod.TICKER_CODE,
                        pattern.ticker,
                    )

        if self._alias_re is not None:
            for hit in self._alias_re.finditer(haystack):
                text = hit.group(1)
                pattern = self._alias_owner.get(text)
                if pattern is None or pattern.issuer_id in found:
                    # Already tagged by its code, which is the stronger signal;
                    # not overwritten, so the recorded method stays the best one.
                    continue
                method = (
                    TagMethod.COMPANY_NAME
                    if text == normalise(pattern.name)
                    else TagMethod.ALIAS
                )
                found[pattern.issuer_id] = Tag(pattern.issuer_id, pattern.ticker, method, text)

        tags = list(found.values())
        if len(tags) > MAX_ISSUERS_PER_ITEM:
            # A listing, not a story about anybody.
            return []
        return tags
