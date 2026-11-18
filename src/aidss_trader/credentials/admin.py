"""Checking a candidate or stored exchange key without placing an order (docs/05/13).

The check calls `GET /api/v2/account` and nothing else. A key passes only if it
authenticates, may trade, and has neither withdrawal permission (ADR-013): a key that
can withdraw is refused outright, because the Trader must never hold one.

The reason returned is a class name and a plain sentence. It never contains the key,
the secret, a signature, or an exchange payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from aidss_trader.connector.errors import ConnectorError
from aidss_trader.connector.port import ExchangeClient


@dataclass(frozen=True, slots=True)
class AccountCheck:
    ok: bool
    reason: str | None = None


def _numeric(code: object) -> int | None:
    """Only a whole number is shown: the code comes from the exchange's body."""
    try:
        return int(code)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def check_account(client: ExchangeClient) -> AccountCheck:
    try:
        account = client.get_account()
    except ConnectorError as exc:
        # The class, the exchange's numeric code and the HTTP status say which kind of refusal it
        # was (a bad key, a bad signature, a clock). They are not secrets; the exchange's own
        # message text is left out because nothing guarantees what it contains.
        detail = ", ".join(
            part
            for part in (
                str(exc.error_class),
                f"code {_numeric(exc.code)}" if _numeric(exc.code) is not None else "",
                f"HTTP {exc.http_status}" if exc.http_status is not None else "",
            )
            if part
        )
        return AccountCheck(False, f"the exchange refused the request ({detail})")
    except Exception:
        return AccountCheck(False, "the key could not be used")
    if account.can_withdraw or account.can_withdraw_fiat:
        return AccountCheck(
            False, "this key can withdraw funds; create a key with Read and Trade only"
        )
    if not account.can_trade:
        return AccountCheck(False, "this key cannot trade; it needs the Spot Trading permission")
    return AccountCheck(True)
