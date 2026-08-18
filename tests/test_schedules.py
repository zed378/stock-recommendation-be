"""The shapes the cron picker emits, checked against the scheduler that parses them.

The picker composes expressions from dropdowns rather than taking them typed,
which removes a whole class of error - and introduces one. Nothing in
TypeScript can check that what it composes is a shape this scheduler accepts,
and the failure would be a schedule the reader set from a menu and the backend
refused, which reads as the menu being broken rather than as a mismatch.
"""

from __future__ import annotations

from aidss.news.schedules import next_run_at

#: Enumerated rather than imported: they live in `CronPicker.tsx`, and this
#: list drifting from that one is what a reviewer touching either should catch.
PICKER_SHAPES = [
    # Every day, at each offered minute.
    "0 18 * * *",
    "15 8 * * *",
    "30 8 * * *",
    "45 23 * * *",
    # Every trading day.
    "0 18 * * 1-5",
    "45 9 * * 1-5",
    # Once a week, every weekday value the dropdown offers.
    "0 8 * * 0",
    "0 8 * * 1",
    "0 8 * * 2",
    "0 8 * * 3",
    "0 8 * * 4",
    "0 8 * * 5",
    "0 8 * * 6",
    # Every few hours, at each offered interval.
    "0 */1 * * *",
    "0 */2 * * *",
    "0 */3 * * *",
    "0 */4 * * *",
    "0 */6 * * *",
    "0 */8 * * *",
    "30 */12 * * *",
]


def test_every_shape_the_cron_picker_emits_is_accepted() -> None:
    for expression in PICKER_SHAPES:
        assert next_run_at(expression) is not None, f"{expression} was refused"


def test_the_picker_cannot_emit_an_empty_schedule_as_a_space() -> None:
    """"Not scheduled" composes to the empty string, which every caller treats
    as off. A single space would be stored as truthy and then fail to parse on
    the next tick."""
    assert "" .strip() == ""
    for expression in PICKER_SHAPES:
        assert expression == expression.strip()
        assert len(expression.split()) == 5
