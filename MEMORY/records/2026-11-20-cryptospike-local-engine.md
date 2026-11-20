# cryptospike-client analysis and a local strategy engine patch (2026-11-20)

Request: analyse https://github.com/bozid95/cryptospike-client and add auto-trading for Binance and Tokocrypto. Finding: the client already auto-executes signals on Binance Futures and Tokocrypto Spot; the missing piece is a signal source of its own (all signals come from a third-party server). Owner chose a local strategy engine, delivered as a patch inside this repo (the cryptospike repo is not modified).

Delivered in `integrations/cryptospike-local-engine/` (README, `apply.sh`, `index.ts.patch`, the engine files and 32 tests). Verified in a throwaway clone (untrusted code: dependencies installed with `--ignore-scripts`, nothing from the repo executed except the new tests): `apply.sh` applies cleanly to a pristine checkout, `tsc --noEmit` reports no error in the new files (the repo's own errors from a missing `prisma generate` are not ours), and the 32 tests pass, including parity of EMA, ATR, ADX and +/-DI against this repo's Python indicators.

Not verified: the real `handleIncomingSignal` path (needs Prisma and a database), any exchange (testnet or live), reachability of `api.binance.com` from the owner's server. Exit logic in that client (TP ladder, SL, trailing) differs from the AIDSS exit, so AIDSS backtests do not apply. The engine is off by default and starts in SHADOW mode.
