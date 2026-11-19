# Feature Spec — S3 Longer candle history and a held-out evaluation window

**Written:** 2026-11-19, **before** implementation
**Task:** S3 (no task id assigned yet)
**Author:** Claude, at the owner's request ("rancang perpanjangan riwayat candle")
**Spec refs:** `docs/05-MODULE-SPECIFICATIONS/01` (strategy engine, held-out data), `06` (paper and backtest), `docs/06-INTEGRATIONS/05` (market data); OQ-4, OQ-11; ADR-012, ADR-019, ADR-059, ADR-061, ADR-063.

> Status: a design. Nothing here is built. Section "Open Questions" needs the owner before code.

---

## Problem

Every strategy result so far comes from about 300 four-hour bars per pair (about 50 days, one falling market, 15 to 60 trades per strategy). That is too little to tell a better rule from a lucky one, and there is no data the rules were not chosen on. `docs/05/01` already says parameters "must be tuned only on data that is then held out from the promotion evidence", and OQ-11 lists the held-out data policy as undecided. The owner needs: (1) much more history to test on, and (2) a window the strategies are never tuned on, so a result there means something.

---

## What `docs/` Already Decides

| Decision | Source |
|---|---|
| Candles come from `GET /tradingview/history_v2` on the public REST API; only closed candles are stored | `06/05`, ADR-012, `market_data/candles.py` |
| Candles are aligned to UTC (4H at 00, 04, 08, 12, 16, 20) | D18 |
| A backtest has no look-ahead and uses the same sizing, limits and costs as paper | `05/06`, engine docstring |
| Parameters are tuned only on data that is then held out of the promotion evidence | `05/01` |
| The backtest promotion gate reads stored runs, never a typed figure | ADR-059 |
| No signed request to the production exchange by an agent without the owner's per-action word | CLAUDE.md |

**Gaps this spec settles (ADR-064, proposed):** how far back, how backfill is done and checked; how the backtest window matches what live strategies see; what "held out" means in code; what the promotion gate reads once a holdout exists.

---

## Facts measured on 2026-11-19 (public requests, nothing signed)

- One request returned the whole range asked: 365 days gave 2,191 4H candles (6 per day), no paging needed at that size.
- `BTCIDR`, `ETHIDR`, `DOGEIDR` all start on **2025-05-16** (3,313 candles, about 18 months), and asking for 560, 700 or 1,100 days gave the same 3,313. Either the history begins then or the endpoint caps at 3,313 bars; a young pair settles it: `PIEVERSEIDR` returned 1,686 candles from its listing on 2026-02-11, so the cap, if any, is not hit there. The two readings are not told apart yet.
- The database keeps every stored candle (no pruning), live decisions read only the newest 300 (`_load_candles` limit), and the backtest runner reads **all** stored candles of a pair. So storing more history needs no change to live decisions, and it automatically lengthens every backtest.

---

## Design

### A. Backfill (one-off tool, not the live loop)

- `deploy/trader/backfill_candles.py`, run inside the Trader container like the other deploy scripts. It uses the Trader's own public connector (`get_ohlc`), so rate limiting, retries and error classes are the existing ones, and **no signed request is made**.
- For each chosen pair (default: the allowlist) it requests 4H candles from a chosen start to now, in chunks of at most 365 days, spaced at least one second apart, and stores them with `ingest_candles(..., check_alignment=True)`. That function already refuses unfinished and malformed candles and never overwrites an existing one.
- **Idempotent and resumable:** running it twice stores nothing new the second time. An existing candle that differs from the fetched one is a *conflict*: it is counted and listed, never overwritten, and the run exits non-zero.
- **Gap report:** after ingest, per pair, the first and last stored candle, the count, and every missing 4H slot between them. A pair with gaps is reported, not silently patched.
- Summary written to the audit log (`candles.backfill`: pairs, counts, conflicts, gaps). Dry run by default; `--apply` writes.
- The live loop is untouched: it keeps fetching the last 300 bars and deduplicating.

### B. Backtest window that matches live

- **Cap the history a strategy sees at `MAX_HISTORY_BARS` (300), as live does.** Today the engine hands `evaluate` every candle up to the decision; with 3,300 bars a long EMA would behave differently in the backtest than in paper, and the cost of each decision would grow with history. The engine passes `candles[max(0, i + 1 - 300) : i + 1]`. The no-look-ahead test changes from "exactly `i + 1`" to "`min(i + 1, 300)`, never more than the past".
- **Trade window.** `run_backtest` gains `trade_from` and `trade_to`: decisions before `trade_from` only warm the indicators and never open a position; equity and metrics start at `trade_from`. So a held-out window can be tested with full indicator warm-up and a clean book.
- **Contiguity.** A missing 4H candle breaks indicator continuity. The runner uses the latest contiguous segment of each pair and reports how many bars were dropped; it does not interpolate.
- **Speed.** Today about 150k evaluations take under a minute. At 3,300 bars per pair, 33 pairs and 15 strategies it is about 1.6 million evaluations, perhaps ten times longer. Step one of the build is to **measure** this; the remedies in order are: run in the background job that already exists (minutes are acceptable), then cache indicator series per pair and parameter set. No remedy is chosen before the measurement.

### C. Held-out window

- A single owner setting `holdout_start` (a UTC timestamp, in `trader_setting`, audited). Data from `holdout_start` on is the **holdout**; everything before it is **development**. Unset means no holdout exists and the screen says so.
- Backtest rows gain `window` (`development`, `holdout`, `all`), `period_start`, `period_end` (migration `0011`, nullable; NULL means a legacy run over everything stored, shown as `all`).
- Development runs may be repeated freely and are where a strategy is designed or tuned. A holdout run is allowed at any time but **every holdout run is counted and shown**: "this holdout has been tested by N strategies, M times". The number is the honest warning about data snooping; it blocks nothing.
- The Strategies screen gets a window selector and shows development and holdout side by side per strategy, with the summary figures from ADR-063.
- **Promotion gate (proposal, needs the owner):** once `holdout_start` is set, the `backtest` gate reads the holdout run of the strategy's registered version, not the all-data run. With no holdout set it keeps today's behaviour and the gate says the evidence is not held out.

### D. What is deliberately not done

- No parameter search or automatic optimisation. The screen and tools only report; the owner chooses.
- No 1D history in this task (ADR-012 lists 1D, nothing uses it yet).
- No change to paper or live decisions.

---

## Open Numbers

| Number | Owner-set? | Open question |
|---|---|---|
| `holdout_start` | **Open** | A date, or a share of the history. Proposal: the most recent 25 percent of the common history, about 4.5 months. Never defaulted in code; unset means no holdout |
| How far back to backfill | **Open** | Proposal: as far as the exchange serves (about 2025-05-16), because the cost is a few requests per pair |
| Which pairs | Owner-set (allowlist, 33 pairs) | Proposal: the allowlist; pairs listed later simply have less history |
| Chunk size and pacing | Technical | At most 365 days per request, at least 1 s apart; these are caution, not limits the exchange stated (OQ-4 stays open for the maximum range) |
| Gap handling | **Open** | Proposal: use the latest contiguous segment and report the rest; the alternative is to refuse a pair with any gap |
| Backtest promotion threshold (OQ-12) | Owner-set where set | Unchanged; it now applies to the holdout figure if the owner accepts the gate change |

---

## Data Model

- [ ] No new table for backfill: it writes the existing `candle` table through `ingest_candles` (`trader_rw` already inserts there).
- [ ] Migration `0011`: nullable `window` (String 12), `period_start`, `period_end` (DateTime tz) on `backtest_run`, added only if missing. Additive, no rewrite.
- [ ] `holdout_start`: a `trader_setting` row `backtest_holdout`, with an audit entry on every change.
- [ ] `origin` stays `BACKTEST`; money stays `Decimal`.
- [ ] Retention: candles and runs are never deleted.

---

## API (operator)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/trader/v1/backtest-holdout` | `VIEW` | The holdout start (or null), the common history range, how many strategies and runs have touched the holdout |
| PUT | `/trader/v1/backtest-holdout` | `CONFIGURE_STRATEGY` + step-up | Set or clear `holdout_start`; moving it earlier (more holdout) is free, moving it later (less holdout, releasing data to development) needs the password |
| POST | `/trader/v1/backtests` | existing | Gains `window` (`development`, `holdout`, `all`) |
| GET | `/trader/v1/strategy-defs/{id}/backtests` | `VIEW` | Gains the window and the period of each row, and a summary per window |

- [ ] Every route has a permission; none creates an order; idempotency key and audit on every mutation.

---

## Exchange Interaction

- [ ] Endpoint `GET https://indodax.com/tradingview/history_v2`, public and unsigned, already used by the Trader; fields per `06/05` and D11, D12, D18.
- [ ] Retry class: safe (a read). A failed chunk is retried by the connector's own read policy; the script then stops with a report and can be rerun.
- [ ] Rate limit: the connector's public scope, plus the script's own pacing.
- [ ] Mock behaviour: the mock server serves `history_v2` ranges; the tests use it with a long synthetic range.
- [ ] Marked "measured on 2026-11-19, not yet a documented guarantee": the 365-day chunk and the 2025-05-16 start.

---

## Risk and Safety

- **Interacts with:** nothing that sizes or sends an order. The backfill writes only candles; the backtest writes only `backtest_run` and audit rows.
- **On uncertainty (a conflicting candle, a gap, an unaligned time):** report and stop that pair; never overwrite or invent a candle.
- **A test that fails when the control is removed:** the history cap (a strategy never receives more than 300 bars), the trade window (no position before `trade_from`), and "never overwrites an existing candle".
- **Skipping the Risk Engine?** No order is involved.
- **Model output into an order?** No.
- **Honesty risks:** backtest figures stay labelled BACKTEST; a holdout figure is never presented as live or paper; the holdout counter is shown next to every holdout result.

---

## Security

- [ ] No secrets; the script reads only the public API and the database URL the container already has.
- [ ] No new outbound destination: `indodax.com` is already allowed.

---

## Tests

- Unit: backfill chunking and idempotence on a long synthetic series; a conflicting candle is reported and never overwritten; an unfinished or unaligned candle is refused; gap detection; the history cap in the engine; `trade_from` and `trade_to` (no trade and no metric before `trade_from`, indicator warm-up still used).
- Integration (mock exchange, SQLite): a backfill followed by a backtest over the longer series gives the same result for the same window twice (reproducible fingerprint); development and holdout rows are stored with their periods.
- Acceptance: the holdout counter rises with each holdout run; moving `holdout_start` later without a password is refused.
- Negative authorization: a viewer cannot set the holdout or run a backtest.
- Guard: the architecture tests are untouched; migration `0011` is additive and `-m postgres` passes with the privilege test.
- Performance: a measured timing of the full backtest at 3,300 bars, recorded before choosing a speed-up.

---

## Open Questions

1. **Holdout size.** The most recent 25 percent of the history (about 4.5 months), a fixed recent window, or another split.
2. **Promotion gate.** Should the `backtest` gate read the holdout result once a holdout is set?
3. **Gaps.** Use the latest contiguous segment and report the rest, or refuse any pair with a gap.
4. **Backfill depth.** As far back as the exchange serves, or a shorter fixed span.
5. **Regime coverage.** About 18 months is one bear and one recovery at most; the holdout will be one regime. Is a single chronological holdout enough, or does the owner want several (walk-forward) windows? Walk-forward is a larger design and is not specified here.

---

## Rollout

- [ ] Phases, each deployable alone: **A** backfill script (no deploy risk beyond new rows; run a dry run first), **B** engine window and cap plus migration `0011`, **C** holdout setting, API and screen.
- [ ] Rollback: A leaves extra candle rows that older code ignores (live reads the newest 300); B and C are additive and nullable. No order, position or live setting is touched.
- [ ] Order for B and C: backup of the `trading` schema, migration as `trader_owner`, Trader, frontend, `--no-deps`.
- [ ] Nothing here touches orders and nothing is enabled by default: with no `holdout_start` set the screen and the gate behave as they do today.
