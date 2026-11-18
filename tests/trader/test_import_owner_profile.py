"""The profile importer, run against the real Trader API (the T5 harness: SQLite, no exchange).

The point of these tests is that the importer goes through the same routes and rules as the screens:
a dry run writes nothing, `proposed` is never applied, a loosening write needs and uses a step-up
grant, and nothing but the five settings sections is touched.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from tests.trader import test_t5_operator_surface as t5

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "deploy" / "trader" / "import_owner_profile.py"
PROFILE = ROOT / "deploy" / "trader" / "owner-defaults.rp50000.json"
BASE = "https://importer.test"


def load_tool():
    spec = importlib.util.spec_from_file_location("import_owner_profile", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()


class Wire:
    """Routes the importer's HTTP calls to the in-process Trader API and records every one."""

    def __init__(self, api, *, login_ok: bool = True) -> None:
        self.api, self.login_ok = api, login_ok
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, method, url, headers, body):
        path = url.removeprefix(BASE)
        self.calls.append((method, path, dict(headers)))
        if path == "/api/auth/login":
            if not self.login_ok:
                return 401, {"detail": "Incorrect email or password"}
            return 200, {"access_token": "tok-trader"}
        response = self.api.http.request(method, path, headers=headers, json=body)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls if m in ("PUT", "POST") and p != "/api/auth/login"]


@pytest.fixture
def setup(monkeypatch):
    # The harness's analysis API answers every login with the trader token; make that user an admin,
    # who holds every Trader permission (ADR-048), as the owner does.
    monkeypatch.setitem(t5.USERS, "tok-trader", ("u1", "admin"))
    api = t5.Api()
    wire = Wire(api)
    client = tool.Client(BASE, wire)
    client.login("owner@example.test", "correct horse")
    return api, wire, client


def profile(status: str = "accepted") -> dict:
    p = json.loads(PROFILE.read_text(encoding="utf-8"))
    p["status"] = status
    return p


def run(client, p, *, apply, answer="APPLY"):
    lines: list[str] = []
    code = tool.run(p, client, apply=apply, confirm=lambda: answer, out=lines.append)
    return code, "\n".join(lines)


def test_a_dry_run_reads_and_shows_the_differences_and_writes_nothing(setup) -> None:
    _, wire, client = setup
    code, text = run(client, profile(), apply=False)

    assert code == 0
    assert "Dry run: nothing was written" in text
    assert "limits.risk_per_trade_pct" in text and "(unset)" in text
    assert wire.writes() == []


def test_a_proposed_profile_is_never_applied(setup) -> None:
    _, wire, client = setup
    code, text = run(client, profile("proposed"), apply=True)

    assert code == 3 and '"status": "proposed"' in text
    assert wire.writes() == []


def test_apply_needs_the_word_apply(setup) -> None:
    _, wire, client = setup
    code, _ = run(client, profile(), apply=True, answer="yes")

    assert code == 4
    assert wire.writes() == []


def test_a_file_with_a_problem_is_stopped_before_the_trader_is_asked_anything(setup) -> None:
    _, wire, client = setup
    bad = profile()
    bad["limits"]["max_daily_loss_idr"] = "100"
    before = len(wire.calls)

    code, text = run(client, bad, apply=True)

    assert code == 2 and "PROBLEM: A2 vs A1" in text
    assert len(wire.calls) == before  # not even a read


def test_apply_writes_all_five_sections_and_the_trader_ends_up_holding_them(setup) -> None:
    api, wire, client = setup
    code, text = run(client, profile(), apply=True)

    assert code == 0, text
    assert "Verified: the Trader now holds every value in the file" in text
    wanted = profile()
    limits = api.call("GET", "/limits", token="tok-admin").json()["data"]
    assert limits["unset"] == []
    assert limits["limits"]["max_order_idr"] in ("20000", "20000.0")
    allow = api.call("GET", "/allowlist", token="tok-admin").json()["data"]
    assert allow["pairs"] == wanted["allowlist"]["pairs"] and allow["active"] is True
    params = api.call("GET", "/strategies/ema_adx/parameters", token="tok-admin").json()["data"]
    assert params["configured"] is True and params["mode"] == "PAPER"
    assert api.call("GET", "/paper-config", token="tok-admin").json()["data"]["configured"]
    thresholds = api.call("GET", "/promotion-thresholds", token="tok-admin").json()["data"]
    assert thresholds["unset"] == []


def test_a_loosening_write_carries_a_fresh_single_use_step_up_grant(setup) -> None:
    _, wire, client = setup
    run(client, profile(), apply=True)

    grants = [h["X-Step-Up"] for m, p, h in wire.calls if "X-Step-Up" in h]
    assert len(grants) >= 2 and len(set(grants)) == len(grants)  # limits, allowlist, thresholds
    stepups = [c for c in wire.calls if c[1] == "/trader/v1/stepup"]
    assert len(stepups) == len(grants)
    keys = [h["Idempotency-Key"] for m, p, h in wire.calls if "Idempotency-Key" in h]
    assert len(set(keys)) == len(keys)


def test_it_touches_nothing_but_the_settings_routes(setup) -> None:
    _, wire, client = setup
    run(client, profile(), apply=True)

    allowed = {
        "/api/auth/login",
        "/trader/v1/stepup",
        "/trader/v1/strategies/ema_adx/parameters",
        "/trader/v1/paper-config",
        "/trader/v1/limits",
        "/trader/v1/allowlist",
        "/trader/v1/promotion-thresholds",
    }
    assert {p for m, p, _ in wire.calls if m != "GET"} <= allowed
    forbidden = ("promote", "resume", "kill", "credentials", "demote")
    assert not any(any(word in p for word in forbidden) for _, p, _ in wire.calls)


def test_a_second_run_finds_nothing_to_do(setup) -> None:
    _, wire, client = setup
    run(client, profile(), apply=True)
    before = len(wire.writes())

    code, text = run(client, profile(), apply=True)

    assert code == 0 and "already holds every value" in text
    assert len(wire.writes()) == before


def test_a_refused_sign_in_stops_everything() -> None:
    api = t5.Api()
    client = tool.Client(BASE, Wire(api, login_ok=False))
    with pytest.raises(tool.ImportError_, match="sign-in refused"):
        client.login("owner@example.test", "wrong")


def test_the_password_is_never_in_the_output_or_the_headers(setup) -> None:
    _, wire, client = setup
    _, text = run(client, copy.deepcopy(profile()), apply=True)

    assert "correct horse" not in text
    assert all("correct horse" not in json.dumps(h) for _, _, h in wire.calls)


def test_the_real_transport_does_not_send_the_default_python_user_agent() -> None:
    """Cloudflare answers 403 (error 1010) to urllib's default agent, which made sign-in fail
    before the API was reached."""
    import http.server
    import threading

    seen: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers.get("User-Agent", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        status, _ = tool.http_send("GET", f"http://127.0.0.1:{server.server_port}/", {}, None)
    finally:
        thread.join(5)
        server.server_close()
    assert status == 200
    assert seen and not seen[0].startswith("Python-urllib")
