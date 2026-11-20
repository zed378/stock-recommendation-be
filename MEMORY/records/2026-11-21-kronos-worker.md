# Indodax Kronos/AI review worker activation

Owner requested the Kronos worker. Polling interval is 300 seconds, selected by the
owner after an explicit interval question. This is not a trade or order service.

## Scope and safety

- CPU-only, separate container; model work never runs in the Trader or stop path.
- Exact-candle Kronos and AI review are stored as append-only evidence. Missing or
  invalid evidence blocks PAPER entries.
- Dedicated random token file is owner-only/read-only and only authenticates the
  two builder work/review routes.
- Analysis DB identity is read-only; the JWT decryption setting is mounted from a
  protected host file for AI gateway configuration.
- Trader remains HALTED. No strategy/risk numbers, promotions, or order actions are
  changed.

## Deployment

Pending worker service rollout and health confirmation.

## What Was Not Determined

Pending.
