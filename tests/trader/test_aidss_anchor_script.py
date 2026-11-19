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
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
GIT_USR_BIN = Path(r"C:\Program Files\Git\usr\bin")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs a POSIX shell")

STUB = """#!/bin/sh
if [ "$1" = inspect ]; then
    printf '%s\n' "$@" > "$STUB_DIR/inspect_args.txt"
    [ -n "${STUB_INSPECT:-}" ] && echo "$STUB_INSPECT"
    exit "${STUB_INSPECT_RC:-0}"
fi
printf '%s\n' "$@" > "$STUB_DIR/args.txt"
env | grep '^AIDSS_' | sed 's/=.*//' > "$STUB_DIR/env_names.txt"
echo "${STUB_OUT:-anchored seq=1 head_hash=abc file=/anchor/anchor.jsonl}"
exit "${STUB_RC:-0}"
"""


def run(
    tmp_path: Path,
    env_lines: list[str],
    *,
    rc: int = 0,
    out: str | None = None,
    extra_env: dict[str, str] | None = None,
):
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
    path_parts = [str(stub_dir)]
    if GIT_USR_BIN.exists():
        path_parts.append(str(GIT_USR_BIN))
    path_parts.append(os.environ["PATH"])
    env = {
        "PATH": os.pathsep.join(path_parts),
        "HOME": str(tmp_path),
        "AIDSS_ANCHOR_ENV_FILE": str(env_file),
        "AIDSS_ANCHOR_DIR": str(anchor_dir),
        "STUB_DIR": str(tmp_path),
        "STUB_RC": str(rc),
    }
    if out is not None:
        env["STUB_OUT"] = out
    env.update(extra_env or {})
    done = subprocess.run(
        [BASH, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30
    )
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
    assert "zed378/aidss-trader:latest" in args  # the fallback: the stub reports no running Trader
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


def _image_arg(tmp_path: Path) -> str:
    args = (tmp_path / "args.txt").read_text().splitlines()
    return args[args.index("python") - 1]


def test_it_runs_the_image_the_trader_container_is_running(tmp_path) -> None:
    done, _ = run(
        tmp_path,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://t:p@db/x"],
        extra_env={"STUB_INSPECT": "zed378/aidss-trader:9ae191a"},
    )
    assert done.returncode == 0
    assert _image_arg(tmp_path) == "zed378/aidss-trader:9ae191a"
    inspected = (tmp_path / "inspect_args.txt").read_text().splitlines()
    assert inspected[0] == "inspect" and inspected[-1] == "stocks-trader-1"
    log = (tmp_path / "anchor" / "anchor.log").read_text()
    assert "image=zed378/aidss-trader:9ae191a" in log


def test_without_a_running_trader_it_falls_back_to_latest(tmp_path) -> None:
    done, _ = run(
        tmp_path,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://t:p@db/x"],
        extra_env={"STUB_INSPECT_RC": "1"},
    )
    assert done.returncode == 0
    assert _image_arg(tmp_path) == "zed378/aidss-trader:latest"


def test_an_odd_image_name_from_inspect_is_not_used(tmp_path) -> None:
    done, _ = run(
        tmp_path,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://t:p@db/x"],
        extra_env={"STUB_INSPECT": "evil; rm -rf /"},
    )
    assert done.returncode == 0
    assert _image_arg(tmp_path) == "zed378/aidss-trader:latest"


def test_an_explicit_image_wins_and_a_bad_one_is_refused(tmp_path) -> None:
    done, _ = run(
        tmp_path,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://t:p@db/x"],
        extra_env={"AIDSS_ANCHOR_IMAGE": "zed378/aidss-trader:473436d", "STUB_INSPECT": "x:y"},
    )
    assert done.returncode == 0 and _image_arg(tmp_path) == "zed378/aidss-trader:473436d"
    other = tmp_path / "second"
    other.mkdir()
    done, _ = run(
        other,
        ["AIDSS_TRADER_DATABASE_URL=postgresql://t:p@db/x"],
        extra_env={"AIDSS_ANCHOR_IMAGE": "bad image; x"},
    )
    assert done.returncode == 3
    assert not (other / "args.txt").exists()  # nothing was started
