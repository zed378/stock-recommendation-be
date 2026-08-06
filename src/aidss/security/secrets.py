"""Encrypting credentials the application itself has to be able to read.

**The trade-off, stated plainly.** Provider API keys used to live only in the
environment, which meant the database could be dumped without leaking one. They
now live in `ai_providers` so an operator can add a model from the admin screen
instead of editing `.env` and redeploying - and that necessarily means the
application can decrypt them, so a database dump *plus* the application secret
is enough to recover every key.

That is strictly weaker than a secret manager and strictly stronger than the
plaintext column this replaces. It is the price of configurable providers, and
the mitigations are the ordinary ones: the key never leaves the server (the API
returns a masked hint, never the value), rotating `AIDSS_JWT_SECRET` renders
stored keys unreadable rather than silently wrong, and an operator who wants
the stronger property can still leave the column empty and use the environment.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from aidss.config import Settings, get_settings


class SecretUnreadable(RuntimeError):
    """The stored ciphertext cannot be decrypted with the current secret.

    Raised rather than returning None, because the two causes need different
    answers: a rotated `AIDSS_JWT_SECRET` means every stored key must be
    re-entered, and silently treating them as absent would look like a provider
    that simply stopped authenticating.
    """


def _cipher(settings: Settings | None = None) -> Fernet:
    settings = settings or get_settings()
    # Derived rather than used directly: Fernet needs 32 url-safe base64 bytes
    # and the JWT secret is an arbitrary string. Salted with a constant so the
    # same secret does not produce the same key for two different purposes.
    digest = hashlib.sha256(f"aidss.provider-credentials:{settings.jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, settings: Settings | None = None) -> str:
    return _cipher(settings).encrypt(value.encode()).decode()


def decrypt_secret(ciphertext: str, settings: Settings | None = None) -> str:
    try:
        return _cipher(settings).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnreadable(
            "A stored credential could not be decrypted. This normally means "
            "AIDSS_JWT_SECRET changed since it was saved; re-enter the key on "
            "the provider."
        ) from exc


def hint(value: str) -> str:
    """What is safe to show back.

    Enough to recognise which key is stored, never enough to use it. Short
    values are hidden entirely rather than mostly revealed.
    """
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-4:]}"
