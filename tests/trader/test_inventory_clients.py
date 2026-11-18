"""Inventory fixture parsing and metadata redaction, with every system command stubbed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/host/firewall/inventory-clients.sh"


def test_inventory_groups_sources_and_never_prints_process_secrets(monkeypatch, capsys):
    program = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    monkeypatch.setattr(sys, "argv", ["inventory"])
    calls = []

    def stub(args, **kwargs):
        calls.append(args)
        if args == ["ss", "-H", "-ltnp"]:
            output = 'LISTEN 0 128 *:6547 *:* users:(("java",pid=123,fd=4))\n'
        elif args == ["ss", "-H", "-tn4", "state", "established"]:
            output = (
                "0 0 10.1.200.13:8000 10.1.101.50:40000\n"
                "0 0 10.1.200.13:8000 10.1.101.51:40001\n"
                "0 0 10.1.200.13:8000 10.1.101.50:40002\n"
                "0 0 10.1.200.13:9999 10.1.101.50:40003\n"
            )
        elif args == ["ss", "-H", "-tn6", "state", "established"]:
            output = "0 0 [::]:8000 [2001:db8::1]:40000\n"
        elif args[0] == "docker":
            assert args[1] == "ps"
            output = "portainer\t0.0.0.0:8000->8000/tcp\tmanagement\n"
        elif args[0] == "ps":
            output = "java\n" if args[-1] == "comm=" else "operator\n"
        elif args == ["systemctl", "whoami", "123"]:
            output = "example.service\n"
        else:
            pytest.fail(str(args))
        return subprocess.CompletedProcess(args, 0, stdout=output)

    original_read = Path.read_bytes

    def read_bytes(path):
        if path.name in ("cmdline", "environ"):
            return b"sensitive-process-marker"
        return original_read(path)

    monkeypatch.setattr(subprocess, "run", stub)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(os, "readlink", lambda p: "/example/" + p.name)
    with pytest.raises(SystemExit) as result:
        exec(compile(program, str(SCRIPT), "exec"), {})
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "SUBNET 8000 10.1.101.0/24 3" in output
    assert "SOURCE 8000 10.1.101.50 2" in output
    assert "CLIENTS_IPV6\nSOURCE 8000 2001:db8::1 1" in output
    assert "management" in output and "example.service" in output
    assert "sensitive-process-marker" not in output
    assert '"cmdline_length": 24' in output
    assert all(c[0] in ("ss", "docker", "ps", "systemctl") for c in calls)
