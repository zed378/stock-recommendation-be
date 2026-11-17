# Starter profiles for the owner numbers (2026-11-16)

The owner asked for default parameters for the trading bot to adjust instead of filling every field by hand, then said the capital is small and may be only Rp 50,000 (earlier answer: Rp 1,000,000).
Per the standing rule that a loss-limiting number is never defaulted silently, this was built as a **draft the owner edits**, not as a default in the code (ADR-055, `proposed`).

## What was added

- `deploy/trader/owner-defaults.rp50000.json` and `owner-defaults.rp1000000.json`: every owner number the Trader accepts (risk limits, strategy parameters, paper cost model, allowlist and liquidity filter,
  promotion thresholds), conservative, 4H, BTCIDR and ETHIDR, `status: proposed`.
- `deploy/trader/check_owner_defaults.py`: read-only. Builds `RiskLimits`, `EmaAdxParams`, `PaperConfig` and `Thresholds` from a file, applies the API's own `limit_problem` ranges, and checks the
  relationships in `08` (A2/A1, A8/A6, A6/A7, A5/A6/A7, A3/A2, C1/A10, D5/E4, H3/A3, I1) plus one new rule: the sized entry must reach the pair's minimum order.
- `tests/trader/test_owner_defaults.py` (5 tests): both profiles load and pass, no required limit is missing, a missing limit is reported not defaulted, each broken relationship is caught, a value the API would refuse is refused,
  and a 0.5% risk at Rp 50,000 is reported as below the minimum.
- `docs/01-PRODUCT-REQUIREMENTS/09-OWNER-NUMBERS-STARTER-PROFILE.md` and ADR-055.

## Why Rp 50,000 gets a different profile

`intents/builder.py` sizes an entry as the smallest of the risk-based size and the caps and then refuses an order under the pair minimum; it never rounds up. With a 5% stop and a Rp 10,000 minimum
(both assumptions), an entry needs at least Rp 500 of risk, 1% of Rp 50,000. So the small-account profile uses 1.5% risk per trade (Rp 750), one open position, and caps of 40%.

## Not verified

- The minimum order (Rp 10,000) and the 5% stop distance are assumptions. The real minimums come from `GET /api/pairs`, which no agent has called (no live exchange call without the owner's instruction). The test mock's
  Rp 50,000 and 0.0001 BTC are fixture numbers; if real, BTCIDR could not be traded at Rp 50,000.
- The fee, tax, clearing, slippage, liquidity-volume and spread values are placeholders chosen to err pessimistic, not observed (OQ-5, OQ-8 stay open).
- The profiles were not applied to any instance; nothing about runtime behaviour changed. No import tool exists; values are entered on the Trader screens.
