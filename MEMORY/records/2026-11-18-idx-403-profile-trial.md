# IDX adapter refused with 403: browser-profile trial (2026-11-18)

Symptom: `[idx] refused (403) by bot protection ... Persisting across every attempt means the impersonation profile needs updating or the route has closed`, from the analysis platform's IDX adapter (not the Trader, not Indodax).

Read-only findings on the VM: dead jobs with that error on 2026-11-09, 10, 16, 17 (`market.trading_summary`) and 11-09, 10, 18 (`fundamentals.refresh`); `issuers.sync` died on 11-18 after four attempts. The pattern starts before the 2026-11-18 api/worker rebuild, so the rebuild did not cause it. `monitoring.poll`, `news.sweep` and `analysis.run` are healthy. Cause not proven: either the datacenter IP is treated differently by the site's bot management, or the browser profile is stale.

Probing the site with several profiles from the agent was declined by the permission check; no probe was run.

Change made at the owner's request (option 2): `AIDSS_IDX_IMPERSONATE=chrome136` appended to `~/stocks/.env` (the documented setting; backup `~/stocks/.env.bak-20261118`, same owner and mode), worker only recreated with `--no-deps`. `chrome136` was a pick among the profiles curl_cffi 0.17.0 offers, not a measured one. The api container still has the old value until it is next recreated; only the worker calls IDX. Result not yet observed: the next IDX job (scheduler tick, daily summary about 11:00 UTC) decides it. Revert: restore the backup and recreate the worker.

Option 3 (a data source that does not depend on passing bot protection) is a decision, see the owner's answer.

## Option 3, as chosen: an outbound proxy for the IDX adapter (code only, not deployed)

New setting `AIDSS_IDX_PROXY_URL` (`scheme://[user:pass@]host:port`; http, https, socks5, socks5h; unset by default, so nothing changes). Used only by the IDX adapter: it goes to the `curl_cffi` session as `proxies`. A malformed value is refused at construction without repeating it, and a transport error has the URL, user name and password replaced by `<proxy>` (the value can hold credentials). Pass-through lines added to `docker-compose.yml`, `deploy/production/docker-compose.production.yml`, both env examples and the README table; 5 new tests in `tests/test_market_idx.py`.
Not done: no proxy exists yet, so nothing was configured or deployed. To use it: build and deploy a new api image (the running one does not know the setting), add `AIDSS_IDX_PROXY_URL: ${AIDSS_IDX_PROXY_URL:-}` to the host `~/stocks/docker-compose.yml` (root-owned, needs sudo and the usual `config` comparison), put the URL in `~/stocks/.env` (`infra:infra 600`), and recreate the worker with `--no-deps`. The migration kit's "compose equals the running stack" claim no longer holds byte for byte for the one added line.
Whether using a proxy is acceptable under IDX's terms of use is the owner's call; this change only makes the route configurable.
