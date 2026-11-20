# cryptospike-client analysis and a local strategy engine patch (2026-11-20)

Request: analyse https://github.com/bozid95/cryptospike-client and add auto-trading for Binance and Tokocrypto. Finding: the client already auto-executes signals on Binance Futures and Tokocrypto Spot; the missing piece is a signal source of its own (all signals come from a third-party server). Owner chose a local strategy engine, delivered as a patch inside this repo (the cryptospike repo is not modified).

Delivered in `integrations/cryptospike-local-engine/` (README, `apply.sh`, `index.ts.patch`, the engine files and 47 tests). Verified in a throwaway clone (untrusted code: dependencies installed with `--ignore-scripts`, nothing from the repo executed except the new tests): `apply.sh` applies cleanly to a pristine checkout, `tsc --noEmit` reports no error in the new files (the repo's own errors from a missing `prisma generate` are not ours), and the 32 tests pass, including parity of EMA, ATR, ADX and +/-DI against this repo's Python indicators.

Not verified: the real `handleIncomingSignal` path (needs Prisma and a database), any exchange (testnet or live), reachability of `api.binance.com` from the owner's server. Exit logic in that client (TP ladder, SL, trailing) differs from the AIDSS exit, so AIDSS backtests do not apply. The engine is off by default and starts in SHADOW mode.

## Follow-up: signal-capture simulation and an AI reviewer (2026-11-20)

Owner asked to simulate how the client captures external signals and to build it with an AI as the assessor of signals used for auto-trading.

- **Simulation** (`simulation/`): the client's real `socket.service` and Tokocrypto dry-run executor run against a local mock Socket.IO server and an in-memory stand-in for Prisma; nothing leaves the machine. Observed (real output in `EXAMPLE-OUTPUT.txt`): a repeated signal id opened a second simulated BTC_USDT buy (no dedupe on the Tokocrypto path); a transport drop reconnected, a server-initiated disconnect did not; ACKs are sent even for ignored signals.
- **AI reviewer** (`ai-assessor.ts`, off by default): rules find the candidate and set entry, stop and targets; the AI sees numbers only and returns a score and TAKE or SKIP; it can only veto; any failure drops the candidate; a decision log records every candidate for later measurement. 47 tests pass (15 new) and `simulation/run-ai-pipeline.ts` shows the full chain with a scripted AI.
- Not verified: any call to the real Anthropic API (no key used), the AI's usefulness (no evidence), the real signal server's protocol, any exchange.
