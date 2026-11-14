"""Encrypted credential storage (ADR-014, ADR-029).

Why this is not `aidss.security.secrets`: that module derives its Fernet key
from `AIDSS_JWT_SECRET`, which the analysis API also holds. Reusing it would
tie the safety of the exchange key to a secret the analysis API can read, so a
database dump plus that secret would recover the key. Here the key is its own
random value, read from a file secret on the host and never from the
environment.

A credential that cannot be decrypted is an error, never `None`: a lost master
key must stop trading loudly, not look like "no credential configured".
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aidss_trader.db.models import Credential


class MasterKeyUnavailable(RuntimeError):
    """The master key file is missing, unreadable, or not a valid key."""


class CredentialUnreadable(RuntimeError):
    """Stored ciphertext cannot be decrypted with the current master key."""


def load_master_key(path: Path | None) -> Fernet:
    if path is None:
        raise MasterKeyUnavailable("AIDSS_TRADER_MASTER_KEY_FILE is not set")
    try:
        raw = path.read_bytes().strip()
    except OSError as exc:
        raise MasterKeyUnavailable(f"cannot read the master key file: {exc.strerror}") from exc
    try:
        return Fernet(raw)
    except (ValueError, TypeError) as exc:
        # The message deliberately says nothing about the content.
        raise MasterKeyUnavailable("the master key file does not hold a valid key") from exc


def generate_master_key_file(path: Path) -> None:
    """Write a new random key. Refuses to overwrite: replacing it strands every credential."""
    if path.exists():
        raise FileExistsError(f"{path} already exists; refusing to overwrite a master key")
    # O_EXCL closes the race between the check above and the write; 0o600 keeps
    # it readable only by the owning account where the OS honours modes.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(Fernet.generate_key())


def _hint(secret: str) -> str:
    return secret[-4:] if len(secret) > 8 else "*" * len(secret)


class CredentialStore:
    def __init__(self, session: Session, fernet: Fernet) -> None:
        self._session = session
        self._fernet = fernet

    def put(
        self, kind: str, *, key: str, secret: str = "", now: datetime | None = None
    ) -> uuid.UUID:
        """Store a credential as the active one for `kind`, retiring the previous.

        One transaction, so there is never a moment with no valid credential
        (the old one is retired only together with the new one being added).
        """
        now = now or datetime.now(UTC)
        ciphertext = self._fernet.encrypt(json.dumps({"key": key, "secret": secret}).encode())
        self._session.execute(
            update(Credential)
            .where(Credential.kind == kind, Credential.active.is_(True))
            .values(active=False, retired_at=now)
        )
        row = Credential(
            kind=kind,
            ciphertext=ciphertext.decode(),
            hint=_hint(key),
            active=True,
            created_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def get(self, kind: str) -> tuple[str, str] | None:
        """Decrypt the active credential, or None if none was ever stored."""
        row = self._session.scalar(
            select(Credential).where(Credential.kind == kind, Credential.active.is_(True))
        )
        if row is None:
            return None
        try:
            payload = json.loads(self._fernet.decrypt(row.ciphertext.encode()))
        except InvalidToken as exc:
            raise CredentialUnreadable(
                f"the stored {kind} credential cannot be decrypted; the master key changed "
                "since it was saved. Re-enter the credential."
            ) from exc
        return payload["key"], payload["secret"]

    def describe(self, kind: str) -> dict[str, object] | None:
        """What an API may show: a hint and test status, never the value."""
        row = self._session.scalar(
            select(Credential).where(Credential.kind == kind, Credential.active.is_(True))
        )
        if row is None:
            return None
        return {
            "kind": row.kind,
            "hint": row.hint,
            "created_at": row.created_at,
            "last_test_at": row.last_test_at,
            "last_test_ok": row.last_test_ok,
        }

    def readable(self, kind: str) -> bool | None:
        """None when none is stored; otherwise whether the master key can still decrypt it.
        Nothing decrypted leaves this method."""
        try:
            return None if self.get(kind) is None else True
        except CredentialUnreadable:
            return False

    def mark_test(self, kind: str, ok: bool, now: datetime | None = None) -> None:
        self._session.execute(
            update(Credential)
            .where(Credential.kind == kind, Credential.active.is_(True))
            .values(last_test_at=now or datetime.now(UTC), last_test_ok=ok)
        )
        self._session.flush()

    def remove(self, kind: str, now: datetime | None = None) -> bool:
        """Retire the active credential and wipe its ciphertext. The Trader's database role has
        no DELETE, so the row stays, emptied, as the record that a credential existed."""
        result = self._session.execute(
            update(Credential)
            .where(Credential.kind == kind, Credential.active.is_(True))
            .values(active=False, retired_at=now or datetime.now(UTC), ciphertext="")
        )
        self._session.flush()
        return bool(result.rowcount)
