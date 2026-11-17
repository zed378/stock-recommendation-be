"""Hermetic tests for deploy/trader/backup_offhost.sh using a stubbed --source-cmd."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "trader" / "backup_offhost.sh"


def _find_git_bash_and_env() -> tuple[str | None, dict[str, str]]:
    env = dict(os.environ)
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    git_usr_bin = Path(r"C:\Program Files\Git\usr\bin")
    if os.name == "nt" and git_bash.exists() and git_usr_bin.exists():
        env["PATH"] = f"{git_usr_bin}{os.pathsep}{env.get('PATH', '')}"
        return str(git_bash), env
    bash = shutil.which("bash")
    return bash, env


BASH, BASE_ENV = _find_git_bash_and_env()
OPENSSL = shutil.which("openssl", path=BASE_ENV.get("PATH"))
pytestmark = pytest.mark.skipif(
    BASH is None or OPENSSL is None,
    reason="needs bash and openssl",
)

FAKE_DUMP_SQL = (
    "SET statement_timeout = 0;\n"
    "CREATE ROLE aidss;\n"
    "CREATE ROLE trader_rw;\n"
    'COPY "public"."users" ("id", "email") FROM stdin;\n'
    "1\towner@example.com\n"
    "\\.\n"
    "-- PostgreSQL database cluster dump complete\n"
)


def _run_backup(
    dest: Path,
    *,
    source_cmd: str,
    passphrase: str = "correct-horse-battery-staple",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            BASH,  # type: ignore[list-item]
            str(SCRIPT),
            "--dest",
            str(dest),
            "--passphrase-fd",
            "0",
            "--source-cmd",
            source_cmd,
        ],
        input=(passphrase + "\n").encode(),
        env=env or BASE_ENV,
        capture_output=True,
        timeout=45,
    )


def test_encrypted_backup_roundtrip_sha256_and_no_passphrase_leak(tmp_path: Path) -> None:
    dest = tmp_path / "backups"
    sql_file = tmp_path / "dump.sql"
    sql_file.write_text(FAKE_DUMP_SQL, encoding="utf-8", newline="\n")
    passphrase = "test-passphrase-never-logged"

    done = _run_backup(
        dest,
        source_cmd=f"gzip -c '{sql_file.as_posix()}'",
        passphrase=passphrase,
    )
    assert done.returncode == 0, done.stderr

    enc_files = list(dest.glob("aidss-pg_dumpall-*.sql.gz.enc"))
    assert len(enc_files) == 1
    enc_file = enc_files[0]
    sha_file = Path(str(enc_file) + ".sha256")
    assert sha_file.exists()

    raw_enc = enc_file.read_bytes()
    assert b"CREATE ROLE" not in raw_enc
    assert passphrase.encode("utf-8") not in raw_enc
    assert passphrase.encode() not in done.stdout
    assert passphrase.encode() not in done.stderr
    assert passphrase not in sha_file.read_text(encoding="utf-8")

    expected_sha = hashlib.sha256(raw_enc).hexdigest()
    recorded_sha = sha_file.read_text(encoding="utf-8").split()[0]
    assert recorded_sha == expected_sha

    if os.name != "nt":
        assert stat.S_IMODE(enc_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(sha_file.stat().st_mode) == 0o600

    # Decrypting with the right passphrase reproduces the original SQL dump.
    dec = subprocess.run(
        [
            BASH,
            "-c",
            'if [ -x /usr/bin/openssl ]; then exec /usr/bin/openssl "$@"; '
            'else exec openssl "$@"; fi',
            "decrypt",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "600000",
            "-pass",
            "stdin",
            "-in",
            str(enc_file),
        ],
        input=(passphrase + "\n").encode(),
        env=BASE_ENV,
        capture_output=True,
        timeout=45,
    )
    assert dec.returncode == 0
    import gzip

    assert gzip.decompress(dec.stdout).decode("utf-8") == FAKE_DUMP_SQL

    # Wrong passphrase fails decryption.
    bad = subprocess.run(
        [
            BASH,
            "-c",
            'if [ -x /usr/bin/openssl ]; then exec /usr/bin/openssl "$@"; '
            'else exec openssl "$@"; fi',
            "decrypt",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "600000",
            "-pass",
            "stdin",
            "-in",
            str(enc_file),
        ],
        input=b"wrong-passphrase\n",
        env=BASE_ENV,
        capture_output=True,
        timeout=45,
    )
    assert bad.returncode != 0


def test_truncated_or_incomplete_dump_deletes_outputs_and_fails(tmp_path: Path) -> None:
    dest = tmp_path / "backups"
    bad_sql = tmp_path / "truncated.sql"
    bad_sql.write_text("CREATE ROLE aidss;\n-- incomplete", encoding="utf-8", newline="\n")

    done = _run_backup(dest, source_cmd=f"gzip -c '{bad_sql.as_posix()}'")
    assert done.returncode != 0
    assert list(dest.glob("aidss-pg_dumpall-*")) == []


def test_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    dest = tmp_path / "backups"
    dest.mkdir()
    sql_file = tmp_path / "dump.sql"
    sql_file.write_text(FAKE_DUMP_SQL, encoding="utf-8", newline="\n")

    now = datetime.now(UTC)
    targets = []
    for offset in range(15):
        ts = (now + timedelta(seconds=offset)).strftime("%Y%m%dT%H%M%SZ")
        p = dest / f"aidss-pg_dumpall-{ts}.sql.gz.enc"
        p.write_bytes(b"keep-me")
        targets.append(p)

    done = _run_backup(
        dest,
        source_cmd=f"gzip -c '{sql_file.as_posix()}'",
        passphrase="passphrase-123",
    )

    assert done.returncode != 0
    assert all(p.read_bytes() == b"keep-me" for p in targets)


@pytest.mark.parametrize(
    "source",
    [
        "printf 'CREATE ROLE fixture;\\n' | gzip; exit 7",
        "printf broken-gzip",
        "printf '' | gzip",
        "printf 'CREATE ROLE fixture;\\nCOPY t FROM stdin;\\n"
        "-- PostgreSQL database cluster dump complete\\n' | gzip",
    ],
)
def test_source_failure_or_invalid_archive_removes_every_output(
    tmp_path: Path, source: str
) -> None:
    done = _run_backup(tmp_path / "out", source_cmd=source)
    assert done.returncode != 0
    assert not list((tmp_path / "out").iterdir())


def test_empty_passphrase_and_invalid_fd_create_nothing(tmp_path: Path) -> None:
    done = _run_backup(tmp_path / "out", source_cmd="exit 99", passphrase="")
    assert done.returncode != 0
    assert not (tmp_path / "out").exists()


def test_script_has_lf_line_endings() -> None:
    assert b"\r" not in SCRIPT.read_bytes()
