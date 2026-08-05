"""What a stance means depends on whether you already hold the asset.

A `hold` on something you own and a `hold` on something you do not are the same
word describing two different situations: the first says stay, the second says
there is no reason to start. One label answering both questions is why people
read a recommendation and still ask "so what do I do?".

So both readings are produced, always, side by side. Not the one matching the
reader's position - both. Seeing the case you are *not* in is what makes the
asymmetry visible: an asset worth keeping but not worth buying today is a real
and common situation, and a screen that showed only your own side would hide it.

**Derived, never asked.** This is a deterministic projection of a stored
recommendation onto two situations. A second model call could contradict the
first - saying `buy` and then advising an exit - and there would be no way to
tell which was wrong. Everything below follows from the label, the levels, and
the confidence that were already validated and stored.

**Stances, not orders.** Every phrasing here describes a position and the
condition attached to it. `entry_candidate`, not "buy now". `exit_candidate`,
not "sell". The platform cannot place an order and does not tell anyone to;
Section 5.4 puts the wording under the same rule as the labels themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aidss.domain.types import RecommendationLabel


class PositionState(StrEnum):
    """The two situations a reader can be in."""

    HOLDING = "holding"
    NOT_HOLDING = "not_holding"


class Stance(StrEnum):
    """What the recommendation implies for one situation.

    Named as positions and candidacies rather than actions. `trim` and `reduce`
    describe a resulting position; "sell 30%" would describe an order.
    """

    #: Not holding
    ENTRY_CANDIDATE = "entry_candidate"
    WAIT_FOR_LEVEL = "wait_for_level"
    NO_ENTRY_BASIS = "no_entry_basis"
    AVOID = "avoid"

    #: Holding
    MAINTAIN = "maintain"
    ACCUMULATE_CANDIDATE = "accumulate_candidate"
    TRIM_CANDIDATE = "trim_candidate"
    EXIT_CANDIDATE = "exit_candidate"


#: A stance strong enough to warrant an entry needs evidence behind it. Below
#: this, a `buy` becomes "wait for a level" rather than "enter": Section 5.4
#: already refuses a strong label on thin evidence, and the same reasoning
#: applies to acting on a weak one.
ENTRY_CONFIDENCE_FLOOR = 55.0


@dataclass(frozen=True, slots=True)
class Guidance:
    """One situation's reading of the recommendation."""

    position: PositionState
    stance: Stance
    #: Why this stance follows, in one sentence.
    rationale: str
    #: What has to be true. Empty when the stance is unconditional.
    conditions: list[str] = field(default_factory=list)
    #: What would make this stance wrong. Never empty: a stance with no stated
    #: invalidation is one that can never be shown to have been mistaken, and
    #: those are the ones people hold on to longest.
    invalidated_if: list[str] = field(default_factory=list)
    #: Levels that matter for this situation, if the analysis produced any.
    reference_levels: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.value,
            "stance": self.stance.value,
            "rationale": self.rationale,
            "conditions": list(self.conditions),
            "invalidated_if": list(self.invalidated_if),
            "reference_levels": dict(self.reference_levels),
        }


@dataclass(frozen=True, slots=True)
class StrategyView:
    """Both readings, plus the caveat that applies to both."""

    label: RecommendationLabel
    confidence: float
    not_holding: Guidance
    holding: Guidance
    disclaimer: str
    #: The same view in every other language, keyed by language code. Both are
    #: written by hand rather than one being rendered from the other, so
    #: neither is "the original" and the interface offers them symmetrically.
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label.value,
            "confidence": self.confidence,
            "not_holding": self.not_holding.as_dict(),
            "holding": self.holding.as_dict(),
            "disclaimer": self.disclaimer,
            "translations": dict(self.translations),
        }


STRATEGY_DISCLAIMER = (
    "Informational only and not investment advice. These are stances with the "
    "conditions attached to them, not instructions: this platform places no "
    "orders and is connected to no broker. Position sizing, timing, and the "
    "decision itself remain yours."
)

#: Every sentence this module produces, in both languages.
#:
#: Written here rather than translated at runtime. None of this is model output
#: - it is product copy with a price interpolated into it - so paying an AI to
#: render text we wrote ourselves would spend tokens to arrive back where we
#: started, and would do it again on every view.
#:
#: Neither language is a translation of the other in any sense the interface
#: needs to caveat. Both are originals, so the switch offers them symmetrically
#: and no machine-translation notice appears.
#:
#: The numbers are interpolated on this side of the wire on purpose: formatting
#: a price is already done here, and doing it again in the frontend would be a
#: second place for it to be wrong.
PHRASES: dict[str, dict[str, str]] = {
    # --- shared ---------------------------------------------------------
    "disclaimer": {
        "en": STRATEGY_DISCLAIMER,
        "id": (
            "Hanya informasi dan bukan nasihat investasi. Ini adalah sikap beserta "
            "syarat yang menyertainya, bukan instruksi: platform ini tidak "
            "menempatkan order dan tidak terhubung ke broker mana pun. Ukuran "
            "posisi, waktu, dan keputusannya sendiri tetap milik Anda."
        ),
    },
    "invalid.support": {
        "en": "price closes below support at {support}",
        "id": "harga ditutup di bawah support pada {support}",
    },
    "invalid.level_gives_way": {
        "en": "the level the thesis rests on gives way",
        "id": "level yang menjadi dasar tesis ini jebol",
    },
    "invalid.stance_turns": {
        "en": "the analysis turns, which would be a different stance entirely",
        "id": "analisisnya berbalik, yang berarti sikap yang sama sekali berbeda",
    },
    "invalid.stop": {
        "en": "price reaches the suggested stop at {stop}",
        "id": "harga mencapai stop yang disarankan pada {stop}",
    },

    # --- not holding ----------------------------------------------------
    "nh.thin.rationale": {
        "en": (
            "The stance is {label} but calibrated confidence is {confidence:.0f}, "
            "below the {floor:.0f} this platform treats as enough evidence to "
            "favour starting a position."
        ),
        "id": (
            "Sikapnya {label}, tetapi confidence terkalibrasi hanya {confidence:.0f} "
            "- di bawah {floor:.0f} yang diperlakukan platform ini sebagai bukti "
            "cukup untuk mendukung membuka posisi."
        ),
    },
    "nh.thin.more_agreement": {
        "en": "more of the evidence sources agree, raising confidence",
        "id": "lebih banyak sumber bukti sepakat, sehingga confidence naik",
    },
    "nh.thin.pullback": {
        "en": "price pulls back towards support at {support}",
        "id": "harga mundur ke arah support pada {support}",
    },
    "nh.thin.clearer_level": {
        "en": "a clearer level to work against appears",
        "id": "muncul level yang lebih jelas untuk dijadikan acuan",
    },
    "nh.candidate.rationale": {
        "en": (
            "A {label} stance at {confidence:.0f} confidence describes an asset the "
            "evidence currently favours, which is what makes it a candidate to "
            "consider rather than one to watch."
        ),
        "id": (
            "Sikap {label} pada confidence {confidence:.0f} menggambarkan aset yang "
            "saat ini didukung bukti - itulah yang membuatnya kandidat untuk "
            "dipertimbangkan, bukan sekadar dipantau."
        ),
    },
    "nh.candidate.level_support": {
        "en": "a defined level to work against - support sits at {support}",
        "id": "ada level acuan yang jelas - support berada di {support}",
    },
    "nh.candidate.level_plain": {
        "en": "a defined level to work against",
        "id": "ada level acuan yang jelas",
    },
    "nh.candidate.sizing": {
        "en": (
            "the position size fits your own concentration limits, which this "
            "analysis knows nothing about"
        ),
        "id": (
            "ukuran posisinya sesuai batas konsentrasi Anda sendiri, yang sama "
            "sekali tidak diketahui analisis ini"
        ),
    },
    "nh.watchlist.rationale": {
        "en": (
            "A watchlist stance means the case is not yet made either way - worth "
            "following, without a basis to start today."
        ),
        "id": (
            "Sikap watchlist berarti alasannya belum terbentuk ke arah mana pun - "
            "layak diikuti, tanpa dasar untuk memulai hari ini."
        ),
    },
    "nh.watchlist.clears": {
        "en": "price clears resistance at {resistance} and holds",
        "id": "harga menembus resistance pada {resistance} dan bertahan",
    },
    "nh.watchlist.resolves": {
        "en": "the price structure resolves in one direction",
        "id": "struktur harga terselesaikan ke satu arah",
    },
    "nh.watchlist.reaches": {
        "en": "or price reaches support at {support} with the thesis intact",
        "id": "atau harga mencapai support pada {support} dengan tesis masih utuh",
    },
    "nh.watchlist.clearer_entry": {
        "en": "or a clearer entry level forms",
        "id": "atau terbentuk level masuk yang lebih jelas",
    },
    "nh.watchlist.stops_applying": {
        "en": "the reason for following it stops applying",
        "id": "alasan untuk mengikutinya tidak lagi berlaku",
    },
    "nh.hold.rationale": {
        "en": (
            "A hold describes staying where you are. For someone with no position, "
            "staying where you are means not starting one - the same stance reads "
            "differently from the two sides."
        ),
        "id": (
            "Hold menggambarkan tetap di posisi Anda sekarang. Bagi yang belum "
            "punya posisi, tetap di tempat berarti tidak memulai - sikap yang sama "
            "terbaca berbeda dari dua sisi."
        ),
    },
    "nh.hold.directional": {
        "en": "a directional case forms in either direction",
        "id": "terbentuk alasan berarah, ke mana pun arahnya",
    },
    "nh.hold.off_neutral": {
        "en": "the analysis moves off neutral",
        "id": "analisisnya bergerak keluar dari netral",
    },
    "nh.avoid.rationale": {
        "en": (
            "A {label} stance describes evidence pointing down. There is no reading "
            "of it that favours starting a position."
        ),
        "id": (
            "Sikap {label} menggambarkan bukti yang mengarah turun. Tidak ada "
            "pembacaan atasnya yang mendukung membuka posisi."
        ),
    },

    # --- holding ---------------------------------------------------------
    "h.accumulate.rationale": {
        "en": (
            "The evidence favours the asset at {confidence:.0f} confidence, so an "
            "existing position has no case against it and adding is a candidate."
        ),
        "id": (
            "Bukti mendukung aset ini pada confidence {confidence:.0f}, sehingga "
            "posisi yang sudah ada tidak menghadapi alasan untuk dilepas dan "
            "menambah menjadi salah satu kandidat."
        ),
    },
    "h.accumulate.concentration": {
        "en": "adding would not push this holding past your own concentration limit",
        "id": (
            "menambah tidak membuat kepemilikan ini melewati batas konsentrasi Anda "
            "sendiri"
        ),
    },
    "h.accumulate.pullback": {
        "en": "a pullback towards support at {support} rather than into strength",
        "id": "harga mundur ke arah support pada {support}, bukan mengejar penguatan",
    },
    "h.accumulate.average_level": {
        "en": "an entry level you are willing to average at",
        "id": "level masuk yang Anda bersedia pakai untuk merata-ratakan",
    },
    "h.buy.rationale": {
        "en": (
            "A buy stance at {confidence:.0f} confidence supports keeping the "
            "position. It does not by itself argue for enlarging it."
        ),
        "id": (
            "Sikap buy pada confidence {confidence:.0f} mendukung mempertahankan "
            "posisi. Dengan sendirinya itu bukan alasan untuk memperbesarnya."
        ),
    },
    "h.buy.target": {
        "en": "the target at {target} remains the case being tested",
        "id": "target di {target} tetap menjadi hipotesis yang sedang diuji",
    },
    "h.maintain.rationale": {
        "en": (
            "A {label} stance gives no reason to change an existing position in "
            "either direction."
        ),
        "id": (
            "Sikap {label} tidak memberi alasan untuk mengubah posisi yang ada, ke "
            "arah mana pun."
        ),
    },
    "h.maintain.nothing_turned": {
        "en": "nothing in the evidence has turned",
        "id": "tidak ada bukti yang berbalik",
    },
    "h.maintain.next_analysis": {
        "en": "the next analysis reaches a different stance",
        "id": "analisis berikutnya sampai pada sikap yang berbeda",
    },
    "h.reduce.rationale": {
        "en": (
            "The evidence has weakened without turning outright negative, which is "
            "what a reduce stance describes: a smaller position, not none."
        ),
        "id": (
            "Bukti melemah tanpa berbalik negatif sepenuhnya - itulah yang "
            "digambarkan sikap reduce: posisi yang lebih kecil, bukan nol."
        ),
    },
    "h.reduce.sizing": {
        "en": (
            "how much to trim is a position-sizing decision this analysis cannot "
            "make for you"
        ),
        "id": (
            "seberapa banyak dikurangi adalah keputusan ukuran posisi yang tidak "
            "bisa diambil analisis ini untuk Anda"
        ),
    },
    "h.reduce.recovers": {
        "en": "the evidence recovers and the stance moves back up",
        "id": "bukti pulih dan sikapnya bergerak naik kembali",
    },
    "h.exit.rationale": {
        "en": (
            "A sell stance at {confidence:.0f} confidence describes evidence "
            "pointing down, which makes closing the position the candidate reading."
        ),
        "id": (
            "Sikap sell pada confidence {confidence:.0f} menggambarkan bukti yang "
            "mengarah turun, sehingga menutup posisi menjadi pembacaan kandidatnya."
        ),
    },
    "h.exit.timing": {
        "en": "timing and tax consequences are yours, and are not modelled here",
        "id": "waktu dan konsekuensi pajak ada pada Anda, dan tidak dimodelkan di sini",
    },
}

#: The languages every strategy view is produced in.
STRATEGY_LANGUAGES: tuple[str, ...] = ("en", "id")


def _t(key: str, language: str, **params: Any) -> str:
    """One sentence, in one language.

    A missing key raises rather than falling back to English: a half-translated
    panel that silently mixes languages is harder to notice than one that fails
    the moment it is written.
    """
    return PHRASES[key][language].format(**params)


def _fmt(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)):,.2f}"


def _levels(
    support: Decimal | None,
    resistance: Decimal | None,
    target: Decimal | None,
    stop: Decimal | None,
) -> dict[str, str]:
    pairs = {
        "support": _fmt(support),
        "resistance": _fmt(resistance),
        "target": _fmt(target),
        "suggested_stop": _fmt(stop),
    }
    return {key: value for key, value in pairs.items() if value is not None}


def _not_holding(
    label: RecommendationLabel,
    confidence: float,
    levels: dict[str, str],
    language: str = "en",
) -> Guidance:
    support = levels.get("support")
    resistance = levels.get("resistance")

    def say(key: str, **params: Any) -> str:
        return _t(key, language, **params)

    invalidation = (
        [say("invalid.support", support=support)]
        if support
        else [say("invalid.level_gives_way")]
    )

    if label in (RecommendationLabel.STRONG_BUY, RecommendationLabel.BUY):
        if confidence < ENTRY_CONFIDENCE_FLOOR:
            return Guidance(
                position=PositionState.NOT_HOLDING,
                stance=Stance.WAIT_FOR_LEVEL,
                rationale=say(
                    "nh.thin.rationale",
                    label=label.value,
                    confidence=confidence,
                    floor=ENTRY_CONFIDENCE_FLOOR,
                ),
                conditions=[
                    say("nh.thin.more_agreement"),
                    say("nh.thin.pullback", support=support)
                    if support
                    else say("nh.thin.clearer_level"),
                ],
                invalidated_if=invalidation,
                reference_levels=levels,
            )
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.ENTRY_CANDIDATE,
            rationale=say(
                "nh.candidate.rationale", label=label.value, confidence=confidence
            ),
            conditions=[
                say("nh.candidate.level_support", support=support)
                if support
                else say("nh.candidate.level_plain"),
                say("nh.candidate.sizing"),
            ],
            invalidated_if=invalidation,
            reference_levels=levels,
        )

    if label is RecommendationLabel.WATCHLIST:
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.WAIT_FOR_LEVEL,
            rationale=say("nh.watchlist.rationale"),
            conditions=[
                say("nh.watchlist.clears", resistance=resistance)
                if resistance
                else say("nh.watchlist.resolves"),
                say("nh.watchlist.reaches", support=support)
                if support
                else say("nh.watchlist.clearer_entry"),
            ],
            invalidated_if=[say("nh.watchlist.stops_applying")],
            reference_levels=levels,
        )

    if label is RecommendationLabel.HOLD:
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.NO_ENTRY_BASIS,
            rationale=say("nh.hold.rationale"),
            conditions=[say("nh.hold.directional")],
            invalidated_if=[say("nh.hold.off_neutral")],
            reference_levels=levels,
        )

    # reduce / sell
    return Guidance(
        position=PositionState.NOT_HOLDING,
        stance=Stance.AVOID,
        rationale=say("nh.avoid.rationale", label=label.value),
        conditions=[],
        invalidated_if=[say("invalid.stance_turns")],
        reference_levels=levels,
    )


def _holding(
    label: RecommendationLabel,
    confidence: float,
    levels: dict[str, str],
    language: str = "en",
) -> Guidance:
    support = levels.get("support")
    target = levels.get("target")
    stop = levels.get("suggested_stop")

    def say(key: str, **params: Any) -> str:
        return _t(key, language, **params)

    stop_line = (
        say("invalid.stop", stop=stop)
        if stop
        else (
            say("invalid.support", support=support)
            if support
            else say("invalid.level_gives_way")
        )
    )

    if label is RecommendationLabel.STRONG_BUY:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.ACCUMULATE_CANDIDATE,
            rationale=say("h.accumulate.rationale", confidence=confidence),
            conditions=[
                say("h.accumulate.concentration"),
                say("h.accumulate.pullback", support=support)
                if support
                else say("h.accumulate.average_level"),
            ],
            invalidated_if=[stop_line],
            reference_levels=levels,
        )

    if label is RecommendationLabel.BUY:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.MAINTAIN,
            rationale=say("h.buy.rationale", confidence=confidence),
            conditions=[say("h.buy.target", target=target)] if target else [],
            invalidated_if=[stop_line],
            reference_levels=levels,
        )

    if label in (RecommendationLabel.HOLD, RecommendationLabel.WATCHLIST):
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.MAINTAIN,
            rationale=say("h.maintain.rationale", label=label.value),
            conditions=[say("h.maintain.nothing_turned")],
            invalidated_if=[stop_line, say("h.maintain.next_analysis")],
            reference_levels=levels,
        )

    if label is RecommendationLabel.REDUCE:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.TRIM_CANDIDATE,
            rationale=say("h.reduce.rationale"),
            conditions=[say("h.reduce.sizing")],
            invalidated_if=[say("h.reduce.recovers")],
            reference_levels=levels,
        )

    return Guidance(
        position=PositionState.HOLDING,
        stance=Stance.EXIT_CANDIDATE,
        rationale=say("h.exit.rationale", confidence=confidence),
        conditions=[say("h.exit.timing")],
        invalidated_if=[say("invalid.stance_turns")],
        reference_levels=levels,
    )


def build_strategy(
    label: RecommendationLabel | str,
    confidence: float,
    *,
    support_level: Decimal | None = None,
    resistance_level: Decimal | None = None,
    target_price: Decimal | None = None,
    suggested_stop: Decimal | None = None,
) -> StrategyView:
    """Both readings of one stored recommendation."""
    resolved = label if isinstance(label, RecommendationLabel) else RecommendationLabel(label)
    levels = _levels(support_level, resistance_level, target_price, suggested_stop)

    # Built once per language, from the same branch logic. Nothing is rendered
    # from anything else, so the two cannot describe different stances - they
    # are the same decision tree walked twice with a different phrase table.
    return StrategyView(
        label=resolved,
        confidence=confidence,
        not_holding=_not_holding(resolved, confidence, levels, "en"),
        holding=_holding(resolved, confidence, levels, "en"),
        disclaimer=_t("disclaimer", "en"),
        translations={
            language: {
                "not_holding": _not_holding(resolved, confidence, levels, language).as_dict(),
                "holding": _holding(resolved, confidence, levels, language).as_dict(),
                "disclaimer": _t("disclaimer", language),
            }
            for language in STRATEGY_LANGUAGES
            if language != "en"
        },
    )
