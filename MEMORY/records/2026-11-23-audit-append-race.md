# Audit chain forks and the append lock (2026-11-23)

**Finding.** The hash-chained audit log forked five times on 2026-11-19 (seq 1423, 1492, 1638, 1679, 1982). Each fork is two rows written 1 to 3 ms apart, one by `script:compare_strategies` and one by the API's own backtest job, both chained to the same previous row. Cause: `AuditLogger.record` read the last hash and inserted without any serialisation, under a "single writer" assumption that the API, scripts and the runtime loop do not meet.

**Fix.** `AuditLogger.record` now takes a transaction-scoped advisory lock (`pg_advisory_xact_lock`) on PostgreSQL before reading the last hash, so concurrent appenders queue and the chain stays linear. SQLite is unchanged. A `-m postgres` test runs eight threads with separate connections and checks a 200-row chain; against a local PostgreSQL 16 it fails without the lock (broken at seq 2) and passes with it. The full suite passes (2742).

**Not fixed.** The five existing forks stay: the log is append-only and was not rewritten. `verify_chain` and the hourly anchor job stop at seq 1423, so the anchor job has returned `rc=2` every hour since 2026-11-19 07:07 UTC and `anchor.jsonl` holds 7 lines. A unique constraint on `prev_hash` was not added because the existing forks would violate it. Not deployed.

Also fixed in the same change: the strategy-kinds API test did not list `koro_obv_pullback`.

## Existing forks accepted (owner, 2026-11-23)

The owner chose to accept the five known forks rather than start a new chain. `verify_chain` now has `KNOWN_FORKS`: for each of seq 1423, 1492, 1638, 1679 and 1982 it lists the parent hash, the dead-end sibling hash and the child hash, and accepts the row only if all three match. Any other fork, or any change to those rows, still breaks verification. History was not rewritten.

Checked against production data: a dump taken from the VM on 2026-11-20 (2876 rows, all five forks inside it) restored into a local PostgreSQL 16 verifies as 2876 rows with the list, breaks at 1423 without it, and breaks at 1679 when that one entry is removed. Full suite 2746 passed.

Still to do, not done: deploy this image so the hourly anchor job (`rc=2` every hour since 2026-11-19 07:07 UTC) can record heads again. The anchor file has a 4-day gap; the first new anchor covers the rows written since.

