# Crypto signals: operator menu, database settings and history (2026-11-20)

ADR-066. Built (not yet deployed): migration `0011_crypto_signals` (four tables, grants for `trader_rw`, guarded grants for `signals_rw`), `deploy/trader/grant_signals_role.sql`, `aidss_trader/signals_config.py` (validation, loosening, storage, scan requests), eight `/trader/v1/signals/*` routes, the worker's database mode (`aidss_signals/store.py`, `runner.py`, `config_from_settings`, `serve` using `AIDSS_SIGNALS_DATABASE_URL`), and the operator page `/trader/signals` (settings, meets the criteria, history with filters, receiver acknowledgements) with id and en copy.

Verified locally: tests for the settings and the API (12), the worker's database mode (13), the earlier worker tests (24), 156 frontend tests including the new form logic and the lazy route, production build. Not verified: PostgreSQL grants (`-m postgres`), the screen in a browser, and anything on the VM.

Behaviour worth knowing: PUBLISH without a receiver server configured in the worker runs as SHADOW and says so; a changed setting applies at the next poll; "scan now" queues a request the worker answers within 30 seconds; a coin already published for a daily candle is not published again, but every scan keeps its own score rows.

## Deployed (2026-11-20)

Images `zed378/aidss-trader:e37cc82`, `zed378/aidss-frontend:latest` (= `e37cc82`), `zed378/aidss-signals:e37cc82`. Order: backup of the `trading` schema (`~/aidss-pre-0011-trading.dump`, 89 tables), migration `0011_crypto_signals` as `trader_owner` (head confirmed), role `signals_rw` created by the superuser with a random password written only to `~/aidss-signals.env` (mode 600, the previous file kept as `.bak-20261120`), trader and frontend recreated with `--no-deps`, settings seeded once by `deploy/trader/seed_signal_config.py` (placeholder numbers, SHADOW, enabled), and the worker container `stocks-signals` recreated in database mode. The api, worker, postgres containers were not touched.

Checked: the role can read `signal_config` and add acknowledgements, cannot read `trading."order"` and cannot update `signal_config`; the worker read the settings from the database and ran a scheduled pass (5 coins, all below threshold for the 2026-11-19 candle, no AI call) whose scan and five scored-coin rows are stored; the Trader's `/trader/v1/signals/*` routes answer 401 without a token (404 for a route that does not exist) and the frontend serves `/trader/signals`. Not checked: the page in a browser, PUBLISH mode, a receiver client.

Docker Hub tidy-up (PowerShell, token never printed): kept the running tag and one rollback per repo. `aidss-trader`: `e37cc82`, `latest` (retagged to `e37cc82`, the host anchor wrapper falls back to it), rollback `f80bbe8`; deleted `52b57b5`, `9ae191a`, `eae6bc2`, `0cca1d1`, `5804d34`, `76be0c6`. `aidss-frontend`: `latest` = `e37cc82`, rollback `f80bbe8`; deleted `5804d34`, `0cca1d1`, `eae6bc2`, `52b57b5`, `1e68c59`. `aidss-signals`: `e37cc82` and rollback `59eae42`. `aidss-api` unchanged.
Rollback: `docker rm -f stocks-signals` stops the worker; the previous Trader and frontend images are `f80bbe8`.
