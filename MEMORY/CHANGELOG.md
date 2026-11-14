# Changelog

Chronological summary of user-visible or operationally significant changes. Coarser than the records.

## 2026-11-14

- **Documentation:** the AIDSS Trader (Indodax crypto auto-trading) is specified in `docs/`, `MEMORY/`,
  `TASKS/`, `CLAUDE.md`, `AGENTS.md`, and `trader-document-catalog.md`. **No Trader code exists.**
- **Decisions:** ADR-001 to ADR-027 recorded (`DECISIONS.md`). Notable: separate execution service,
  Trade API 2.0 only, staged `PAPER`/`APPROVAL`/`AUTO`, deterministic rules with AI as veto, Read plus
  Trade key with no withdrawal code, tiered kill switch.
- **Moved:** `Dokumen_Perencanaan_AI_Investment_Decision_Support.md` to `docs/archive/` (`git mv`). The
  README's one reference to it was updated. Code comments citing "Section N" refer to that file's section
  numbers and are unaffected.
- **Decisions (later the same day):** ADR-028 (operator screens in the existing front end, logins verified via
  `GET /auth/me`), ADR-029 (master key as a host file secret), ADR-030 (Trader image public during
  development, private before production). OQ-14, OQ-17, OQ-24 resolved.
- **Decisions (batch 7):** ADR-043 (order poll 10 s; lease TTL 15 s, heartbeat 5 s), ADR-044 (allowlist BTCIDR
  and ETHIDR, inactive until the liquidity filter passes), ADR-045 (AI veto decided later, with evidence). 8 open
  questions remain: the live check (OQ-3, 4, 5) and the owner numbers (OQ-8, 9, 11, 12, 16).
- **Decisions (batch 6):** ADR-042 (reprice after 5 min, at most 3 times; approval expires in 1 hour; `UNKNOWN`
  queried 5 times in 30 s). OQ-22 closed; 11 open questions remain.
- **Decisions (batch 5):** ADR-041 (price poll 10 s, watchdog after 3 missed cycles, reconcile every 60 s,
  clock-skew halt at 250 ms). 12 open questions remain.
- **Decisions (batch 4):** ADR-037 (legal and tax are the owner's, no checklist gate), ADR-038 (live read-only
  check after the connector and mock), ADR-039 (host liveness script direct to Telegram; nothing alerts if the
  host is down), ADR-040 (manual off-host backups). 14 open questions remain.
- **Decisions (batch 3):** ADR-035 (maker-first at the best bid or ask, `MOC` on entries, `EXPIRE_TAKER`; its
  numbers stay open), ADR-036 (no automatic `FLATTEN`). 18 open questions remain.
- **Decisions (batch 2):** ADR-031 (Telegram, outbound only), ADR-032 (MVP without AI context; candle-in
  endpoint after), ADR-033 (`admin` may `HALT`), ADR-034 (daily loss day is local midnight WIB). 19 open
  questions remain.
- **Added documents (approved by the owner):** owner numbers worksheet, settings registry, live read-only
  verification plan, analysis-platform crypto adapter spec. Now 108 documents in `docs/`.
- **Operations note (analysis platform, same day):** images `zed378/aidss-api` and `zed378/aidss-frontend`
  were published to Docker Hub as **public** repositories at the owner's choice. The Trader image must not
  follow that (OQ-24).
