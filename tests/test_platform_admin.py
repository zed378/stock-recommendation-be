"""Operator settings, admin-created accounts, and configurable AI providers.

Three features that share one property: each moves a decision out of the
environment and into the running system, so each needs a guard the environment
used to provide for free.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from aidss.db.base import get_sessionmaker
from aidss.db.models import AIProviderConfig, SchedulerJob, User, UserRole
from aidss.platform.settings import (
    NEWS_SWEEP_CRON,
    REGISTRATION_OPEN,
    all_settings,
    get_setting,
    set_setting,
)
from aidss.security.secrets import SecretUnreadable, decrypt_secret, encrypt_secret, hint

# --- the settings store -----------------------------------------------------


def test_an_unset_key_reads_its_default(session) -> None:
    """An empty table is a working system: a fresh install needs no seeding."""
    assert get_setting(session, REGISTRATION_OPEN) is True
    assert get_setting(session, NEWS_SWEEP_CRON) == ""


def test_false_is_stored_and_read_back_as_false(session) -> None:
    """The reason values are wrapped rather than stored bare. A JSON column
    holding `false` and one holding SQL NULL are easy to confuse through an
    ORM, and "registration is closed" must never read as "nobody set this"."""
    set_setting(session, REGISTRATION_OPEN, False)

    assert get_setting(session, REGISTRATION_OPEN) is False
    assert all_settings(session)[REGISTRATION_OPEN] is False


def test_an_unknown_key_is_refused(session) -> None:
    """Not a general key-value store. A typo would otherwise be stored happily
    and read back as its default forever."""
    with pytest.raises(KeyError):
        set_setting(session, "registration_opne", True)
    with pytest.raises(KeyError):
        get_setting(session, "whatever")


# --- closing registration ---------------------------------------------------


def test_registration_is_refused_when_closed(client, session) -> None:
    db = get_sessionmaker()()
    try:
        db.add(User(email="someone@example.com", password_hash="x"))
        set_setting(db, REGISTRATION_OPEN, False)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/auth/register", json={"email": "new@example.com", "password": "correct-horse-battery"}
    )

    assert response.status_code == 403


def test_a_closed_platform_does_not_reveal_who_is_registered(client) -> None:
    """The gate is checked before the email is looked up. A 409 for an existing
    address and a 403 for a new one would enumerate the user list through a
    door that is supposed to be shut."""
    db = get_sessionmaker()()
    try:
        db.add(User(email="known@example.com", password_hash="x"))
        set_setting(db, REGISTRATION_OPEN, False)
        db.commit()
    finally:
        db.close()

    known = client.post(
        "/auth/register", json={"email": "known@example.com", "password": "correct-horse-battery"}
    )
    unknown = client.post(
        "/auth/register",
        json={"email": "unknown@example.com", "password": "correct-horse-battery"},
    )

    assert known.status_code == unknown.status_code == 403
    assert known.json() == unknown.json()


def test_the_first_account_is_always_allowed(client, session) -> None:
    """A switch that can brick the platform is a switch nobody should be
    offered. An operator who closes registration on an empty instance must
    still be able to create the first account."""
    set_setting(session, REGISTRATION_OPEN, False)
    session.commit()

    response = client.post(
        "/auth/register", json={"email": "first@example.com", "password": "correct-horse-battery"}
    )

    assert response.status_code == 201


def test_registration_still_works_when_open(client) -> None:
    response = client.post(
        "/auth/register", json={"email": "open@example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 201


# --- accounts created by an administrator -----------------------------------


def test_an_admin_can_create_an_account_while_registration_is_closed(
    client, admin_headers
) -> None:
    """The reason this route exists: an operator who closed the door still
    needs to let people in."""
    db = get_sessionmaker()()
    try:
        set_setting(db, REGISTRATION_OPEN, False)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/admin/users",
        headers=admin_headers,
        json={"email": "invited@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "invited@example.com"
    assert response.json()["role"] == "investor"


def test_creating_an_account_is_the_one_route_that_can_mint_an_admin(
    client, admin_headers
) -> None:
    response = client.post(
        "/admin/users",
        headers=admin_headers,
        json={
            "email": "second-admin@example.com",
            "password": "correct-horse-battery",
            "role": "admin",
        },
    )

    assert response.status_code == 201
    db = get_sessionmaker()()
    try:
        created = db.scalar(select(User).where(User.email == "second-admin@example.com"))
        assert created.role is UserRole.ADMIN
    finally:
        db.close()


def test_a_non_admin_cannot_create_accounts(client, auth_headers) -> None:
    response = client.post(
        "/admin/users",
        headers=auth_headers,
        json={"email": "nope@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 403


def test_a_duplicate_email_is_refused(client, admin_headers) -> None:
    body = {"email": "dupe@example.com", "password": "correct-horse-battery"}
    assert client.post("/admin/users", headers=admin_headers, json=body).status_code == 201
    assert client.post("/admin/users", headers=admin_headers, json=body).status_code == 409


# --- provider credentials ---------------------------------------------------


def test_a_credential_survives_a_round_trip() -> None:
    ciphertext = encrypt_secret("sk-secret-value-1234")
    assert ciphertext != "sk-secret-value-1234"
    assert decrypt_secret(ciphertext) == "sk-secret-value-1234"


def test_a_rotated_secret_is_an_error_rather_than_a_wrong_answer() -> None:
    """The two causes need different answers. Treating an undecryptable key as
    absent would look like a provider that quietly stopped authenticating."""
    from aidss.config import Settings

    ciphertext = encrypt_secret("sk-secret-value-1234")
    with pytest.raises(SecretUnreadable):
        decrypt_secret(ciphertext, Settings(jwt_secret="a-completely-different-secret"))


def test_the_hint_identifies_without_revealing() -> None:
    assert hint("sk-abcdefghijklmnop") == "sk-…mnop"
    # A short value is hidden entirely rather than mostly revealed.
    assert set(hint("sk-12")) == {"•"}


def test_the_api_never_returns_the_credential(client, admin_headers) -> None:
    created = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={
            "name": "primary",
            "base_url": "https://api.example.com/v1",
            "default_model": "some-model",
            "api_key": "sk-super-secret-value",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert "sk-super-secret-value" not in str(body)
    assert body["api_key_hint"] == hint("sk-super-secret-value")

    listed = client.get("/admin/ai-providers", headers=admin_headers)
    assert "sk-super-secret-value" not in listed.text


def test_omitting_the_key_on_update_keeps_it(client, admin_headers) -> None:
    """What an admin editing the model name expects."""
    created = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "keeper", "api_key": "sk-keep-me-please"},
    ).json()

    client.patch(
        f"/admin/ai-providers/{created['id']}",
        headers=admin_headers,
        json={"name": "keeper", "default_model": "changed"},
    )

    db = get_sessionmaker()()
    try:
        row = db.scalar(select(AIProviderConfig).where(AIProviderConfig.name == "keeper"))
        assert decrypt_secret(row.api_key_ciphertext) == "sk-keep-me-please"
        assert row.default_model == "changed"
    finally:
        db.close()


def test_an_empty_key_on_update_clears_it(client, admin_headers) -> None:
    """What a switch to a local model needing no key expects. Distinct from
    omitting it, and collapsing the two would make one impossible to say."""
    created = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "clearable", "api_key": "sk-remove-me"},
    ).json()

    client.patch(
        f"/admin/ai-providers/{created['id']}",
        headers=admin_headers,
        json={"name": "clearable", "api_key": ""},
    )

    db = get_sessionmaker()()
    try:
        row = db.scalar(select(AIProviderConfig).where(AIProviderConfig.name == "clearable"))
        assert row.api_key_ciphertext is None
        assert row.api_key_hint is None
    finally:
        db.close()


def test_the_audit_trail_never_carries_the_credential(client, admin_headers) -> None:
    client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "audited", "api_key": "sk-must-not-be-logged"},
    )

    logs = client.get("/audit-logs", headers=admin_headers, params={"entity": "ai_providers"})

    assert logs.status_code == 200
    assert "sk-must-not-be-logged" not in logs.text
    assert '"has_api_key": true' in logs.text.replace("True", "true").lower() or any(
        row["after"].get("has_api_key") for row in logs.json()["items"]
    )


def test_an_unknown_adapter_is_refused(client, admin_headers) -> None:
    """A row naming an adapter that does not exist is skipped at build time,
    so it would sit on the screen looking configured and never be used."""
    response = client.post(
        "/admin/ai-providers",
        headers=admin_headers,
        json={"name": "bogus", "adapter_name": "not-a-real-adapter"},
    )
    assert response.status_code == 422


def test_a_duplicate_provider_name_is_refused(client, admin_headers) -> None:
    body = {"name": "same-name"}
    assert client.post("/admin/ai-providers", headers=admin_headers, json=body).status_code == 201
    assert client.post("/admin/ai-providers", headers=admin_headers, json=body).status_code == 409


def test_each_provider_reaches_its_own_endpoint(session) -> None:
    """The point of the whole change. Every row used to be built from the
    environment, so several rows could differ only by model name against one
    endpoint - which is not multi-provider, it is one provider listed twice,
    and the fallback chain had nowhere to fail over to."""
    from aidss.config import Settings
    from aidss.llm.provisioning import provider_from_row

    row = AIProviderConfig(
        name="its-own",
        adapter_name="openai_compatible",
        base_url="https://somewhere-else.example.com/v1",
        default_model="a-different-model",
        api_key_ciphertext=encrypt_secret("sk-row-specific"),
    )
    settings = Settings(ai_base_url="https://the-environment.example.com/v1")

    provider = provider_from_row(row, settings)

    assert provider._base_url == "https://somewhere-else.example.com/v1"
    assert provider._api_key == "sk-row-specific"
    assert provider._chat_model == "a-different-model"


def test_a_row_that_overrides_only_the_model_still_uses_the_environment(session) -> None:
    """Field by field rather than all-or-nothing, so a deployment configured
    the old way keeps working when somebody adds a second model."""
    from aidss.config import Settings
    from aidss.llm.provisioning import provider_from_row

    row = AIProviderConfig(name="model-only", default_model="just-the-model")
    settings = Settings(ai_base_url="https://the-environment.example.com/v1")

    provider = provider_from_row(row, settings)

    assert provider._base_url == "https://the-environment.example.com/v1"
    assert provider._chat_model == "just-the-model"


# --- the news sweep schedule ------------------------------------------------


def test_no_cron_means_no_sweep(session) -> None:
    """Off by default. Reading somebody else's feeds on a timer nobody asked
    for is not a sensible default."""
    from aidss.jobs.handlers import enqueue_due_news_sweep

    assert enqueue_due_news_sweep(session)["disabled"] is True


def test_setting_a_cron_schedules_rather_than_fires_immediately(session) -> None:
    from aidss.jobs.handlers import enqueue_due_news_sweep

    set_setting(session, NEWS_SWEEP_CRON, "0 */2 * * *")

    result = enqueue_due_news_sweep(session, now=datetime(2026, 8, 6, 9, 30, tzinfo=UTC))

    assert result["enqueued"] == 0
    # Cron is read in exchange time (WIB, UTC+7), so an even Jakarta hour is an
    # odd UTC one. 09:30 UTC is 16:30 in Jakarta; the next even hour there is
    # 18:00, which is 11:00 UTC.
    assert result["scheduled_for"].startswith("2026-08-06T11:00")


def test_the_sweep_is_queued_once_it_is_due(session) -> None:
    from aidss.jobs.handlers import enqueue_due_news_sweep

    set_setting(session, NEWS_SWEEP_CRON, "0 */2 * * *")
    enqueue_due_news_sweep(session, now=datetime(2026, 8, 6, 9, 30, tzinfo=UTC))

    result = enqueue_due_news_sweep(session, now=datetime(2026, 8, 6, 11, 1, tzinfo=UTC))

    assert result["enqueued"] == 1


def test_changing_the_cron_re_anchors_the_next_run(session) -> None:
    """A new expression must not inherit a due time computed from the old one."""
    from aidss.jobs.handlers import enqueue_due_news_sweep

    set_setting(session, NEWS_SWEEP_CRON, "0 */6 * * *")
    enqueue_due_news_sweep(session, now=datetime(2026, 8, 6, 9, 30, tzinfo=UTC))

    set_setting(session, NEWS_SWEEP_CRON, "*/15 * * * *")
    result = enqueue_due_news_sweep(session, now=datetime(2026, 8, 6, 9, 31, tzinfo=UTC))

    assert result["scheduled_for"].startswith("2026-08-06T09:45")


def test_clearing_the_cron_deactivates_rather_than_deletes(session) -> None:
    from aidss.jobs.handlers import enqueue_due_news_sweep

    set_setting(session, NEWS_SWEEP_CRON, "0 * * * *")
    enqueue_due_news_sweep(session)

    set_setting(session, NEWS_SWEEP_CRON, "")
    enqueue_due_news_sweep(session)

    row = session.scalar(select(SchedulerJob).where(SchedulerJob.job_type == "news.sweep"))
    assert row is not None, "the schedule's history must survive being switched off"
    assert row.is_active is False


def test_an_unusable_cron_is_refused_by_the_endpoint(client, admin_headers) -> None:
    """Validated when it is set, not discovered by a scheduler at 3am where the
    failure is a sweep that silently never runs."""
    response = client.patch(
        "/admin/settings", headers=admin_headers, json={"news_sweep_cron": "not a cron"}
    )
    assert response.status_code == 422


def test_a_partial_update_leaves_the_other_setting_alone(client, admin_headers) -> None:
    """Otherwise changing the news schedule would close registration."""
    client.patch("/admin/settings", headers=admin_headers, json={"registration_open": False})

    client.patch("/admin/settings", headers=admin_headers, json={"news_sweep_cron": "0 * * * *"})

    body = client.get("/admin/settings", headers=admin_headers).json()
    assert body["registration_open"] is False
    assert body["news_sweep_cron"] == "0 * * * *"
