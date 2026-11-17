"""Draft firewall checks never execute a host mutation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/host/firewall/apply-with-rollback.sh"
NFT = ROOT / "deploy/host/firewall/docker-user.nft"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")


def test_drafts_are_lf_and_explicitly_unapplied() -> None:
    for path in (SCRIPT, NFT):
        content = path.read_bytes()
        assert b"\r" not in content
        assert b"DRAFT, NOT APPLIED" in content


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_apply_draft_shell_syntax_only() -> None:
    done = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_disabled_draft_cannot_reach_mutation_commands(tmp_path: Path) -> None:
    # Every potentially mutating executable is replaced; no real host command can run.
    marker = tmp_path / "called"
    for name in ("nft", "iptables", "ip6tables", "systemd-run", "systemctl", "sudo"):
        stub = tmp_path / name
        stub.write_text('#!/bin/sh\nprintf called > "$MARKER"\nexit 99\n', newline="\n")
        stub.chmod(0o700)
    env = dict(os.environ, PATH=str(tmp_path), MARKER=str(marker))
    done = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True)
    assert done.returncode == 2
    assert "DRAFT ONLY" in done.stderr
    assert not marker.exists()


def test_container_filter_uses_original_port_and_both_source_families() -> None:
    text = NFT.read_text()
    assert "ct original proto-dst @managed_tcp" in text
    assert "ip saddr @lan_v4" in text and "ip6 saddr @lan_v6" in text
    assert "flush ruleset" not in text
    assert "OWNER_APPROVED" not in text


def test_stage_one_values_match_the_recorded_owner_answers() -> None:
    lines = [ln.strip() for ln in NFT.read_text().splitlines()]
    elements = [ln for ln in lines if ln.startswith("elements")]
    # ssh_v4, lan_v4, managed_tcp; both IPv6 sets stay empty (new remote IPv6 denied).
    assert elements == [
        "elements = { 10.1.101.0/24 }",
        "elements = { 10.1.101.0/24 }",
        "elements = { 8000, 9443 }",
    ]
    assert "100.64." not in NFT.read_text()  # netbird is admitted by wt0, not by a CIDR
