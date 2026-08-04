"""Password hashing with bcrypt (Section 13)."""

from __future__ import annotations

import bcrypt

#: bcrypt truncates input at 72 bytes. Rejecting longer input is safer than
#: silently ignoring the tail, which would make two different passwords
#: interchangeable.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10


class PasswordPolicyError(ValueError):
    """The password does not meet the minimum policy."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # A corrupt or unrecognised hash fails closed rather than crashing the
        # login path.
        return False
