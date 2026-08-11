

def test_every_event_has_a_subject() -> None:
    """`SUBJECTS` is a plain dict lookup, so a member added without one raises
    KeyError at send time - inside a notification, which is the one place that
    is wrapped in a guard and logged as a warning rather than surfaced. The
    feature then looks like it silently does not notify.

    Measured: adding SCREEN_MATCHED did exactly this, and every scheduled
    screen failed at the point of announcing what it had found.
    """
    from aidss.reporting.notifications import SUBJECTS, NotificationEvent

    missing = [event.value for event in NotificationEvent if event not in SUBJECTS]

    assert missing == [], f"these events would raise when sent: {missing}"
