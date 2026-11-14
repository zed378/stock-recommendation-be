# T0 — Trader Documentation Scaffolding

**Date:** 2026-11-14
**Task:** T0-01 to T0-05 (`TASKS/PHASE-T0-SPECIFICATION.md`)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `trader-document-catalog.md`; the reference repository's structure
(`Central Dashboard`: `docs/`, `MEMORY/`, `TASKS/`, `CLAUDE.md`, `AGENTS.md`)

---

## Hook

The owner asked for technical documents for an Indodax auto-trading system. Reading the code and the
exchange documentation first found four things that change what is possible: the analysis platform
**deliberately has no path to execution and no crypto data for its AI**, Indodax **has no sandbox**, the
trade key **cannot be IP-locked**, and the Trade API **has no stop order**.

---

## What Changed

Documentation and one file move. **No source, test, migration, or Docker change.**

| Item | Detail |
|---|---|
| New | `CLAUDE.md`, `AGENTS.md`, `trader-document-catalog.md` |
| New | `docs/` in 13 categories (about 100 files) |
| New | `MEMORY/` (this folder), `TASKS/` (phases T0 to T6, progress board, backlog) |
| Moved | `Dokumen_Perencanaan_AI_Investment_Decision_Support.md` to `docs/archive/` with `git mv` |
| Edited | `README.md`: the link to the moved file, and a note that its "no execution" statement describes the analysis platform |

---

## Why

The owner will implement crypto auto-trading with Indodax Trade API 2.0 and wanted the same documentation
discipline as the Central Dashboard repository, understood first and decided through questions.

### The Design Interview (six batches, multiple choice)

| Topic | Options offered | Owner's answer | ADR |
|---|---|---|---|
| Hard constraint "no execution" | Separate service; same process; remove globally | Separate execution service | 001 |
| Indodax API version | TAPI 2.0 only; TAPI 2.0 plus legacy for Deadman and WS; legacy only | TAPI 2.0 only | 002 |
| Autonomy | Staged; semi forever; fully automatic | Staged: paper, approval, auto | 003 |
| Signal source | Deterministic with AI filter; AI as trigger; both | Deterministic, AI as filter | 004 |
| Pairs | Allowlist IDR; allowlist plus discovery; all IDR; IDR and USDT | Explicit IDR allowlist | 005 |
| Order types | LIMIT-first, MARKET emergency; LIMIT only; MARKET | LIMIT-first | 006 |
| Stops | Bot-side plus watchdog; bot-side plus tight exposure; no auto stop | Bot-side plus watchdog and alert | 007 |
| Sizing | Risk percent of equity; fixed IDR; per strategy | Risk percent of equity | 008 |
| Circuit breakers | Loss; exposure; execution guards; cooldown and window | All four groups | 009 |
| Kill switch | Tiered; HALT and CANCEL; HALT only | Tiered | 010 |
| Market data | REST only; REST plus WS; build from ticks | REST only | 011 |
| Horizon | Swing; intraday; scalping | Swing (4H, 1D) | 012 |
| Key permission | Read plus Trade; separate keys; with withdrawal | Read plus Trade | 013 |
| Credential storage | Encrypted DB via UI; server secret file; secret manager | Encrypted DB via UI | 014 |
| Operators | One owner plus TRADER role; TRADER plus RISK_ADMIN; all investors | One owner plus TRADER | 015 |
| Notifications | In-app plus email; in-app only; in-app plus Telegram or WhatsApp | In-app plus Telegram or WhatsApp | 016 |
| Language | English docs; Indonesian; mixed | English | 017 |
| Docs breadth | Focused 35 to 45; full 100; minimal 15 | **Full mirror, about 100** | 023 |
| Old planning document | Keep; archive and update references; delete after migrating | **Archive** | 018 |
| Output | Docs only; plus skeleton; plus read-only prototype | Documents only | n/a |
| Reference strategy | Trend; breakout; mean-reversion; pluggable | Trend-following EMA plus ADX | 019 |
| Promotion gates | Strict; moderate; manual | Strict and measurable | 020 |
| Deployment | Separate container with schema and role; separate DB; separate host | Separate container, schema, role | 021 |
| Ledger | Exchange as truth with periodic reconciliation; daily; local | Exchange truth, periodic | 022 |

The author added ADR-024 to ADR-027 (idempotent orders, `Decimal` money, write-ahead orders, single
instance) as **proposed**, from evidence in the documentation, not from an answer.

---

## Alternatives Considered

- A focused 35 to 45 document set. The owner chose the full mirror (ADR-023). Consequence: some documents are
  short because little is decided, and they say so instead of inventing content.
- Deleting the planning document. Its 494 "Section N" citations in 301 source and test files cite section
  numbers, not the file path, so archiving costs one README edit and breaks nothing.

---

## What Surprised Me

1. **The analysis platform cannot supply AI or Kronos context for crypto.** No Indodax provider exists;
   assets must be registered and the code is built around exchange hours (`06-INTEGRATIONS/13`, OQ-13).
2. **Indodax publishes production URLs only.** There is no sandbox to test orders against, so the mock
   exchange and an owner-led read-only check carry all verification before real money.
3. **A trade-only key cannot be IP-restricted.** IP Permission exists only when Withdrawal is selected, which
   the owner correctly excluded (ADR-013). The residual risk is documented.
4. **No stop order.** `stop_limit_not_available`. Stops are bot-side, and **with the bot down there is no
   stop** (ADR-007).
5. **Indodax's documentation contradicts itself in about twenty places** (`06-INTEGRATIONS/11`), including
   which host serves Trade API 2.0, whether both order ids are required to cancel, `FILL` versus `FILLED`, and
   which rate limit applies to creates.
6. **`aidss.security.secrets` derives its Fernet key from `AIDSS_JWT_SECRET`.** Reusing it for the exchange key
   would tie the key's safety to a secret the analysis API also holds (ADR-014).
7. **The `commission` field combines fees and taxes**; the split exists only in the Private WebSocket, which is
   deferred (OQ-5).
8. **The analysis images were pushed to Docker Hub as public** on the same day, at the owner's choice. The
   Trader image must not be (OQ-24).

---

## Tests

Not applicable: documentation only. Nothing was run against code. The traceability tables name **planned**
tests; none exists.

- Verified commands in `CLAUDE.md` come from `README.md` and `pyproject.toml`, not executed in this task.
- The Kronos CPU timing in `08-AI-AGENT/03` was measured earlier the same day on the development machine
  (about 4 seconds per sample, 12 seconds for five), on synthetic input. It is a measurement, not a benchmark.

---

## Definition of Done

- [x] Documents written to the agreed structure and language
- [x] ADRs recorded; unanswered items listed as open questions
- [x] This record written and indexed
- [ ] **The owner has reviewed the documents.** Not done. T0 stays in `REVIEW` until they do
- [ ] Lint, typecheck, tests: not applicable (no code)

**Waived:** none.

---

## Security and Compliance

No security-relevant code change. Content: threat model, secrets policy, and the instruction never to copy
Indodax's sample keys. A password for the production server was given in chat during an earlier deployment
in this session; it is **not** recorded in any file, but it is in the conversation history and should be
rotated (see the deployment note in the owner's thread). No Indodax credential has been seen.

---

## What to Watch

- Documents that say "documented, not yet observed" are **not verified** against Indodax. Do not build on
  them as facts until T2-07.
- Several documents depend on owner numbers that are not set. Nothing in them is a default.
- The planning document move: `README.md` links to the new path.

---

## What Was Not Determined

- Every owner number: risk limits, thresholds, intervals, capital, strategy parameters (OQ-6, OQ-9, OQ-11,
  OQ-12, OQ-15, OQ-16, OQ-22, OQ-23, OQ-25).
- The notification channel (OQ-2), the operator surface (OQ-14), how the Trader gets analysis context
  (OQ-13), master key custody (OQ-17), backup location (OQ-20).
- Whether a TAPIv2 key works with the Deadman Switch or Private WebSocket (OQ-3), the OHLC candle
  boundaries (OQ-4), the real fee, tax, and clearing (OQ-5).
- Legal and tax position of automated crypto trading in Indonesia (OQ-1). Not analysed.
- The Telegram and WhatsApp facts: not researched.

---

## Follow-Ups

All in `TASKS/BACKLOG.md`: OQ-1 to OQ-26.

---

## Links

- ADR: `MEMORY/DECISIONS.md` ADR-001 to ADR-027
- Backlog: `TASKS/BACKLOG.md`
- Reference: the Central Dashboard repository's structure
