"""The venue-neutral exchange port (ADR-056): what it promises, and that nothing bypasses it."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from aidss_trader.config.settings import TraderSettings
from aidss_trader.connector import ExchangeClient, IndodaxClient
from aidss_trader.runtime import assembly

SRC = Path(__file__).resolve().parents[2] / "src" / "aidss_trader"
# The only code allowed to name the concrete client: the client itself, the package export, and
# the one place that builds it.
ALLOWED = {
    SRC / "connector" / "client.py",
    SRC / "connector" / "__init__.py",
    SRC / "runtime" / "assembly.py",
}


def _port_methods() -> list[str]:
    return [n for n, v in vars(ExchangeClient).items() if callable(v) and not n.startswith("_")]


def test_the_indodax_client_matches_every_port_method_signature() -> None:
    assert _port_methods()
    for name in _port_methods():
        port = inspect.signature(getattr(ExchangeClient, name))
        real = inspect.signature(getattr(IndodaxClient, name))
        assert list(port.parameters) == list(real.parameters), name
        for pname, param in port.parameters.items():
            assert param.kind == real.parameters[pname].kind, (name, pname)
            assert param.default == real.parameters[pname].default, (name, pname)


def test_the_port_has_no_withdrawal_deposit_or_transfer_method() -> None:
    """ADR-013: no such client exists, not even disabled."""
    for name in _port_methods():
        assert not any(w in name for w in ("withdraw", "deposit", "transfer", "fiat")), name


def test_only_the_assembly_names_the_concrete_client() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p not in ALLOWED and "IndodaxClient" in p.read_text("utf-8")
    ]
    assert offenders == []


def _settings(**kw: object) -> TraderSettings:
    return TraderSettings(database_url="sqlite://", **kw)  # type: ignore[arg-type]


def test_indodax_is_the_default_and_needs_both_urls() -> None:
    assert _settings().exchange == "indodax"
    assert assembly._client(_settings(), lambda: ("k", "s")) is None
    client = assembly._client(
        _settings(exchange_base_url="https://trade.invalid", public_base_url="https://pub.invalid"),
        lambda: ("k", "s"),
    )
    assert isinstance(client, ExchangeClient) and isinstance(client, IndodaxClient)


def test_an_unknown_venue_is_refused_not_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown exchange 'binance_futures'"):
        assembly._client(_settings(exchange="binance_futures"), lambda: ("k", "s"))


def test_a_second_venue_is_one_adapter_and_one_table_entry(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setitem(assembly.VENUES, "fake", lambda settings, creds: sentinel)
    assert assembly._client(_settings(exchange="fake"), lambda: ("k", "s")) is sentinel
