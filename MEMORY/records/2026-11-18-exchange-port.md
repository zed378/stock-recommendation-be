# Venue-neutral exchange port (ADR-056)

Date: 2026-11-18. Code and tests only; nothing deployed, no exchange contacted.

What existed: `IndodaxClient` (TAPI 2.0, mock-verified) already built and wired. What was missing was a boundary: six modules named the concrete class.

Changed: `connector/port.py` (`ExchangeClient` Protocol, the 14 operations the Trader uses, no withdrawal method), the six consumers now depend on it (`api/app.py`, `credentials/admin.py`, `killswitch/switch.py`, `orders/manager.py`, `reconcile/reconciler.py`, `runtime/loop.py`), `runtime/assembly.py` builds the client through a `VENUES` table, new setting `exchange` (env `AIDSS_TRADER_EXCHANGE`, default `indodax`, unknown refused), ADR-056, `tests/trader/test_exchange_port.py` (6 tests).

Not changed: `IndodaxClient`, the ledger, the Risk Engine, the schema, any limit. No Binance code.

Futures: only a gap was left, by the owner's choice. A derivatives venue needs its own port (positions, margin, funding), risk rules and ADR first.

Still open for Indodax itself: the exchange URLs are empty on the VM, so the deployed Trader has no connector; T2-07 (live Phase A, then B) is owner-led and not done.
