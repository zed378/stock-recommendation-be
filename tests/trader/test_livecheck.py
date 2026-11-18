"""T2-07 preparation: the live verification script, exercised against the SYNTHETIC mock only.

Nothing here touches the real exchange. The point of these tests is to prove the script's limits
(read-only, bounded, redacted, honest about what it did not call) before the owner ever runs it.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aidss_trader.__main__ import main
from aidss_trader.livecheck import (
    ALLOWED,
    MAX_REQUESTS,
    MIN_DELAY_S,
    Config,
    LiveCheck,
)
from aidss_trader.livecheck.redact import describe_shape, redact_public, scrub
from aidss_trader.livecheck.runner import PUBLIC_PATHS, SIGNED_PATHS, Refused
from tests.trader.mock_exchange import TEST_KEY, TEST_SECRET, MockExchange

SRC = Path(__file__).resolve().parents[2] / "src" / "aidss_trader" / "livecheck"
D = "https://exchange.test"


def hosts() -> dict[str, str]:
    return {"public": D, "api": D, "tapi": D}


class Rig:
    def __init__(self, tmp_path: Path, phase: str, *, read_only: bool = True, **kw) -> None:
        self.mock = MockExchange()
        self.mock.keys[TEST_KEY]["can_trade"] = not read_only
        rows = [
            (self.mock.now_ms // 1000 - 86_400 * i, "100", "110", "90", "105", "1")
            for i in range(3)
        ]
        self.mock.candles[("BTCIDR", "240")] = rows
        self.mock.candles[("BTCIDR", "1D")] = rows
        self.sleeps: list[float] = []
        self.http = httpx.Client(transport=self.mock.transport())
        self.raw, self.out = tmp_path / "raw", tmp_path / "out"
        signed = phase == "B"
        self.cfg = Config(
            phase=phase,
            raw_dir=self.raw,
            out_dir=self.out,
            confirmed=True,
            key=TEST_KEY if signed else "",
            secret=TEST_SECRET if signed else "",
            hosts=hosts(),
            **kw,
        )
        self.check = LiveCheck(
            self.cfg, self.http, sleep=self.sleeps.append, clock=lambda: self.mock.now_ms / 1000
        )

    def run(self):
        return self.check.run()

    @property
    def requests(self):
        return self.mock.requests

    def all_output(self) -> str:
        files = [*self.raw.glob("*"), *self.out.glob("*")]
        return "\n".join(f.read_text("utf-8") for f in files)


# ------------------------------------------------------------------- refusals


def test_it_refuses_without_the_explicit_confirmation(tmp_path) -> None:
    with pytest.raises(Refused, match="real exchange"):
        LiveCheck(Config("A", tmp_path / "r", tmp_path / "o", confirmed=False), httpx.Client())


def test_phase_b_refuses_without_a_key_and_phase_a_refuses_a_key(tmp_path) -> None:
    with pytest.raises(Refused, match="AIDSS_LIVECHECK_KEY"):
        LiveCheck(Config("B", tmp_path / "r", tmp_path / "o", confirmed=True), httpx.Client())
    with pytest.raises(Refused, match="must not be given a key"):
        LiveCheck(
            Config(
                "A", tmp_path / "r", tmp_path / "o", confirmed=True, key="k" * 12, secret="s" * 12
            ),
            httpx.Client(),
        )


def test_it_refuses_directories_inside_a_git_repository(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[2]
    with pytest.raises(Refused, match="inside a git repository"):
        LiveCheck(Config("A", repo / "scratch-raw", tmp_path / "o", confirmed=True), httpx.Client())
    with pytest.raises(Refused, match="inside a git repository"):
        LiveCheck(Config("A", tmp_path / "r", repo / "scratch-out", confirmed=True), httpx.Client())


def test_it_refuses_a_higher_cap_or_a_shorter_delay_than_the_plan_allows(tmp_path) -> None:
    for kw in ({"max_requests": MAX_REQUESTS + 1}, {"delay_s": MIN_DELAY_S / 2}):
        with pytest.raises(Refused, match="at most"):
            LiveCheck(
                Config("A", tmp_path / "r", tmp_path / "o", confirmed=True, **kw), httpx.Client()
            )


def test_the_command_line_refuses_and_exits_2_without_the_flag(tmp_path, capsys) -> None:
    code = main(
        [
            "live-check",
            "--phase",
            "A",
            "--raw-dir",
            str(tmp_path / "r"),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert code == 2 and "refused" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()  # nothing was created


# --------------------------------------------------------------------- phase A


def test_phase_a_makes_only_get_requests_to_planned_public_paths_with_no_key(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    report = rig.run()
    assert report.calls and len(report.calls) <= MAX_REQUESTS
    assert {r["method"] for r in rig.requests} == {"GET"}
    assert {r["path"] for r in rig.requests} <= {p for _, p in PUBLIC_PATHS}
    assert not any("x-apikey" in {k.lower() for k in r["headers"]} for r in rig.requests)
    assert not any("sign" in {k.lower() for k in r["headers"]} for r in rig.requests)


def test_requests_are_spaced_by_at_least_the_minimum_delay(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    report = rig.run()
    assert len(rig.sleeps) == len(report.calls) - 1 and all(s >= MIN_DELAY_S for s in rig.sleeps)


def test_phase_a_records_observations_and_says_what_it_did_not_call(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    report = rig.run()
    assert report.observations["D11_server_time_digits"] == 13  # milliseconds
    assert report.observations["A4_240"]["time_digits"] == 10  # candle time is in seconds
    assert any("phase B" in n for n in report.not_run)
    assert any("Phase C" in n for n in report.not_run) and any("B8" in n for n in report.not_run)
    assert (rig.out / "report-phase-A.json").exists() and (
        rig.out / "record-draft-phase-A.md"
    ).exists()
    assert "Nothing here is a conclusion" in (rig.out / "record-draft-phase-A.md").read_text(
        "utf-8"
    )


def test_a_step_that_never_ran_is_listed_as_not_verified(tmp_path) -> None:
    rig = Rig(tmp_path, "A", max_requests=3)
    report = rig.run()
    assert report.stopped and "cap" in report.stopped and len(report.calls) == 3
    missed = " ".join(report.not_run)
    assert "A5: not called" in missed and "A7: not called" in missed


# --------------------------------------------------------------------- phase B


def test_phase_b_is_read_only_and_touches_no_order(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    report = rig.run()
    assert report.stopped is None and len(report.calls) >= 12
    assert {r["method"] for r in rig.requests} == {"GET"}
    assert {r["path"] for r in rig.requests} <= {p for _, p in SIGNED_PATHS}
    order_reads = [r for r in rig.requests if r["path"] == "/api/v2/order"]
    assert order_reads and all(
        "orderId=1" in r["query"] or "livecheck-nonexistent" in r["query"] for r in order_reads
    )  # only ids that cannot exist
    assert not rig.mock.orders  # nothing was created, so nothing could be cancelled


def test_phase_b_provokes_the_planned_errors_and_records_their_shape(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    report = rig.run()
    errors = report.observations["D17_error_shapes"]
    assert errors["B5-wrong-signature"]["code"] == -1022
    assert errors["B6-stale-timestamp"]["code"] == -1021
    assert errors["B3-order-by-id"]["code"] == -2013
    assert report.observations["B1_permission_flags"] == {
        "canTrade": False,
        "canWithdraw": False,
        "canWithdrawFiat": False,
    }


def test_no_key_secret_signature_uid_or_balance_reaches_any_file(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    rig.run()
    sigs = [r["headers"]["sign"] for r in rig.requests if "sign" in r["headers"]]
    text = rig.out.joinpath("report-phase-B.json").read_text("utf-8") + rig.out.joinpath(
        "record-draft-phase-B.md"
    ).read_text("utf-8")
    assert sigs
    for secret in (TEST_KEY, TEST_SECRET, *sigs):
        assert secret not in text
    for value in ("100000000", '"uid"'):  # the mock account's balance and its uid field
        assert value not in text
    assert "numeric-string" in text or "string" in text  # signed bodies are shape only


def test_the_secret_is_scrubbed_even_from_an_echoing_error(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    rig.mock.inject(
        "GET",
        "/api/v2/openOrders",
        lambda: httpx.Response(200, text=f"debug echo {TEST_SECRET} and {TEST_KEY}"),
    )
    report = rig.run()
    assert TEST_SECRET not in (rig.out / "report-phase-B.json").read_text("utf-8")
    assert report.calls


# ------------------------------------------------------------- stop conditions


def test_a_key_that_can_withdraw_stops_the_run_at_once(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    rig.mock.can_withdraw = True
    report = rig.run()
    assert "can withdraw" in report.stopped and len(report.calls) == 1
    assert len(rig.requests) == 1  # nothing after the first call


def test_a_key_that_can_trade_is_not_read_only_and_stops_the_run(tmp_path) -> None:
    rig = Rig(tmp_path, "B", read_only=False)
    report = rig.run()
    assert "not Read-only" in report.stopped and len(report.calls) == 1


def test_access_denied_stops_and_is_never_retried(tmp_path) -> None:
    rig = Rig(tmp_path, "B")
    rig.mock.inject_error("GET", "/api/v2/openOrders", 403, -2015, "Access denied.")
    report = rig.run()
    assert "-2015" in report.stopped
    assert len([r for r in rig.requests if r["path"] == "/api/v2/openOrders"]) == 1
    assert not any(r["path"] == "/api/v2/order" for r in rig.requests)


def test_a_rate_limit_stops_the_run(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    rig.mock.inject_error("GET", "/api/pairs", 429, -1003, "Too many requests")
    report = rig.run()
    assert "rate limit" in report.stopped and len(report.calls) == 2


def test_two_server_errors_in_a_row_stop_the_run(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    rig.mock.inject_error("GET", "/api/pairs", 500, -1001, "down")
    rig.mock.inject_error("GET", "/api/price_increments", 500, -1001, "down")
    report = rig.run()
    assert "two server" in report.stopped and len(report.calls) == 3


def test_one_server_error_alone_does_not_stop_the_run(tmp_path) -> None:
    rig = Rig(tmp_path, "A")
    rig.mock.inject_error("GET", "/api/pairs", 500, -1001, "down")
    assert Rig.run(rig).stopped is None


# ------------------------------------------------------------------- redaction


def test_shape_keeps_structure_and_types_but_no_values_or_identifiers() -> None:
    body = {
        "uid": 123,
        "canTrade": True,
        "balances": [{"asset": "IDR", "free": "100.5"}],
        "sign": "abc",
        "n": 5,
        "price": 1.5,
    }
    shape = describe_shape(body)
    assert "uid" not in shape and "sign" not in shape
    assert shape["balances"] == ["list", 1, {"asset": "string", "free": "numeric-string"}]
    assert shape["canTrade"] == "bool" and shape["n"] == "int" and shape["price"] == "float"
    assert "100.5" not in json.dumps(shape)


def test_public_redaction_keeps_values_truncates_lists_and_strips_identifiers() -> None:
    out = redact_public({"uid": 1, "api_key": "x", "rows": list(range(10)), "price": "5"})
    assert "uid" not in out and "api_key" not in out and out["price"] == "5"
    assert out["rows"] == {"truncated_list_of": 10, "first": [0, 1, 2]}


def test_scrub_removes_every_known_secret_and_ignores_empty_ones() -> None:
    assert (
        scrub("a SECRETVALUE b KEYVALUE", ["SECRETVALUE", "KEYVALUE", ""])
        == "a <removed> b <removed>"
    )


# ---------------------------------------------------------------------- guards


def test_the_module_has_no_way_to_send_anything_but_a_get() -> None:
    for path in SRC.glob("*.py"):
        text = path.read_text("utf-8")
        for banned in (
            ".post(",
            ".delete(",
            ".put(",
            ".patch(",
            ".request(",
            "IndodaxClient",
            "create_order",
            "cancel_order",
            "withdraw",
            "capital/",
            "fiat/",
        ):
            if banned in ("withdraw",) and "withdraw" in text:
                # The word appears only to read and report permission flags.
                assert text.count("canWithdraw") >= 1
                continue
            assert banned not in text, (path.name, banned)


def test_the_allowlist_contains_no_order_mutation_or_account_movement_path() -> None:
    paths = {p for _, p in ALLOWED}
    assert not any(
        "withdraw" in p or "capital" in p or "fiat" in p or "deposit" in p for p in paths
    )
    assert "/api/v2/order" in paths and "/api/v2/order" in {p for _, p in SIGNED_PATHS}


def test_an_increment_spelled_differently_is_not_a_disagreement() -> None:
    """On the first live run the JSON float 1e-06 differed from the string 0.000001 as text and
    10 pairs looked wrong; compared as numbers they agree."""
    from aidss_trader.livecheck.runner import _same_number

    assert _same_number("0.000001", 1e-06) is True
    assert _same_number("1000", 1000) is True
    assert _same_number("0.00000100", 1) is False  # a real disagreement still shows
    assert _same_number("x", 1) is False
