# T0 — Owner answers, batch 1, and four added documents

**Date:** 2026-11-14
**Task:** T0-01, T0-02 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-028 to ADR-030; the four new documents below

---

## Hook

Three open questions were answered by multiple choice, four extra documents were approved, and checking the
analysis API's code **corrected a claim in the earlier record**: crypto assets can be registered; the missing
piece for AI context is the market-data provider, not registration.

---

## What Changed

| Item | Detail |
|---|---|
| ADR-028 | Operator screens in the existing front end; token verification through `GET /auth/me` (OQ-14 resolved) |
| ADR-029 | Master key in a file secret on the host (OQ-17 resolved) |
| ADR-030 | Trader image **public during development, private before production** (OQ-24 resolved) |
| New documents | `01/08-OWNER-NUMBERS-WORKSHEET.md`, `03/08-SETTINGS-REGISTRY.md`, `06/14-INDODAX-LIVE-VERIFICATION-PLAN.md`, `08/07-ANALYSIS-PLATFORM-CRYPTO-ADAPTER-SPEC.md` |
| New tasks | T0-06 (owner fills the worksheet), T1-08 (token verification and the `trader` role), T3-06 (candle-in forecast endpoint, conditional on OQ-13) |
| Synced | About 25 documents and task cards that referred to the three answered questions; headers now say "resolved" or "custody decided" |
| Counts | 108 documents in `docs/`, 30 ADRs, 23 open questions |

---

## Why

The owner chose, in the interview:

| Question | Answer |
|---|---|
| Where do operator screens live, and how are logins verified? | New pages in the existing front end; verify through the analysis API |
| Where does the Trader image live? | "For now public; make it private after it is finished and in production" |
| Where does the master key live? | A file secret on the host with strict permissions, read by the container |
| Which extra documents? | All four offered: worksheet, live verification plan, settings registry, crypto adapter spec |

---

## Alternatives Considered

- **Registry visibility:** the author recommended private from the start. The owner declined. ADR-030 records
  the choice with its consequences (everything pushed while public is assumed copied) and ties the switch to
  private to a release-checklist item before T5-06.
- **Token verification:** sharing the JWT secret was rejected (a compromised Trader could mint tokens for the
  analysis platform).

---

## What Surprised Me

1. **Correction to `2026-11-14-trader-docs-scaffolding.md` ("What Surprised Me" #1).** That record said the
   analysis platform needs assets registered first and implied crypto could not be registered. Reading the
   code showed `POST /assets` (`AssetCreate`) accepts any `exchange` string, so `BTCIDR` on `INDODAX` can be
   created. The real gap is the **absence of an Indodax market-data provider**, plus a provider setting that
   appears global. `06-INTEGRATIONS/13` was corrected. The earlier record is left unedited.
2. **`GET /auth/me` already exists** and re-checks user status on every request, which makes ADR-028
   feasible without any change to how tokens are signed. Whether it carries the role the Trader needs is
   still to be verified (T1-08).
3. **Making the operator surface depend on the analysis API** means that if the analysis API is down, the
   screens cannot authorize. ADR-028 records that the command-line kill tool is therefore mandatory.
4. **Option A for crypto context is larger than it sounds** because provider selection looks global. That is
   why the adapter spec recommends option B first.

---

## Tests

Not applicable: documentation only. The consistency check was run:

- **126 files** checked earlier; all `NN-NAME.md` references resolved, OQ-1 to OQ-26 defined, ADR-001 to
  ADR-027 defined. After this batch the same check should be re-run for 108 documents and ADR-030.
- No code, test, or Docker file was changed. Nothing was committed.

---

## Definition of Done

- [x] Answers recorded as ADRs; synced across documents and task cards
- [x] Approved documents written, catalogued, and given tasks
- [x] This record written and indexed
- [ ] The owner has reviewed the new documents
- [ ] Re-run the reference consistency check (done at the end of this task; result in the final message)

**Waived:** none.

---

## Security and Compliance

- ADR-030 lets the Trader image be public in development. **While public, the image must contain no secret,
  no configuration value, no owner number, and no real strategy parameter**; those live in the database and the
  settings registry. A secret scan of image layers is required (S17).
- ADR-029 means anyone with root on the host can read the master key. The file is excluded from every backup.
- A production server password was shared in chat earlier in the session. It is in the conversation history,
  not in any file. It should be rotated.

---

## What to Watch

- `trader` role in the analysis platform: adding it touches `aidss` and must keep its architecture test
  unmodified (T1-08).
- The public Trader image: make it private before T5-06, and re-check that nothing sensitive was ever in a
  public layer.
- The worksheet is blank. Nothing can be enabled until the owner fills the relevant rows.

---

## What Was Not Determined

- Telegram or WhatsApp (OQ-2) and every owner number (OQ-5, OQ-6, OQ-9, OQ-10, OQ-11, OQ-12, OQ-15, OQ-16,
  OQ-22, OQ-23, OQ-25), OQ-7, OQ-8, OQ-13, OQ-1, OQ-3, OQ-4, OQ-18, OQ-19, OQ-20, OQ-21, OQ-26.
- Whether `GET /auth/me` carries the role needed (T1-08).
- Whether the analysis platform's provider setting is truly global (T3-06 and option A).

---

## Follow-Ups

`TASKS/BACKLOG.md` (23 open). Tasks: T0-06, T1-08, T3-06.

---

## Links

- ADR: ADR-028, ADR-029, ADR-030
- Previous record: `2026-11-14-trader-docs-scaffolding.md`
