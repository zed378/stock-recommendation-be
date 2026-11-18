# T2-07 phase A (public) and the first backtest (2026-11-18)

Both run on the owner's explicit instruction ("eksekusi nomor 2 dan 3"). Neither sends an order or a signed request.

## T2-07 phase A, run from the owner's workstation

`python -m aidss_trader live-check --phase A ... --i-understand-this-calls-the-real-exchange`, output directories outside any repository, raw responses deleted afterwards. 18 public GET calls, none stopped it, no rate-limit or server error. Observed (the script's own draft; the integration documents are NOT yet amended, which stays a person's step under the deviation protocol):
- D11: `server_time` is 13 digits (milliseconds); the candle endpoint's `Time` is 10 digits (seconds).
- D20: `trade_fee_percent`, `_maker`, `_taker` are present on all 450 pairs. D12: `price_precision` is an integer.
- A3: `price_increments` agrees with `pricescale` for 428 of 450 pairs; **22 disagree**. Not yet examined; the Trader reads increments from `price_increments`.
- A4: 4H candles end on 00, 04, 08, 12 UTC boundaries (the last candle's time is a multiple of the timeframe); the newest candle returned is still open when fetched (the Trader stores closed candles only, as designed); `Volume` is a string, prices are integers.
- D10: `BTCIDR`, `btcidr`, `btc_idr` all answered 200 on the v2 ticker. D1: `api.indodax.com` and `tapi.indodax.com` answered identically on the public v2 call.
- D17: invalid symbol, invalid limit, missing parameter return HTTP 400 with negative codes (-1121, -1130, -1102).
Not run: phase B (needs a **Read-only** key set in the owner's own terminal; the script stops at once if the key can trade, so the Read+Trade key in the Trader cannot be used), B8, phase C, the Deadman Switch.

## First backtest

`deploy/trader/run_backtest.py` (new, tested): reads the stored 4H candles (301 per pair, about 50 days), the parameters in force, the paper cost model and the risk limits; changes nothing the Trader acts on; read only unless `--record`. Run inside the Trader container on the VM. The allowlist held 18 pairs. Result with the owner's numbers (EMA 20/50, ADX 25, Rp 50,000 start, 1.5% risk): 16 trades in total over 9 pairs, **1 winner**; per-pair returns from -1.31% to +4.33%; their plain sum is about -0.25% (not a portfolio figure: each pair was run on the full capital separately). The one winner was ICNTIDR. All 18 runs were recorded to `backtest_run` (origin BACKTEST, `ran_by` `script:run_backtest (owner requested)`), nothing selected or tuned.
How to read it: a short sample, a trend-following rule over a period it evidently did not suit, costs and slippage from the owner's placeholder paper numbers, candle-level fills. It is not evidence that the strategy works, and it would not clear a 0% backtest threshold on an aggregate. The promotion gate reads a return the owner supplies, not these rows; the legacy helper `latest_backtest_return_pct` takes only the latest row (one arbitrary pair) and should not be used as the gate input as it is.
