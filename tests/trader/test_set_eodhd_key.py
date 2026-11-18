"""The host helper that stores the EODHD key: no echo of the key, only three names touched."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/host/set-eodhd-key.sh"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

KEY = "tok-SECRET_abc.123"


def run(tmp_path: Path, stdin: str, env_text: str) -> tuple[subprocess.CompletedProcess, Path]:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text, newline="\n")
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, AIDSS_ENV_FILE=str(env_file), HOME=str(home))
    done = subprocess.run(
        [BASH, str(SCRIPT)], input=stdin.encode(), capture_output=True, env=env, timeout=30
    )
    return done, env_file


def test_lf_and_syntax() -> None:
    assert b"\r" not in SCRIPT.read_bytes()
    assert subprocess.run([BASH, "-n", str(SCRIPT)]).returncode == 0


def test_it_replaces_three_names_keeps_the_rest_and_never_prints_the_key(tmp_path: Path) -> None:
    before = (
        "AIDSS_JWT_SECRET=keepme\n"
        "AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=idx\n"
        "AIDSS_EODHD_API_KEY=old\n"
        "AIDSS_AI_BASE_URL=https://x.invalid/v1\n"
    )
    done, env_file = run(tmp_path, f"{KEY}\n5000\n", before)
    assert done.returncode == 0, done.stderr
    text = env_file.read_text()
    assert "AIDSS_JWT_SECRET=keepme" in text and "AIDSS_AI_BASE_URL=https://x.invalid/v1" in text
    assert text.count("AIDSS_EODHD_API_KEY=") == 1 and f"AIDSS_EODHD_API_KEY={KEY}" in text
    assert "AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd" in text
    assert "=idx" not in text and "=old" not in text
    assert "AIDSS_FUNDAMENTALS_DAILY_QUOTA=5000" in text
    assert KEY.encode() not in done.stdout + done.stderr
    backups = list((tmp_path / "home").glob(".env.aidss-*.bak"))
    assert len(backups) == 1 and backups[0].read_text() == before


@pytest.mark.parametrize(
    "stdin", ["\n10\n", f"{KEY}\n\n", f"{KEY}\nabc\n", "bad key with spaces\n10\n", f"{KEY}\n-5\n"]
)
def test_bad_input_changes_nothing(tmp_path: Path, stdin: str) -> None:
    before = "AIDSS_JWT_SECRET=keepme\n"
    done, env_file = run(tmp_path, stdin, before)
    assert done.returncode != 0
    assert env_file.read_text() == before
    assert KEY.encode() not in done.stdout + done.stderr
