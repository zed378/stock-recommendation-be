# Exchange URLs enabled on the VM Trader (2026-11-18)

Trigger: entering the Indodax key in the UI gave "no exchange is configured, so the key cannot be tested": the VM Trader had empty exchange URLs, so no client existed. The owner chose, by multiple choice, to enable the URLs now and to use a Read+Trade key.

Done: the VM override (stdin, not in the repository) now sets `AIDSS_TRADER_EXCHANGE_BASE_URL=https://api.indodax.com` and `AIDSS_TRADER_PUBLIC_BASE_URL=https://indodax.com` (per the connector: v2 public and private paths on the first, legacy public pairs, server time and candles on the second; the docs' open question D1 about which host serves the private API is not settled by this). Trader recreated with `--no-deps` on the same image `9b52dfa`. Before and after: `trading_state` HALTED, zero stored credentials.

Observed (first real contact, public only): `GET indodax.com/api/server_time`, `api.indodax.com/api/v2/ticker/price` and `indodax.com/tradingview/history_v2` all HTTP 200 from the VM, every cycle. No traceback from those.
Also observed, expected: with no credential stored the loop's `snapshot` step fails each cycle with `CredentialUnreadable` and logs a traceback (`runtime step snapshot failed`), and `housekeeping` occasionally. It is fail-closed and stops once a credential exists, but it is noisy; a one-line warning would be better.

Not done and not claimed: no signed request has succeeded; no key was entered by the agent; the key test, the account permission check (`canWithdraw` must be false) and everything on the real order path are unverified. The agent sent no request to Indodax; the Trader did, as designed, with public endpoints only.
Owner steps: create the key (an Indodax API key may be restricted by source IP: allow the VM's public egress address, not the workstation), enter it on the Trader credentials screen, read the test result. Trader stays `HALTED`; resuming and any mode above PAPER are separate gates (ADR-020).
Revert: set both URLs back to empty in the override and recreate the Trader (not rehearsed).
