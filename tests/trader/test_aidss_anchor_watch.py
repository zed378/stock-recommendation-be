"""Synthetic logs and command stubs for the independent anchor observer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/trader/aidss-anchor-watch.sh"


def program() -> str:
    return SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


@pytest.mark.parametrize(
    ("log", "maximum", "expected"),
    [
        ("2026-01-01T00:00:00Z rc=0 ok", "100", 0),
        ("2026-01-01T00:00:00Z rc=0 ok", "1", 1),
        ("2026-01-01T00:00:00Z rc=2 sensitive-marker", "100", 2),
        ("2026-01-01T00:00:00Z rc=0 ok", "", 3),
        ("malformed", "100", 1),
        ("2026-01-01T00:00:00Z rc=3 failure", "100", 1),
    ],
)
def test_states_and_fixed_hook_message(tmp_path, monkeypatch, capsys, log, maximum, expected):
    directory = tmp_path / "anchor with spaces"
    directory.mkdir()
    (directory / "anchor.jsonl").write_text('{"seq":1}\n')
    (directory / "anchor.log").write_text(log + "\n")
    before = (directory / "anchor.jsonl").read_bytes()
    monkeypatch.setenv("AIDSS_ANCHOR_DIR", str(directory))
    monkeypatch.setenv("AIDSS_ANCHOR_NOW", "1767225602")
    monkeypatch.setenv("AIDSS_ANCHOR_MAX_AGE_S", maximum)
    monkeypatch.setenv("AIDSS_ANCHOR_ALERT_CMD", str(tmp_path / "hook with spaces"))
    calls = []

    def stub(args, **kwargs):
        calls.append(args)
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", stub)
    with pytest.raises(SystemExit) as result:
        exec(compile(program(), str(SCRIPT), "exec"), {})
    assert result.value.code == expected
    output = capsys.readouterr()
    assert "sensitive-marker" not in output.out + output.err + str(calls)
    hooks = [c for c in calls if c[0] != "logger"]
    assert len(hooks) == int(expected != 0)
    assert all(len(c) == 2 for c in hooks)
    assert (directory / "anchor.jsonl").read_bytes() == before
    assert not any(c[0] == "docker" for c in calls)


def test_missing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDSS_ANCHOR_DIR", str(tmp_path))
    monkeypatch.setenv("AIDSS_ANCHOR_MAX_AGE_S", "100")
    monkeypatch.delenv("AIDSS_ANCHOR_ALERT_CMD", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    with pytest.raises(SystemExit) as result:
        exec(compile(program(), str(SCRIPT), "exec"), {})
    assert result.value.code == 4
