# 09 — Owner Numbers: Starter Profiles

| | |
|---|---|
| **Status** | **Proposed**, 2026-11-16. Written by the engineering agent because the owner asked for a prefilled starting point. **Not decided, not applied anywhere** |
| **Owner** | The Owner (every value here is theirs to change) |
| **Supersedes** | Nothing. `08-OWNER-NUMBERS-WORKSHEET.md` stays the thinking aid; this file is a filled draft of it |
| **Decided by** | ADR-055 (`proposed`) |
| **Machine-readable copies** | `deploy/trader/owner-defaults.rp50000.json`, `deploy/trader/owner-defaults.rp1000000.json` |

`08` says no number that limits loss has a default, and that is still true of the running Trader: an unset field keeps a strategy
disabled. These profiles are different in kind: they are **a draft for the owner to edit**, kept in a file, so the numbers do not have to
be invented one screen at a time. Nothing reads them at runtime. Loading them into an instance is a separate act by the owner.

Check an edited copy before typing it in:

```
python deploy/trader/check_owner_defaults.py deploy/trader/owner-defaults.rp50000.json
```

The checker builds the Trader's own value objects from the file (so a value the Trader would refuse is refused here) and tests the
relationships listed at the end of `08`. It prints `no problem found` or one `PROBLEM:` line per violation. It cannot say a number is wise.

## The two profiles

Both are **conservative**, 4H timeframe (ADR-012), pairs BTCIDR and ETHIDR (ADR-044). The difference is the account size, because on a
small account the exchange's minimum order, not preference, sets how much you must risk per trade.

| ID | Setting | Rp 1,000,000 | Rp 50,000 | Why |
|---|---|---|---|---|
| A1 | `risk_per_trade_pct` | 0.5 | **1.5** | Rp 5,000 and Rp 750 at the stop. At Rp 50,000, 0.5% sizes an entry near Rp 5,000, under any realistic minimum order, so every entry would be refused (see below) |
| A2 | `max_daily_loss_idr` | 15,000 | 1,500 | 3 full stops and 2 full stops (3% of equity at Rp 50,000); never below one stop (`08` rule 1) |
| A3 | `max_drawdown_pct` | 8 | 10 | Above the daily loss as a percentage, so it is the cumulative limit (`08` rule 5) |
| A4 | `max_consecutive_losses` | 4 | 4 | Four full stops in a row cost 2% of equity (Rp 1,000,000 profile) or 6% (Rp 50,000); a broken strategy should not keep going |
| A5 | `max_open_positions` | 2 | 1 | Two pairs are allowed; one position at a time on a tiny account |
| A6 | `max_exposure_per_pair_pct` | 25 | 40 | A5 x A6 must not exceed A7 (`08` rule 4) |
| A7 | `max_total_exposure_pct` | 50 | 40 | At least half (Rp 1,000,000) or 60% (Rp 50,000) of the account stays in cash |
| A8 | `max_order_idr` | 250,000 | 20,000 | Equals the per-pair cap, so a sizing bug cannot place more (`08` rule 2) |
| A9 | `price_deviation_pct` | 0.5 | 0.5 | Fat-finger guard around the best bid/ask for maker-first entries |
| A10 | `freshness_limit_s` | 60 | 60 | Six price polls (poll is 10 s, ADR-041); the watchdog is 30 s |
| A11 | `cooldown_s` | 900 | 900 | Between entries on one pair; the strategy has its own re-entry cooldown below |
| A12 | `trading_window` | unset | unset | Always open (24/7); unset is valid for this one field |
| A13 | `order_rate_limit` | 6 | 6 | Orders per minute, an internal throttle far below exchange limits |
| E1 | `ema_fast`, `ema_slow` | 20, 50 | 20, 50 | About 3 and 8 days of 4H candles; 50 bars needed, 300 are kept |
| E2 | `adx_period`, `adx_threshold` | 14, 25 | 14, 25 | The common trend-strength cut |
| E3 | `atr_period`, `atr_stop_multiple` | 14, 2.5 | 14, 2.5 | Stop 2.5 ATR below the entry |
| E4 | Timeframe | 4H | 4H | More signals than 1D, so four weeks of paper gives some evidence |
| E | `cooldown_s` (strategy) | 14,400 | 14,400 | No re-entry within one 4H candle of an exit |
| F1 to F4 | Maker, taker, tax, clearing (%) | 0.10, 0.20, 0.25, 0.05 | same | Maker and taker are the **headline fees Indodax publishes for BTCIDR and ETHIDR** (`GET /api/pairs`, 2026-11-17). Tax and clearing are **placeholders** chosen on the high side. `commission` on a real fill is fees plus taxes, so the real total is **not observed on your account (OQ-5)**; replace all four from your first real fills |
| F5, F6 | Paper slippage, partial-fill fraction | 0.20, 0.50 | same | Pessimistic on purpose |
| F | Paper start equity | 1,000,000 | 50,000 | Equals the account the profile is built for |
| G2, G3 | Min 24h quote volume, max spread | Rp 1,000,000,000, 0.10% | same | Set from a reading of the public `GET /api/summaries` on 2026-11-17 (05:22 UTC): BTCIDR 24h volume Rp 23.9 billion, ETHIDR Rp 4.9 billion; spread 0.0001% and 0.0030%, one price tick. The volume floor is about a fifth of the thinner pair's volume that day, so a large drop deactivates the pair; the spread cap is wide enough not to flap on a tick or two and still catches a thin book. One quiet 20-second window is a weak basis for the spread: look at it again on a volatile day. A pair that fails stays inactive, the safe direction |
| H1 | Backtest return after costs, out of sample | at least 0% | same | Weak on purpose; costs are included |
| H2 | Paper: minimum completed trades | 10 | 10 | Lower it if four weeks produce fewer on 4H; never after seeing results (`08` rule 11) |
| H3 | Paper: maximum drawdown | 6% | 8% | Tighter than the live limit A3 |
| H4 | Fill quality tolerance vs paper (slippage) | 0.30% | same | |
| I1 | Live capital gate | 1,000,000 | 50,000 | The whole account |

Left out because they are decided elsewhere: the day boundary (ADR-034), timing (ADR-041, ADR-043), order placement (ADR-035, ADR-042),
the four-week minimum (ADR-020), no automatic `FLATTEN` (ADR-036), and the AI veto (ADR-045, later). Not in the file because no field holds them
yet: the breaker-to-kill-switch mapping (J1) and operations numbers (L).

## What a small account has to know

- **The minimum order decides everything at Rp 50,000.** The sizing rule takes the smallest of the risk-based size and the caps, then refuses
  an order below the pair's minimum; it does not round up (`intents/builder.py`). With a 5% stop and Rp 10,000 as the minimum, an entry needs at
  least Rp 500 of risk, which is 1% of Rp 50,000. That is why A1 is 1.5% there. The checker enforces this (`PROBLEM: MINIMUM ...`).
- **The Rp 10,000 minimum order is observed, the 5% stop is not.** On 2026-11-17 the public `GET /api/pairs` (no key, no signature) reported
  `trade_min_base_currency` 10,000 IDR for both BTCIDR and ETHIDR, with `trade_min_traded_currency` 8.36e-06 BTC and 0.00029667 ETH, which is the same Rp 10,000 at current prices.
  So neither pair is blocked at Rp 50,000. The synthetic mock in the tests uses Rp 50,000 and 0.0001 BTC; those are fixture numbers, not Indodax's. The stop distance (`assumed_stop_pct`, 5%) is still an assumption: a tighter real stop sizes a larger position and loosens the minimum, a wider one tightens it.
  Minimums can change; read them again before relying on them.
- **Costs are large against Rp 50,000.** With the placeholder costs a round trip is about 0.9%, so a Rp 15,000 position pays about Rp 135 per trade against Rp 750
  of risk. A strategy needs a real edge after that. This is a reason to run the four weeks in `PAPER` first, not a reason to skip them.
- **A larger risk percentage is the price of a small account.** 1.5% of Rp 50,000 is Rp 750, but it is 1.5% of the account all the same. If that is more than you
  accept, the choice is more capital or accepting that no entry will happen.

## Using it

1. Copy the file for your account size and edit the values you disagree with. Keep `status` as `proposed` until you have decided; change it yourself.
2. Run the checker. Fix every `PROBLEM:` line or decide knowingly to keep a relationship broken (`08` says some may be intended).
3. Enter the values on the Trader screens (limits, strategy parameters, paper configuration, allowlist and liquidity filter, promotion thresholds). A limit change
   may ask for a step-up with your password. Rows you leave blank keep that strategy disabled. A change later is a new audited version.
4. Record what you decided and the date in `MEMORY/records/`, and answer the open questions in `TASKS/BACKLOG.md` (OQ-5, OQ-8, OQ-9, OQ-11, OQ-12, OQ-16).

Even with every number set, the instance starts `HALTED`, every strategy is in `PAPER`, and nothing is promoted without the evidence gates (ADR-020).
