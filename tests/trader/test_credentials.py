from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from aidss_trader.credentials import (
    CredentialStore,
    CredentialUnreadable,
    MasterKeyUnavailable,
    generate_master_key_file,
    load_master_key,
)

SENTINEL_KEY = "TESTKEY-0000-1111-2222-sentinelkey"
SENTINEL_SECRET = "testsecret-sentinel-0123456789abcdef"


def test_roundtrip_and_ciphertext_is_not_plaintext(session, fernet) -> None:
    store = CredentialStore(session, fernet)
    store.put("indodax", key=SENTINEL_KEY, secret=SENTINEL_SECRET)
    assert store.get("indodax") == (SENTINEL_KEY, SENTINEL_SECRET)
    raw = session.execute(text("SELECT ciphertext, hint FROM credential")).one()
    assert SENTINEL_KEY not in raw.ciphertext and SENTINEL_SECRET not in raw.ciphertext
    assert raw.hint == SENTINEL_KEY[-4:]


def test_describe_never_returns_the_value(session, fernet) -> None:
    store = CredentialStore(session, fernet)
    store.put("indodax", key=SENTINEL_KEY, secret=SENTINEL_SECRET)
    shown = repr(store.describe("indodax"))
    assert SENTINEL_KEY not in shown and SENTINEL_SECRET not in shown


def test_key_is_never_returned_by_describe_for_short_values(session, fernet) -> None:
    store = CredentialStore(session, fernet)
    store.put("telegram", key="abc", secret="")
    assert store.describe("telegram")["hint"] == "***"


def test_a_changed_master_key_makes_the_credential_unreadable(session, fernet) -> None:
    CredentialStore(session, fernet).put("indodax", key=SENTINEL_KEY, secret=SENTINEL_SECRET)
    other = CredentialStore(session, Fernet(Fernet.generate_key()))
    with pytest.raises(CredentialUnreadable) as excinfo:
        other.get("indodax")
    assert SENTINEL_KEY not in str(excinfo.value)  # the error never echoes a value


def test_absent_credential_is_none_not_an_error(session, fernet) -> None:
    assert CredentialStore(session, fernet).get("indodax") is None


def test_rotation_leaves_exactly_one_active_credential(session, fernet) -> None:
    store = CredentialStore(session, fernet)
    store.put("indodax", key="old-key-value-0001", secret="old")
    store.put("indodax", key="new-key-value-0002", secret="new")
    assert store.get("indodax") == ("new-key-value-0002", "new")
    active = session.execute(text("SELECT count(*) FROM credential WHERE active = 1")).scalar()
    assert active == 1
    assert session.execute(text("SELECT count(*) FROM credential")).scalar() == 2


def test_the_master_key_is_not_derived_from_the_jwt_secret(session, monkeypatch, key_file) -> None:
    """ADR-014: changing AIDSS_JWT_SECRET must not affect the credential's readability."""
    store = CredentialStore(session, load_master_key(key_file))
    store.put("indodax", key=SENTINEL_KEY, secret=SENTINEL_SECRET)
    monkeypatch.setenv("AIDSS_JWT_SECRET", "a-completely-different-secret-0123456789")
    assert CredentialStore(session, load_master_key(key_file)).get("indodax") == (
        SENTINEL_KEY,
        SENTINEL_SECRET,
    )


def test_load_master_key_errors_do_not_echo_content(tmp_path: Path) -> None:
    bad = tmp_path / "bad.key"
    bad.write_bytes(b"this-is-not-a-fernet-key-but-it-is-sensitive")
    with pytest.raises(MasterKeyUnavailable) as excinfo:
        load_master_key(bad)
    assert "sensitive" not in str(excinfo.value)
    with pytest.raises(MasterKeyUnavailable):
        load_master_key(tmp_path / "missing.key")
    with pytest.raises(MasterKeyUnavailable):
        load_master_key(None)


def test_generate_master_key_refuses_to_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "new.key"
    generate_master_key_file(path)
    Fernet(path.read_bytes())  # a valid key
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate_master_key_file(path)
    assert path.read_bytes() == before
