# T2-07 prepared: the live read-only verification script (not run)

**Date:** 2026-11-15
**Task:** T2-07 (owner-led; an agent prepares and stops)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/06-INTEGRATIONS/14`, `11`; ADR-013, ADR-038, ADR-041

---

## Hook

The first contact with the real Indodax API is now a script the owner can run once, on purpose, with its limits
enforced in code and tested against the mock. **It has never been run against the real exchange**, so every
Indodax shape in the integration documents is still "documented, not yet observed".

---

## What Changed

| Item | Detail |
|---|---|
| `python -m aidss_trader live-check` | Phase A (public, no key) and phase B (signed, read-only key from the owner's environment). Plan calls A1 to A7 and B1 to B7 |
| Limits in code | GET only; an allowlist of paths with no order, deposit, withdrawal, or fiat path; at most 60 requests, at least 1.5 s apart; explicit confirmation flag; both output directories must be outside any git repository |
| Stop conditions | `-2015`, rate limit, two server errors in a row, and any sign the key can withdraw or can trade (the plan allows a Read-only key only) |
| Redaction | Signed responses reduced to shape; public ones keep values, cut long lists, strip identifiers; known secrets scrubbed from any text |
| Output | A JSON report, a record draft that lists what was called and what was **not**, and raw responses in a directory outside the repository |
| Tests | 24 tests against the synthetic mock, including the limits, the stop conditions, that no key, secret, signature, `uid`, or balance reaches a file, and that the source contains no way to send anything but a GET |

## Not Done, Not Verified

- Nothing was called against the real exchange. The observation logic (units, candle boundary, host that serves
  Trade API 2.0, error code forms, `oriQty` versus `origQty`) was checked only against the mock's own answers, so
  it may need correcting once real responses arrive.
- B8 (the private WebSocket token) is not implemented on purpose; Phase C needs a Trade key and belongs to T5-06.
- A real response shape the script did not anticipate will be recorded as-is but not interpreted.
- The owner still has to: make a Read-only key for this check, run the phases, revoke the key, review the output,
  correct the mock and documents, and record the result (`docs/06-INTEGRATIONS/14`, "How the Owner Runs It").
