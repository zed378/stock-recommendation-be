"""Work that outlives a proxy timeout must be queued, not held on a request.

A full multi-agent analysis is a dozen model calls and several translations on
top. Held on an HTTP request, whatever sits in front of the server becomes the
real limit on how thorough it can be - and behind Cloudflare that limit is a
fixed 100 seconds no configuration on the origin can raise. The reader got a
524 error page while the work carried on and its result was thrown away.

The queued endpoint has existed since the job queue was built. The button
simply did not use it. Nothing links "this work is slow" to "call the queued
endpoint", so nothing would notice it being wired back to the synchronous one -
and it would look correct in review and on a fast local machine, failing only
against a real deployment.

A static check, in the Python suite, for the same reason as the other frontend
guards: it is the suite that runs on every change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
ASSET_DETAIL = FRONTEND / "pages" / "AssetDetail.tsx"
CLIENT = FRONTEND / "api" / "client.ts"


def read(path: Path) -> str:
    if not path.exists():  # pragma: no cover - a move, not a regression
        pytest.fail(f"{path} is missing; update this test to follow it")
    return path.read_text(encoding="utf-8")


def test_the_analysis_button_queues_rather_than_waits() -> None:
    source = read(ASSET_DETAIL)

    assert '"/assets/{ticker}/analysis/background"' in source, (
        "running an analysis must go through the queued endpoint; the "
        "synchronous one cannot finish inside a proxy's request timeout"
    )

    # The synchronous endpoint may still be *read* from - that is how the
    # stored analysis is fetched - but it must not be POSTed to.
    synchronous_posts = re.findall(
        r'api\.POST\(\s*"/assets/\{ticker\}/analysis"', source
    )
    assert not synchronous_posts, (
        "the synchronous analysis endpoint is being POSTed to again; a run that "
        "takes minutes will be killed by the proxy and its result discarded"
    )


def test_the_queued_job_is_polled_to_a_terminal_state() -> None:
    """Queuing without polling would leave the button spinning forever."""
    source = read(ASSET_DETAIL)

    assert '"/jobs/{job_id}"' in source, "the queued job must be polled"
    for terminal in ("succeeded", "failed", "dead"):
        assert terminal in source, (
            f"the poll must recognise {terminal!r}; a state it does not handle "
            "leaves the interface waiting on a job that has already stopped"
        )


def test_an_html_error_body_is_not_shown_as_the_message() -> None:
    """A proxy answering instead of the API returns a page, not a message.
    Rendered as-is it filled the panel with a thousand characters of markup."""
    source = read(CLIENT)

    assert "looksLikeMarkup" in source, (
        "errorMessage must reject a markup body rather than render it as text"
    )
    # And it must be applied on the branch that receives one: `openapi-fetch`
    # hands a non-JSON body over as a plain string.
    assert re.search(r"looksLikeMarkup\(error\)", source), (
        "the markup check must guard the string branch, which is where a proxy's "
        "HTML page arrives"
    )


def test_the_language_switch_waits_for_both_languages() -> None:
    """Translation runs as a job *after* the analysis, so for a stretch there is
    exactly one language. A switch offered then would change to nothing - the
    reader presses it, nothing happens, and the control has taught them not to
    trust it."""
    source = read(ASSET_DETAIL)

    assert "bothLanguagesReady" in source, (
        "the language switch must be gated on a second language actually existing"
    )
    assert re.search(r"bothLanguagesReady\s*&&\s*\(\s*\n\s*<LanguageSwitch", source), (
        "the gate must guard the switch itself, not merely be computed"
    )


def test_a_finished_translation_re_renders_rather_than_needing_a_reload() -> None:
    """The event is what makes the switch appear on a page already open."""
    source = read(FRONTEND / "realtime" / "useEvents.ts")

    assert "translation_ready" in source, "the translation event must be handled"
    # Matched to the end of the line rather than to the first `]`, which is the
    # end of the *first* query key rather than the end of the list.
    match = re.search(r"^\s*translation_ready:\s*(.+)$", source, re.M)
    assert match and '["analysis"]' in match.group(1), (
        "translation_ready must invalidate the analysis query, or the page keeps "
        "showing the version it fetched before the rendering existed"
    )
