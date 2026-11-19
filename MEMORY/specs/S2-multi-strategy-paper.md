# Feature Spec — S2 Several strategies in the paper loop (pair ownership)

**Written:** 2026-11-19, **before** implementation
**Task:** S2 (ADR-061 stage 2; no task id assigned yet)
**Author:** Claude, with the owner's agreement to the design ("setuju rancangan satu pasangan satu pemilik", 2026-11-19)
**Spec refs:** `docs/05-MODULE-SPECIFICATIONS/01` (strategy engine), `02` (signal to intent), `03` (risk engine), `06` (paper and backtest), `09` (exit monitor), `11` (mode promotion); ADR-003, ADR-004, ADR-009, ADR-020, ADR-059, ADR-061.

---

## Problem

The owner can define and backtest several strategies (ADR-061) but only `ema_adx` runs in the paper loop. The owner wants the others to run in paper too, to collect real forward evidence (the 50-day backtest is one falling market). Today the decision path assumes one strategy: `Runtime._decide` loads `ema_adx` only, a `PositionStop` is unique per (pair, origin), a fill carries no strategy, the paper promotion gate counts every PAPER sell, and paper entries are not checked against `max_open_positions` or the exposure caps (paper intents are recorded, never sent, so the Risk Engine is not in that path).

---

## What `docs/` Already Decides

| Decision | Source |
|---|---|
| A signal carries no size and no authority; intents are built from the stop distance; AI never touches an order | ADR-004, `05/02` |
| Every order passes the Risk Engine; no path skips it | ADR-009, CLAUDE.md |
| Paper and live books never mix; PAPER rows carry `origin = "PAPER"` and are replayed only by `replay_origin(..., "PAPER")` | FR-T28, `06` |
| A new strategy version starts in PAPER; no strategy leaves PAPER until the owner's thresholds exist and the evidence is there | ADR-003, ADR-020 |
| Promotion evidence of one strategy never includes another's backtest rows | ADR-059, ADR-061 |
| Stops are bot-side, one per position; a stop may tighten, never widen | ADR-007, `09` |
| An intent identity is a pure function of its inputs, so a restart cannot create a second intent for a candle | `05/02`, `intent_identity` |
| Long-only spot; the reference strategy and the library rules share one stop shape (close minus ATR multiple) | ADR-061 |

**Gaps this spec must settle (and an ADR, ADR-062, must record):**
1. Nothing says who owns a pair when two strategies both signal. This spec defines ownership.
2. Nothing attributes a fill or a stop to a strategy. This spec adds attribution.
3. Paper entries skip `max_open_positions` and the exposure caps. With several strategies that would make paper results look better than live could ever be. See Open Questions.
4. The promotion gate counts paper trades and drawdown per origin, not per strategy.

---

## Design

**Scope.** Only the PAPER origin changes. Strategies other than `ema_adx` are **PAPER-only**: they never create a LIVE intent, never reach `OrderManager.submit`, and `promote` is refused for them (`paper_only`). `ema_adx` keeps its current behaviour in every mode, and its intent identities and versions are unchanged. LIVE ownership is out of scope.

**Pair ownership (per origin).**
- A pair is *free* when the PAPER ledger holds no position in it and no `PAPER_RECORDED` BUY intent is pending for it.
- A pair is *owned* by the strategy that opened the position, that is, by the `strategy_id` of the BUY intent behind its opening fill. A pending BUY intent *claims* the pair for its strategy until the intent ends in `PAPER_FILLED`, `PAPER_UNFILLED`, `PAPER_EXPIRED` or `PAPER_VOID`.
- A strategy is shown `PositionState(long=True)` only for pairs it owns, and `long=False` for the rest.
- An ENTRY signal on a pair owned or claimed by another strategy is dropped, with the reason `pair_owned_by:<id>` in the cycle report.
- Only the owner's EXIT signal sells. A STOP exit sells for the owner (the stop was set by the owner's entry intent).
- Each cycle, enabled strategies are evaluated in ascending `strategy_id` order; the first to create an intent claims the pair. This is deterministic and replay-safe, and it is arbitrary: it favours alphabetically earlier ids. See Open Questions.

**Attribution.** A nullable `strategy_id` column on `order_intent`, written by the runtime for every new intent. `NULL` means `ema_adx` (every existing row is `ema_adx`). Fills and orders are attributed through `OrderRow.intent_identity`; STOP sells (no intent) are attributed to the owner of the pair at that moment, found from the opening BUY. A round trip (position 0 to quantity to 0) belongs to the strategy that opened it. The version string stays `<kind>-<hash>` (backtest evidence and `StrategyRow.version` keep matching), so the owner's id is **not** recoverable from the version; that is why a column is needed.

**Definition rule.** Two definitions with the same kind and identical numbers are refused at creation and edit (`duplicate_parameters`), because they would produce identical intent identities and one would silently shadow the other.

**Enabling.** A new setting `strategy_enabled:<id>` (in `trader_setting`), **default off**. Enabling registers the strategy (`Promotion.register(id, version)`, mode PAPER). Editing an enabled strategy gives a new version, registered as PAPER; an open position it owns stays owned by the id and is managed by the new version's EXIT signal and the stored stop. `ema_adx` is not affected by this flag. *Disabling* stops new entries and keeps managing an owned open position until it is flat. *Deleting* is refused while the strategy owns a position or has a pending intent (the existing delete guard is extended from the reference strategy to all).

**Shared paper account.** One paper account, one `start_equity_idr` (the owner's number, already set), one equity curve. Entry sizing uses that shared equity, so strategies are not isolated from each other. Per-strategy results are therefore measured on that strategy's own round trips, never on the account curve.

**Per-strategy paper measures.** Paper trade count, realised PnL, win rate, and a drawdown measured on the cumulative realised PnL of that strategy's own trades against `start_equity_idr`. The `ema_adx` promotion gate (`paper_activity`, `paper_drawdown`) switches from "all PAPER sells" to "its own". This is a new measure, labelled PAPER everywhere it appears.

**Shared limits in paper.** Paper entries are checked, at decision time and across all owners, against `max_open_positions`, `max_exposure_per_pair_pct` and `max_total_exposure_pct`, by reusing the Risk Engine's own rule functions if they can be called without side effects, otherwise by mirroring the three checks with a test that proves they agree. A refused entry is reported with the rule's reason and does not consume the candle's identity in a way that blocks a later retry (same behaviour as the live reconciliation wait). This changes `ema_adx`'s paper results, since it too is now checked.

**Resource cap.** At most 8 strategies may be enabled at once, a resource limit rather than a loss limit. It is a proposal and the owner can change it (see Open Numbers).

---

## Open Numbers

| Number | Owner-set? | Open question |
|---|---|---|
| `max_open_positions` | Stored limit; value on the VM to be read before deciding | Paper now obeys it. If it is 1, strategies serialise: one open position across all pairs and all strategies. See OQ below |
| `max_exposure_per_pair_pct`, `max_total_exposure_pct` | Owner-set | Applied to paper entries; no new number |
| `start_equity_idr` (paper) | Owner-set (74,000 IDR on the VM) | One shared account; no new number |
| Cap on enabled strategies | **Open** (proposed 8) | Resource cap, not a loss limit; the owner confirms or changes it. Never silently defaulted |
| Promotion thresholds (OQ-12) | Owner-set where set | Unchanged; now compared against per-strategy figures |
| Paper cost model | Owner-set; revised numbers not yet applied on the VM | Unchanged |

---

## Data Model

- [ ] One additive Alembic migration `0009`: `order_intent.strategy_id` nullable `String(48)`, indexed. No data rewrite, no drop, no reset (CLAUDE.md trap).
- [ ] `trader_rw` already inserts into and reads `order_intent`; the migration must be run as `trader_owner` and the privilege test extended to cover the new column. No new table.
- [ ] `origin` is already on every row; nothing new carries money as `float`.
- [ ] Idempotency is unchanged: the intent identity is `<version>|<pair>|<candle>|<side>`. The duplicate-parameters rule keeps it unique across owners of the same kind.
- [ ] `strategy_enabled:<id>` is a `trader_setting` row, written with an audit entry (`setting.update`), like every other setting.
- [ ] Retention: no change; intents are never deleted.

---

## API (operator)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| PUT | `/trader/v1/strategy-defs/{id}/paper` | `CONFIGURE_STRATEGY` | Enable or disable the strategy in the paper loop (`{enabled}`); refused for an invalid definition, past the cap, or when `ema_adx` (always governed by its own mode) |
| GET | `/trader/v1/strategy-defs/{id}/paper` | `VIEW` | Enabled flag, owned pairs, pending claims, per-strategy paper trades, PnL, win rate, drawdown; all labelled `origin: PAPER` |
| GET | `/trader/v1/strategy-defs` | `VIEW` | Gains `paper_enabled` and `paper_owned_pairs` |
| POST | `/trader/v1/strategies/{id}/promote` | existing | Refused with `paper_only` for any strategy other than `ema_adx` |

- [ ] Every route has a permission. None creates an order; none touches withdrawal.
- [ ] Idempotency-Key on mutations; audit on every mutation.

---

## Exchange Interaction

None. Paper never calls the exchange. LIVE behaviour is unchanged, and an architecture-level test asserts that a non-reference strategy cannot produce a LIVE row.

---

## Risk and Safety

- **Interacts with:** `max_open_positions`, exposure caps, the position stop, the promotion gate, the kill switch (a halted Trader still advances paper and still decides nothing new, as today).
- **On uncertainty, fail closed:** an unreadable ownership (a fill with no resolvable intent, two strategies claiming one pair after a bug) halts new paper entries for that pair and raises an alert; it never guesses an owner. A ledger replay error is already an integrity error.
- **A test that fails when the control is removed:** the PAPER-only wall (below) and the ownership rule (two strategies, one pair, one candle, exactly one intent).
- **Can this path skip the Risk Engine?** It never reaches an order. For LIVE it still goes only through `OrderManager.submit` for `ema_adx`, unchanged. The shared paper limits make the paper path stricter, not looser.
- **Can model output reach an order?** No; strategies are pure functions of candles and state.
- **Trap to avoid:** the reference strategy's version and identity must not change, or its stored backtest evidence and its registered version stop matching.

---

## Security

- [ ] No secrets involved; nothing new is logged beyond ids and reasons.
- [ ] No new outbound destination.

---

## Tests

- Unit: ownership resolution (free, claimed, owned, owner after a version change); attribution of a round trip including a STOP sell; per-strategy metrics and drawdown; duplicate-parameters refusal; cap on enabled strategies.
- Integration (mock exchange, SQLite): two strategies signal ENTRY on the same pair and candle, exactly one intent is created and the other reports `pair_owned_by`; a non-owner's EXIT is ignored and the owner's EXIT sells; a STOP sells for the owner; disabling keeps managing the open position; deleting is refused while it owns a position; a restart does not duplicate an intent.
- Acceptance: with `max_open_positions` set to 1, a second strategy's entry is refused with the limit's reason while the first holds a position; with it raised, both hold positions in different pairs.
- Negative authorization: an unauthorised user cannot enable, disable or promote; `promote` on a non-reference strategy returns `paper_only`.
- Guard: **no LIVE intent, order or fill can come from a non-reference strategy** (fails if the PAPER-only wall is removed); the architecture tests stay unedited; migration `0009` is additive and `-m postgres` passes with the privilege test.
- Regression: `ema_adx` produces byte-identical intent identities and the same paper result as before on a fixed candle series when it is the only enabled strategy (the shared-limit check aside, which has its own test).

---

## Open Questions

1. **Shared account or split capital.** Proposed: shared (one account, strategies compete for the same equity and limits), because it mirrors a single real account. Split capital would isolate strategies but is a different test, and the owner's account is Rp 74,000, too small to split.
2. **`max_open_positions` in paper.** If the stored value is 1, only one strategy holds a position at any time across the whole market, so most strategies would be starved and the comparison would mostly measure who signals first. Options: keep paper at the live value (honest to what live could do, poor for comparing strategies), or give paper its own higher value (good for comparison, but then paper no longer mirrors live limits and the evidence for promotion is looser). This is a loss-limiting number and is not defaulted here: the owner chooses.
3. **Tie-break on a same-candle collision.** Proposed: ascending `strategy_id`. Alternatives: skip both (nobody enters, unfair to nobody), or rotate by candle. Ascending id is simple and deterministic but favours early ids.
4. **Cap of 8 enabled strategies.** Confirm or change.

---

## Rollout

- [ ] Deployable without a coordinated cutover: yes. The migration is additive and nullable, and everything new is behind `strategy_enabled`, off by default. After deploy nothing changes until the owner enables a strategy.
- [ ] Order: migration `0009` as `trader_owner` first, then the Trader image, then the frontend. Deploy with `--no-deps` as always.
- [ ] Rollback: disable every strategy, then run the previous image (`eae6bc2`); the new column is nullable and the old code ignores it. An open paper position owned by a custom strategy is then managed by its stored stop only, so disable and let positions close before rolling back if possible.
- [ ] Touches orders: it does not create or send any exchange order; the PAPER-only wall is the thing to verify before enabling anything.
