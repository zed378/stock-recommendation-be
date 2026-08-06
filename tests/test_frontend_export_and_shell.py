"""The PDF export, and the shell that carries the navigation.

Static checks, in the Python suite, for the same reason as the other frontend
guards: it is the suite that runs on every change.

The disclaimer one is not a style rule. Section 13 requires the disclaimer on
output, and a PDF is the single artefact that leaves the platform completely -
it gets emailed, printed and forwarded with none of the surrounding interface
that carries the caveats. An export that drops it publishes model-generated
investment prose with nothing attached saying what it is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
EXPORT = FRONTEND / "export" / "analysisPdf.ts"
ASSET_DETAIL = FRONTEND / "pages" / "AssetDetail.tsx"
SIDEBAR = FRONTEND / "components" / "Sidebar.tsx"
NAVIGATION = FRONTEND / "components" / "navigation.ts"


def read(path: Path) -> str:
    if not path.exists():  # pragma: no cover - a move, not a regression
        pytest.fail(f"{path} is missing; update this test to follow it")
    return path.read_text(encoding="utf-8")


# --- the export --------------------------------------------------------------


def test_the_export_carries_the_disclaimer() -> None:
    """Section 13. The one artefact that travels without the interface around
    it is the one that most needs to say what it is."""
    source = read(EXPORT)

    assert "disclaimerBody" in source, (
        "the exported PDF must contain the disclaimer text, not merely a heading"
    )
    assert re.search(r"write\(L\.disclaimerBody", source), (
        "the disclaimer body must actually be written into the document"
    )


def test_the_export_runs_in_the_browser() -> None:
    """Asked for explicitly: the render cost belongs on the reader's machine.
    A server-side renderer would also put a layout engine inside a request,
    which is the shape of mistake that made the analysis time out behind a
    proxy."""
    source = read(EXPORT)

    assert "await import(\"jspdf\")" in source, (
        "jspdf must be imported dynamically so it stays out of the main bundle"
    )
    backend = Path(__file__).resolve().parents[1] / "src" / "aidss"
    offenders = [
        path.name
        for path in backend.rglob("*.py")
        if "reportlab" in path.read_text(encoding="utf-8")
        or "weasyprint" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"PDF rendering appeared on the server in: {offenders}"


def test_the_export_covers_the_recommendation_and_the_strategy() -> None:
    """Both were named in the request, and each is a separate section that a
    partial implementation would quietly leave out."""
    source = read(EXPORT)

    assert "input.recommendation" in source
    assert "input.strategy" in source
    assert "input.agents" in source, "the evidence beneath the conclusion, too"


def test_the_export_prints_both_sides_of_the_strategy() -> None:
    """The asymmetry is the product. An asset worth keeping but not worth
    buying today is a real and common situation, and a document showing only
    the reader's own side hides exactly that - which is also why the screen
    shows both. A PDF is read by people other than whoever exported it, and
    their positions are not the same."""
    source = read(EXPORT)

    assert "not_holding" in source and "holding" in source
    for part in ("conditions", "invalidated_if", "reference_levels"):
        assert part in source, (
            f"{part} must reach the document; a stance with no stated way to be "
            "wrong is the kind people hold longest"
        )


def test_a_stance_is_printed_as_words_rather_than_as_its_enum_value() -> None:
    """`entry_candidate` is a value, not a phrase. The naming rule that keeps
    it from reading as "buy" only holds if the document spells it out the same
    careful way the screen does."""
    source = read(EXPORT)

    assert "STANCE_LABELS" in source
    assert "no_basis_to_enter" in source, "the stance the whole distinction rests on"


def test_the_export_writes_text_rather_than_an_image() -> None:
    """A screenshot would be simpler and would produce a file nobody can
    search, copy a figure out of, or read with a screen reader."""
    source = read(EXPORT)

    assert "doc.text(" in source
    for image_api in ("html2canvas", "addImage", "toDataURL"):
        assert image_api not in source, (
            f"{image_api} suggests the page is being captured rather than written"
        )


def test_the_export_button_waits_for_something_to_export() -> None:
    source = read(ASSET_DETAIL)

    # Located by the label and read backwards, rather than matched with one
    # expression. JSX is full of braces, so any `[^}]*` between the guard and
    # the label stops at the first attribute and matches nothing.
    at = source.index('t("export.pdf")')
    preceding = source[max(0, at - 400) : at]
    assert "result && !running" in preceding, (
        "the export button must be gated on an analysis existing; a button that "
        "produces an empty document teaches the reader it does not work"
    )


# --- the shell ---------------------------------------------------------------


def test_the_navigation_data_is_not_in_a_component_module() -> None:
    """A module exporting both a hook and a component cannot be hot-reloaded.

    Not a style preference and not the linter being fussy: this project has
    already lost an afternoon to it, when the i18n context did the same thing
    and the app white-screened on every edit.
    """
    assert NAVIGATION.exists(), "the navigation data must live in its own module"
    sidebar = read(SIDEBAR)

    assert "useNavigationGroups" not in sidebar or "import" in sidebar.split(
        "useNavigationGroups"
    )[0], "the hook must be imported into the component module, not defined in it"
    assert not re.search(r"^export function use[A-Z]", sidebar, re.M), (
        "Sidebar.tsx exports both a hook and components again; Fast Refresh "
        "replaces the module and every consumer ends up holding a different one"
    )


def test_every_admin_section_has_an_address() -> None:
    """As tab state they had none: an admin could not bookmark the news
    sources, link a colleague to the audit log, or reload without landing back
    on the overview."""
    navigation = read(NAVIGATION)
    routes = read(FRONTEND / "App.tsx")

    assert '"/admin/:section"' in routes, "the admin section must be part of the route"
    for section in (
        "users",
        "news",
        "issuers",
        "queue",
        "providers",
        "settings",
        "budget",
        "audit",
    ):
        assert f'"/admin/{section}"' in navigation, f"/admin/{section} is not linked"
