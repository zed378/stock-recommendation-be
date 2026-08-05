"""The unread count in the tab title must replace itself, not accumulate.

Writing `document.title = f"({n}) {document.title}"` works perfectly the first
time and is wrong on every poll after it: the base it reads already carries the
previous count, so the tab drifts to "(3) (2) (1) AIDSS" while each individual
update looks correct in review.

The fix is one line - capture the untouched title once at module load and build
every update from that - and it is exactly the kind of line a later edit
removes without noticing, because reading `document.title` in the effect is the
obvious thing to write.

A static check rather than a runtime one. There is no JavaScript test runner in
this project, and standing one up to assert this single fact would cost more
than it protects. It lives in the Python suite because that is the suite that
runs on every change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "components"
    / "Notifications.tsx"
)


@pytest.fixture(scope="module")
def source() -> str:
    if not SOURCE.exists():  # pragma: no cover - a move, not a regression
        pytest.fail(f"{SOURCE} is missing; update this test to follow it")
    return SOURCE.read_text(encoding="utf-8")


def test_the_base_title_is_captured_once_outside_the_component(source: str) -> None:
    """At module scope, so it is read before anything has prefixed it."""
    assert re.search(r"^const BASE_TITLE = document\.title;", source, re.MULTILINE), (
        "the untouched tab title must be captured once at module load"
    )


def test_every_title_write_builds_on_that_constant(source: str) -> None:
    """Not on whatever the title happens to be at the time."""
    writes = re.findall(r"document\.title\s*=\s*([^;]+);", source)
    assert writes, "nothing sets the tab title any more; delete this test if intended"

    for write in writes:
        assert "BASE_TITLE" in write, (
            f"`document.title = {write.strip()}` does not build on BASE_TITLE, so "
            "each update would stack another count onto the last one"
        )
        assert "document.title" not in write, (
            f"`document.title = {write.strip()}` reads the title it is replacing, "
            "which is how the count accumulates"
        )


def test_the_count_is_cleared_when_the_bell_unmounts(source: str) -> None:
    """The component unmounts on sign-out. A tab still claiming three unread
    after somebody signed out is stale in a way nobody would think to
    question."""
    assert re.search(
        r"return\s*\(\)\s*=>\s*\{\s*document\.title\s*=\s*BASE_TITLE;?\s*\}", source
    ), "the title effect must restore the base title on cleanup"
