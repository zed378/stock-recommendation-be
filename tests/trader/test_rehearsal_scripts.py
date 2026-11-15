"""Static safety checks for host-hardening and restore rehearsal shell scripts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REHEARSE_ISOLATION = ROOT / "deploy" / "trader" / "rehearse_isolation.sh"
REHEARSE_RESTORE = ROOT / "deploy" / "trader" / "rehearse_restore.sh"


def test_rehearsal_scripts_exist_and_use_trap_cleanup() -> None:
    for script in (REHEARSE_ISOLATION, REHEARSE_RESTORE):
        text = script.read_text(encoding="utf-8")
        assert "set -eu" in text, f"{script.name} must enable set -eu"
        assert re.search(r"trap\s+cleanup\s+EXIT", text), (
            f"{script.name} must register a trap cleanup EXIT handler"
        )
        assert "DROP DATABASE IF EXISTS" in text, (
            f"{script.name} must drop its scratch database in cleanup"
        )

    iso_text = REHEARSE_ISOLATION.read_text(encoding="utf-8")
    assert "DROP ROLE IF EXISTS aidss_app" in iso_text, (
        "rehearse_isolation.sh must drop cluster-wide aidss_app in cleanup when created"
    )


def test_rehearsal_scripts_contain_no_literal_passwords_or_secrets() -> None:
    secret_patterns = [
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bPGPASSWORD\s*="),
        re.compile(r"PASSWORD\s+'(?!%s)[^']+'", re.IGNORECASE),
    ]
    for script in (REHEARSE_ISOLATION, REHEARSE_RESTORE):
        text = script.read_text(encoding="utf-8")
        for pat in secret_patterns:
            assert not pat.search(text), f"{script.name} matched forbidden pattern {pat.pattern!r}"


def test_rehearse_restore_supports_full_flag() -> None:
    text = REHEARSE_RESTORE.read_text(encoding="utf-8")
    assert "--full" in text
    assert "-n trading" in text


def test_rehearsal_scripts_restrict_dump_permissions() -> None:
    """The dump of a full database must not be readable by other users on a shared host."""
    for script in (REHEARSE_ISOLATION, REHEARSE_RESTORE):
        text = script.read_text(encoding="utf-8")
        assert re.search(r"^umask 077$", text, re.MULTILINE), f"{script.name} must set umask 077"
        assert text.index("umask 077") < text.index("docker exec \"$CONTAINER\" pg_dump"), (
            f"{script.name} must set umask before the first pg_dump"
        )


def test_isolation_denial_check_requires_permission_denied() -> None:
    """A generic psql failure (bad connection, missing table) must not count as a refusal."""
    text = REHEARSE_ISOLATION.read_text(encoding="utf-8")
    assert "permission denied" in text
    assert re.search(r"\*\"permission denied\"\*\)", text), "denial must be matched on the message"
