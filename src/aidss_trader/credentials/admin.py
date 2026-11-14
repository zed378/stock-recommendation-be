"""Checking a candidate or stored exchange key without placing an order (docs/05/13).

The check calls `GET /api/v2/account` and nothing else. A key passes only if it
authenticates, may trade, and has neither withdrawal permission (ADR-013): a key that
can withdraw is refused outright, because the Trader must never hold one.

The reason returned is a class name and a plain sentence. It never contains the key,
the secret, a signature, or an exchange payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from aidss_trader.connector.client import IndodaxClient
from aidss_trader.connector.errors import ConnectorError


@dataclass(frozen=True, slots=True)
class AccountCheck:
    ok: bool
    reason: str | None = None


def check_account(client: IndodaxClient) -> AccountCheck:
    try:
        account = client.get_account()
    except ConnectorError as exc:
        return AccountCheck(False, f"the exchange refused the request ({exc.error_class})")
    except Exception:
        return AccountCheck(False, "the key could not be used")
    if account.can_withdraw or account.can_withdraw_fiat:
        return AccountCheck(
            False, "this key can withdraw funds; create a key with Read and Trade only"
        )
    if not account.can_trade:
        return AccountCheck(False, "this key cannot trade; it needs the Spot Trading permission")
    return AccountCheck(True)
