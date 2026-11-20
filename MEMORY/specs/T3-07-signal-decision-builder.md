# T3-07 — Configurable signal decision builder

Written 2026-11-20 before implementation. Requested by the owner in this session.

## Scope and existing decisions

ADR-004 keeps entry and exit deterministic; AI and Kronos can only block entries.
ADR-001 keeps analysis separate from execution. ADR-065 already provides an external
signal package and AI reviewer. This work adds an offline, SHADOW-only builder there,
using closed input candles, explicit rule configuration, the existing Kronos service,
and the existing gateway reviewer. It introduces no execution or publication path.
The owner selected Indodax spot IDR in this session. The first offline foundation is
extended with a deterministic `signal_builder` strategy kind in the Trader, persisted
through its existing audited strategy-definition API and edited by a visual rule form.
The existing per-strategy PAPER toggle, risk checks, ownership and conservative fills
are reused. Non-reference strategies retain their existing PAPER-only promotion guard.

## Indodax integration extension (written before integration code)

Move reusable declarative rules into `aidss_trader.strategy.rules` (no analysis imports).
An Indodax-only definition carries timeframe, entry/exit rules, ATR stop and cooldown,
plus required review thresholds/horizon/samples/data age. Every number remains explicit.
Stops are deterministic and checked before a signal becomes a sized intent.

New append-only `trading.builder_review` holds strategy id/version, pair/timeframe,
candle open, exact candle fingerprint, typed review outcome, generated time and
SHADOW evidence. Unique decision identity makes rescans idempotent. A separate worker
reads stored `indodax_ohlc` candles and enabled definitions, runs existing Kronos and AI,
and writes reviews. It never calls the exchange or order manager. The Trader consumes
only a typed pass for its own exact version/pair/timeframe/data fingerprint, with
owner-set freshness; pending/unavailable/vetoed evidence blocks entry. EXIT bypasses
reviews. The API exposes review history with VIEW permission. Existing setting changes
retain idempotency, audit, version reset and PAPER-only restrictions.

Worker is an explicit CLI `once`/`serve`; the owner selected a **300-second** poll
interval for the Indodax deployment.
It obtains public-candle work through two dedicated service-token routes. A random
token is mounted read-only from an owner-only file in both containers; it is never
placed in environment values, command arguments or logs. The API reads it per request,
checks file permissions and compares it in constant time. The identity can only request
builder work and submit reviews; it cannot configure strategies, read full settings,
read accounts or make orders. Its `signal_worker` role has only VIEW and
RECORD_BUILDER_REVIEW. The Trader validates exact work identity and appends the
review plus hash-chain audit row in one transaction. The worker separately uses the
analysis platform's existing read-only DB identity and JWT-derived provider decryption
setting for AI Gateway calls. The UI shows
PAPER limitations and review status, never a simulated result as a live fill.

Backtests for this strategy are explicitly rule-only (no historical model evidence,
no inference on future data) and may not stand in for combined-model evidence.

Tests: existing definition authorization/idempotency/audit; pure entry/exit/rules;
worker source rejection, idempotency, changed candle/config invalidation; PAPER entry
blocked without review and released only by matching fresh evidence; exits bypass
review; frontend editing and required parameters; architecture guards unmodified.

## Rules and decisions

Strict JSON configuration defines entry and exit groups (ALL or ANY), named operands
(close, EMA, RSI, ADX, volume ratio), comparisons and crossovers. Each rule records
its operands, result and missing-data status. Missing data in ANY is not a failed rule:
the whole group is unavailable. An existing long can emit EXIT or HOLD; a flat position
can emit ENTRY_CANDIDATE or HOLD. EXIT bypasses model review. There are no shorts.

Kronos and AI are required for entry candidates in this builder. A missing, stale,
malformed, fixture-provider or failed forecast blocks a candidate; AI SKIP or a score
below the owner-set minimum blocks it. Prediction return below the owner-set minimum
blocks it. Models never supply prices, quantities, stops or exits. Output is SHADOW,
not a fill, order or promotion approval. Each run records config hash and candle identity.

## Open numbers

All rule thresholds, forecast horizon and sample count, data/context maximum age and AI
score minimum must be supplied explicitly. No risk or trading number is defaulted.
No sizing, stop, take-profit, capital or loss limit is selected in this task. Existing
Risk Engine, intent sizing and promotion gates remain prerequisites to future execution.

## Kronos calendar

Add an explicit continuous-market option to the existing forecaster, default false for
compatibility. Crypto builder sets true so daily projections include weekends.

## Verification

Tests: rule groups and crossovers; missing indicators; closed/ordered/finite candles;
entry cannot be created by bullish models; exit never invokes models; model failures,
fixture provenance and stale data block entry; continuous daily timestamps include
weekends while the stock default skips them. Run hermetic suite and lint.

## Storage and rollout

Standalone CLI uses local inputs and stdout JSON. The Indodax integration uses the
Trader's existing audited definitions, migration 0013 and authenticated review API;
an operator token is supplied separately to the worker. Repeated work has the same
review identity; records cannot be replaced. No exchange call or deployment occurs
in this implementation session. Non-reference live promotion remains blocked.
