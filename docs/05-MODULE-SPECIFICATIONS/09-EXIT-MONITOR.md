# 09 — Exit Monitor

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Risk Engineer, Trading Engineer |
| **Decided by** | ADR-006, ADR-007, ADR-011 |
| **Open items** | OQ-6 (resolved, ADR-041 and ADR-043) |

Enforces stop-loss and take-profit **inside the Trader**, because Trade API 2.0 offers no stop order
(`stop_limit_not_available`). This is the weakest point of the design and is documented as such.

## What It Does

For every open position it holds a stop price (set at entry from the ATR rule, recorded on the intent) and
an optional target. On each price poll:

1. Fetch last price and best bid/ask for all positions' pairs in **one** multi-symbol request.
2. If the price is at or through a stop: create a single `MARKET` sell for the position quantity through the
   Risk Engine's **emergency** profile.
3. If a target is a resting `LIMIT` sell, nothing to do until it fills; if the target is monitored instead,
   a normal `LIMIT` exit intent is created.

The polling interval is **10 seconds** (ADR-041). Reaction time to a stop is **at most that interval plus
processing**, and the real exit price depends on the book at that moment.

## Rules

- **One exit per position.** A position with a pending exit is not exited again; partial fills reduce the
  quantity the monitor protects.
- **A stop is never moved down.** It may be tightened (for example a trailing rule) but not widened, and any
  change is audited.
- **Stale price:** if the price is older than the freshness limit the monitor keeps using the best available
  value, marks the position **unprotected**, and raises `CRITICAL`. It does not pretend the stop is
  working.
- **Gap risk:** if the price jumps through the stop, the exit executes at the market, which may be far worse
  than the stop price. The record shows the stop price and the achieved price so slippage is visible.
- **Order of checks:** a stop takes precedence over a target when both conditions hold on the same poll.
- **No AI input.** A stop is never delayed or cancelled by an analysis result (ADR-004).

## Watchdog (FR-T20)

A separate heartbeat records the monitor's last successful cycle. If it has not advanced within
three missed polling cycles (30 seconds at the 10 second interval, ADR-041), the watchdog raises `CRITICAL` and, if the Trader is otherwise alive, requests
`HALT`. The watchdog must not share the poller's thread or failure domain, otherwise a hung poller would
hang its own alarm.

## When the Trader Is Down

**No stop exists.** The positions are protected only by the exposure limits that bounded them
(ADR-009) and by the owner reacting to the alert. This is an accepted residual risk (ADR-007) and the first
item in the threat model and the runbooks.

## State After Restart

On start the monitor rebuilds its positions from the ledger and the exchange (not from memory) and
immediately evaluates every stop against a fresh price before doing anything else. A position that is
already through its stop at restart is exited at once.

## Tests (planned)

A price crossing a stop emits exactly one `MARKET` exit; a stale price marks the position unprotected and
alerts; the watchdog fires when the poller stops; a restart evaluates stops first; a stop cannot be widened;
a vetoed or AI-unavailable state does not affect a stop.
