# Crypto signals: operator menu, database settings and history (2026-11-20)

ADR-066. Built (not yet deployed): migration `0011_crypto_signals` (four tables, grants for `trader_rw`, guarded grants for `signals_rw`), `deploy/trader/grant_signals_role.sql`, `aidss_trader/signals_config.py` (validation, loosening, storage, scan requests), eight `/trader/v1/signals/*` routes, the worker's database mode (`aidss_signals/store.py`, `runner.py`, `config_from_settings`, `serve` using `AIDSS_SIGNALS_DATABASE_URL`), and the operator page `/trader/signals` (settings, meets the criteria, history with filters, receiver acknowledgements) with id and en copy.

Verified locally: tests for the settings and the API (12), the worker's database mode (13), the earlier worker tests (24), 156 frontend tests including the new form logic and the lazy route, production build. Not verified: PostgreSQL grants (`-m postgres`), the screen in a browser, and anything on the VM.

Behaviour worth knowing: PUBLISH without a receiver server configured in the worker runs as SHADOW and says so; a changed setting applies at the next poll; "scan now" queues a request the worker answers within 30 seconds; a coin already published for a daily candle is not published again, but every scan keeps its own score rows.
