"""The host anchor wrapper: it must hand the container one database URL and nothing else.

`docker` is replaced by a stub that records its arguments and environment, so nothing is started.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "trader" / "aidss-anchor.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs a POSIX shell")

STUB = """#!/bin/sh
printf '%s\n' "$@" > "$STUB_DIR/args.txt"
env | grep '^AIDSS_' | sed 's/=.*//' > "$STUB_DIR/env_names.txt"
echo "${STUB_OUT:-anchored seq=1 head_hash=abc file=/anchor/anchor.jsonl}"
exit "${STUB_RC:-0}"
"""


def run(tmp_path: Path, env_lines: list[str], *, rc: int = 0, out: str | None = None):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    docker = stub_dir / "docker"
    docker.write_text(STUB)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / "trader.env"
    env_file.write_text("\n".join(env_lines) + "\n")
    anchor_dir = tmp_path / "anchor"
    anchor_dir.mkdir()
    # Not the whole environment: the test process carries its own AIDSS_* variables, and the point
    # is to see exactly which ones the script itself passes on.
    env = {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "AIDSS_ANCHOR_ENV_FILE": str(env_file),
        "AIDSS_ANCHOR_DIR": str(anchor_dir),
        "STUB_DIR": str(tmp_path),
        "STUB_RC": str(rc),
    }
    if out is not None:
        env["STUB_OUT"] = out
    done = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True)
    return done, anchor_dir


def test_only_the_traders_own_url_reaches_the_container(tmp_path) -> None:
    done, _ = run(
        tmp_path,
        [
            "AIDSS_TRADER_MIGRATION_DATABASE_URL=postgresql://owner:ownerpw@h/db",
            "AIDSS_TRADER_DATABASE_URL=postgresql://rw:rwpw@h/db",
            "AIDSS_TRADER_MONITOR_DATABASE_URL=postgresql://mon:monpw@h/db",
            "AIDSS_APP_DATABASE_URL=postgresql://app:apppw@h/db",
        ],
    )
    assert done.returncode == 0
    args = (tmp_path / "args.txt").read_text()
    names = (tmp_path / "env_names.txt").read_text().split()
    # The value travels in the environment (`-e NAME`), never on the command line.
    assert "AIDSS_TRADER_DATABASE_URL" in args and "rwpw" not in args
    assert "AIDSS_TRADER_DATABASE_URL" in names
    # The script's own settings (AIDSS_ANCHOR_*) are the test's, not data from the env file.
    assert [n for n in names if n.endswith("DATABASE_URL")] == ["AIDSS_TRADER_DATABASE_URL"]
    for secret in ("ownerpw", "monpw", "apppw"):
        assert secret not in args


def test_the_container_is_locked_down_and_writes_only_the_anchor_directory(tmp_path) -> None:
    run(tmp_path, ["AIDSS_TRADER_DATABASE_URL=postgresql://rw:x@h/db"])
    args = (tmp_path / "args.txt").read_text().split()
    for flag in ("--rm", "--read-only", "--cap-drop", "ALL", "no-new-privileges"):
        assert flag in args
    assert "zed378/aidss-trader:7d03693" in args and "latest" not in " ".join(args)
    assert args[args.index("--out") + 1] == "/anchor/anchor.jsonl"
    assert any(a.endswith(":/anchor") for a in args)


def test_a_quoted_value_is_unquoted(tmp_path) -> None:
    done, _ = run(tmp_path, ['AIDSS_TRADER_DATABASE_URL="postgresql://rw:x@h/db"'])
    assert done.returncode == 0


def test_success_and_failure_are_logged_and_the_exit_code_is_passed_on(tmp_path) -> None:
    done, anchor_dir = run(tmp_path, ["AIDSS_TRADER_DATABASE_URL=postgresql://rw:x@h/db"])
    assert done.returncode == 0
    assert "rc=0 anchored seq=1" in (anchor_dir / "anchor.log").read_text()

    broken = tmp_path / "broken"
    broken.mkdir()
    done, anchor_dir = run(
        broken,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://rw:x@h/db"],
        rc=2,
        out="audit chain broken: audit log truncated",
    )
    assert done.returncode == 2
    assert "rc=2 audit chain broken" in (anchor_dir / "anchor.log").read_text()


def test_a_missing_url_anchors_nothing_and_says_so(tmp_path) -> None:
    done, anchor_dir = run(tmp_path, ["AIDSS_TRADER_MONITOR_DATABASE_URL=postgresql://m:x@h/db"])
    assert done.returncode == 3
    assert not (tmp_path / "args.txt").exists()  # docker was never called
    assert "not found" in (anchor_dir / "anchor.log").read_text()
