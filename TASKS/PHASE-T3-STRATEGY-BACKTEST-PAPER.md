# Phase T3 — Strategy, Backtest, Paper

## Owner-requested extension: T3-07 — Indodax IDR signal builder

Status: locally implemented, awaiting review; not DONE, merged, deployed or promoted.
The owner selected Indodax spot IDR. Existing strategy interface, audited definitions,
PAPER ownership and intent sizing are implemented and reused; their phase review
statuses are not relabelled DONE by this extension. Spec refs: `05/01`, `07/01`,
`08/01`, ADR-068, `MEMORY/specs/T3-07-signal-decision-builder.md`.

Visual declarative entry/exit rules, explicit ATR/model parameters, separate model
review worker and append-only exact-candle review gate are implemented for PAPER.
Every owner number remains explicit. Acceptance and limitations are recorded in
`MEMORY/records/2026-11-20-signal-builder.md`. No completion of T3-05/T3-06's different
analysis-platform candle-in bridge, live gates or independent review is implied.

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T2 complete (T2-07 may follow if the owner schedules it later; the mock suffices for building) |
| **Exit criteria** | A deterministic strategy interface and the reference strategy; sizing; the order state machine; a paper executor and a backtest with a cost model and no look-ahead; the ledger and PnL; the analysis bridge is deferred to post-MVP (ADR-032) |

**Needs from the owner:** OQ-5 (costs), OQ-11 (parameters). AI context is post-MVP (ADR-032).

---

### T3-01 — Strategy interface and determinism tests

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-01 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/01-STRATEGY-ENGINE.md` |
| **Spec required** | no |

**Definition of Done**
- [ ] `evaluate(candles, params, position_state) -> Signal`; no network, database, clock, or random access
- [ ] A test that `strategy` imports nothing from the Trader
- [ ] Determinism and no-look-ahead tests

### T3-02 — Reference EMA plus ADX strategy

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T3-01 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/01` · ADR-019 |
| **Spec required** | yes |
| **Open numbers** | OQ-11 |

**Definition of Done**
- [ ] Entry, exit, ATR stop, re-entry rule; indicators from a tested implementation that **does not import
      `aidss`**
- [ ] Fixtures for entry, exit, none, insufficient history
- [ ] **No parameter value is set in code**; they come from configuration

**Abuse cases**
- Hard-coding the "usual" EMA periods and ADX threshold. They are the owner's (OQ-11).

### T3-03 — Signal to intent, sizing, quantization

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T3-01, T2-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/02-SIGNAL-TO-INTENT.md` |
| **Spec required** | yes |
| **Open numbers** | OQ-9 |

**Definition of Done**
- [ ] Risk-based sizing with floor rounding; minimums; caps; stop required
- [ ] Deterministic intent identity; veto hook (entries only)
- [ ] Tests `test_sizing_rounds_down_and_requires_stop`, `test_intent_explains_itself`
- [ ] Entry price per ADR-035 (best bid or ask, `MOC` on entries); the reprice wait and maximum reprices come from configuration, and unset blocks the intent

### T3-04 — State machine, paper executor, backtest, ledger, PnL

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T3-03, T1-03 |
| **Spec refs** | `docs/03-DATA-MODEL/02` · `04` · `docs/05-MODULE-SPECIFICATIONS/05` · `06` |
| **Spec required** | yes |
| **Open numbers** | OQ-5 |

**Definition of Done**
- [ ] The full order state machine, with every transition tested (shared with T4)
- [ ] Paper executor with conservative fill rules; zero signed order requests in `PAPER`
- [ ] Backtest with cost model, no look-ahead, stored parameters and data fingerprint
- [ ] Ledger and positions derived from fills; weighted average cost; PnL by origin; no mixing
- [ ] Tests `test_paper_mode_sends_no_order_request`, `test_backtest_has_no_lookahead`,
      `test_paper_limit_fills_only_if_traded_through`, `test_paper_and_live_pnl_never_sum`

**Abuse cases**
- A backtest that quietly uses the unfinished candle or a zero-cost model.
- Presenting backtest PnL without its label.

### T3-05 — Analysis context bridge (record-only)

| | |
|---|---|
| **Status** | DEFERRED (post-MVP, ADR-032) |
| **Depends on** | T3-03 |
| **Spec refs** | `docs/08-AI-AGENT/01` to `07` · `docs/06-INTEGRATIONS/13` |
| **Spec required** | yes |
| **Open numbers** | none for the MVP (ADR-045) |

**Definition of Done**
- [ ] Interface and typed schema; failure is non-blocking
- [ ] Context stored on the intent; no veto enabled
- [ ] Deferred to post-MVP (ADR-032); in the meantime no context is faked and no veto is enabled
- [ ] Test `test_veto_blocks_but_never_creates`

**Abuse cases**
- Fabricating context so the bridge "works".

### T3-06 — Candle-in forecast endpoint in the analysis platform (post-MVP, ADR-032)

| | |
|---|---|
| **Status** | DEFERRED (post-MVP, ADR-032) |
| **Depends on** | T3-05 (also deferred) |
| **Spec refs** | `docs/08-AI-AGENT/07-ANALYSIS-PLATFORM-CRYPTO-ADAPTER-SPEC.md` · `docs/06-INTEGRATIONS/13-AIDSS-ANALYSIS-PLATFORM.md` |
| **Spec required** | yes |
| **Open numbers** | none for the MVP (ADR-045) |

**Why:** Without it the Trader has no Kronos context for crypto pairs (`06/13`).

**Definition of Done**
- [ ] `POST /forecast/candles`: stateless, read-only, service-credential authenticated, strict schema that
      accepts **no account data**
- [ ] Validation per the spec; fixture mode deterministic; CPU runtime bounded and serialized
- [ ] The route name contains none of the architecture test's forbidden fragments
- [ ] `tests/test_architecture_constraints.py` passes **unmodified**
- [ ] The Trader's bridge calls it asynchronously at candle close and fails open

**Abuse cases**
- Adding an order-related identifier or table to the analysis platform.
- Letting the endpoint persist or log the owner's candles together with positions.
