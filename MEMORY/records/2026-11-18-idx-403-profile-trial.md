# IDX adapter refused with 403: browser-profile trial (2026-11-18)

Symptom: `[idx] refused (403) by bot protection ... Persisting across every attempt means the impersonation profile needs updating or the route has closed`, from the analysis platform's IDX adapter (not the Trader, not Indodax).

Read-only findings on the VM: dead jobs with that error on 2026-11-09, 10, 16, 17 (`market.trading_summary`) and 11-09, 10, 18 (`fundamentals.refresh`); `issuers.sync` died on 11-18 after four attempts. The pattern starts before the 2026-11-18 api/worker rebuild, so the rebuild did not cause it. `monitoring.poll`, `news.sweep` and `analysis.run` are healthy. Cause not proven: either the datacenter IP is treated differently by the site's bot management, or the browser profile is stale.

Probing the site with several profiles from the agent was declined by the permission check; no probe was run.

Change made at the owner's request (option 2): `AIDSS_IDX_IMPERSONATE=chrome136` appended to `~/stocks/.env` (the documented setting; backup `~/stocks/.env.bak-20261118`, same owner and mode), worker only recreated with `--no-deps`. `chrome136` was a pick among the profiles curl_cffi 0.17.0 offers, not a measured one. The api container still has the old value until it is next recreated; only the worker calls IDX. Result not yet observed: the next IDX job (scheduler tick, daily summary about 11:00 UTC) decides it. Revert: restore the backup and recreate the worker.

Option 3 (a data source that does not depend on passing bot protection) is a decision, see the owner's answer.
