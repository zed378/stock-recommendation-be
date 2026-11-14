# 03 — Decision Log

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |

The authoritative record is `../../MEMORY/DECISIONS.md`. This file is the index. An ADR is never edited to
look better; a superseded one is marked and left in place.

| ADR | Decision | Status |
|---|---|---|
| 001 | Trading is a separate execution service; the analysis platform stays read-only | accepted |
| 002 | Indodax Trade API 2.0 is the API of record | accepted |
| 003 | Staged autonomy: PAPER, APPROVAL, AUTO per strategy | accepted |
| 004 | Deterministic rules decide; AI and Kronos are context and veto only | accepted |
| 005 | Pair universe is an explicit allowlist of IDR pairs | accepted |
| 006 | LIMIT-first orders; MARKET only for emergency exits | accepted |
| 007 | Stops are bot-side; watchdog and alerts; no Deadman Switch | accepted |
| 008 | Risk-based position sizing with absolute caps | accepted |
| 009 | Hard circuit breakers checked before every order | accepted |
| 010 | Tiered kill switch: HALT, CANCEL, FLATTEN | accepted |
| 011 | Market data by REST polling; no WebSocket in the first release | accepted |
| 012 | Swing horizon, 4H to daily candles | accepted |
| 013 | API key is Read plus Trade only; withdrawal never implemented | accepted |
| 014 | Credentials encrypted in the DB, managed in the UI; separate master key | accepted / proposed |
| 015 | Single owner; new TRADER role | accepted |
| 016 | Notifications in-app and to a mobile channel | accepted (channel open) |
| 017 | Documentation in English | accepted |
| 018 | Analysis-platform planning document archived | accepted |
| 019 | Reference strategy: EMA plus ADX trend-following | accepted |
| 020 | Strict measurable promotion gates | accepted (thresholds open) |
| 021 | Separate container, schema, and PostgreSQL role | accepted |
| 022 | Exchange is source of truth; reconcile; WAC PnL | accepted |
| 023 | Documentation mirrors the reference tree in full | accepted |
| 024 | Idempotent orders; unknown outcomes resolved by query | proposed |
| 025 | Money is `Decimal`, quantized to increments | proposed |
| 026 | Orders are written ahead of sending | proposed |
| 027 | Exactly one active Trader instance, by database lease | proposed |
| 028 | Operator screens in the existing front end; logins verified through the analysis API | accepted |
| 029 | The master key lives in a file secret on the host | accepted |
| 030 | Trader image public during development, private before production | accepted |
| 031 | Mobile alerts go to Telegram, outbound only | accepted |
| 032 | The MVP ships without AI context; the candle-in endpoint follows | accepted |
| 033 | The `admin` role may `HALT` | accepted |
| 034 | A day for the daily-loss limit is local midnight WIB | accepted |
| 035 | Order placement: maker-first at best bid or ask, `MOC` on entries, `EXPIRE_TAKER` | accepted (numbers open) |
| 036 | There is no automatic `FLATTEN` | accepted |
| 037 | Legal and tax considerations are the owner's; no checklist gate | accepted |
| 038 | The live read-only verification runs after the connector and mock exist | accepted |
| 039 | A host script outside the Trader alerts on a stale heartbeat, direct to Telegram | accepted |
| 040 | Off-host backups are manual | accepted |
| 041 | Timing: price poll 10 s, watchdog 3 cycles, reconcile 60 s, skew halt 250 ms | accepted (order poll and lease open) |
| 042 | Order placement numbers: reprice 5 min, 3 reprices, approval 1 h, UNKNOWN 5 queries in 30 s | accepted |
| 043 | Order poll 10 s; lease TTL 15 s, heartbeat 5 s | accepted |
| 044 | Initial allowlist: BTCIDR and ETHIDR (inactive until the liquidity filter passes) | accepted |
| 045 | Whether to enable an AI veto is decided later, with evidence | accepted |

## Deviations From the Reference Repository

The structure follows the Central Dashboard repository (`docs/`, `MEMORY/`, `TASKS/`, `CLAUDE.md`,
`AGENTS.md`). Differences, on purpose:

- Task IDs are `T<phase>-<seq>` to avoid clashing with other projects' `P<phase>` scheme.
- Categories are adapted: there is no "findings", "alerts and incidents", or connector-per-vendor catalogue.
  `03-DATA-MODEL` covers orders, positions, ledger, and risk; `05-MODULE-SPECIFICATIONS` covers the trading
  components.
- No `.cursorrules`, `.clinerules`, or `.windsurfrules` mirrors.
