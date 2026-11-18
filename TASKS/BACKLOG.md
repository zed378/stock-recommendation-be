# Backlog — Open Questions, Specification Gaps, Deliberate Deferrals

Anything that needs an owner decision, or that was deliberately deferred, lands here so it has a consequence
rather than only a mention in a chat or a record.

**Rule:** a number that limits loss is never defaulted. It stays here until the owner sets it.

---

## Open Questions (need the project owner)

| ID | Question | Blocks | Referenced by |
|---|---|---|---|
| **OQ-1** | **RESOLVED 2026-11-14 (ADR-037).** The owner states legal, tax, and Indodax-terms aspects have been considered; no checklist gate. The author still recommends reading Indodax's terms on automated trading | n/a | `00-PROJECT-CONTEXT/04`, `06/10` |
| **OQ-2** | **RESOLVED 2026-11-14 (ADR-031).** Telegram, outbound only. Telegram's Bot API facts to be verified in T5-02 | T5-02 | `ADR-016`, `05/12`, `06/12` |
| **OQ-3** | Does a **TAPIv2 key** authenticate the **Deadman Switch** and the **Private WebSocket** token? Both are documented only with legacy auth. Learnable only with a real key | Reconsidering ADR-007, ADR-011 | `06/02`, `06/09`, `06/11` D15 |
| **OQ-4** | **OHLC details:** maximum range per request, 4H and 1D candle boundaries and time zone, whether an unfinished candle is returned, long-term availability of `/tradingview/history_v2` | T2-03, T3 | `02/05`, `03/03`, `06/05` |
| **OQ-5** | **Real fee, tax, clearing** for the owner's account, maker and taker; how to obtain the split (REST `myTrades` returns one combined `commission`) | T3-04 (cost model) | `05/05`, `05/06`, `06/10` |
| **OQ-6** | **RESOLVED 2026-11-14 (ADR-041, ADR-043).** Price poll 10 s; watchdog 3 missed cycles (30 s); order poll 10 s; lease TTL 15 s with a 5 s heartbeat | n/a | `02/05`, `05/09`, `NFR-T05` |
| **OQ-7** | **RESOLVED 2026-11-14 (ADR-044).** BTCIDR and ETHIDR; inactive until the liquidity filter (OQ-8) is set and passes | n/a | `ADR-005` |
| **OQ-8** | **Liquidity filter thresholds** (24h volume, spread) | T4-01 | `ADR-005` |
| **OQ-9** | **Risk numbers:** risk per trade percent; max daily loss; max drawdown; max consecutive losses; max open positions; per-pair and total exposure; max order value; price-deviation percent; freshness limit; cooldown; trading window; order rate limit | T4-01, T5-06 | `ADR-009`, `05/02`, `05/03` |
| **OQ-10** | **RESOLVED 2026-11-14 (ADR-036).** There is no automatic `FLATTEN` | T4-06 | `ADR-010`, `05/08` |
| **OQ-11** | **Reference strategy parameters:** `ema_fast`, `ema_slow`, `adx_period`, `adx_threshold`, `atr_period`, `atr_stop_multiple`, `cooldown_s`; and the held-out data policy | T3-02 | `ADR-019`, `05/01` |
| **OQ-12** | **Promotion thresholds** for every gate (the "four weeks" is decided). No strategy leaves `PAPER` until set | T5-03 | `ADR-020`, `05/11` |
| **OQ-13** | **DECIDED 2026-11-14 (ADR-032).** MVP without AI context; then option B (candle-in endpoint, T3-06) with the bridge record-only (T3-05). Both deferred to post-MVP | post-MVP | `06/13`, `08/01`, `08/07` |
| **OQ-14** | **RESOLVED 2026-11-14 (ADR-028).** New pages in the existing front end; the Trader verifies tokens through `GET /auth/me`. *Left to verify:* that the response carries the role needed, and adding a `trader` role to the platform's `UserRole` | T1-01, T5-04 | `02/02`, `07/00`, `09/01` |
| **OQ-15** | **RESOLVED 2026-11-14 (ADR-041).** Every 60 seconds | T4-07 | `ADR-022`, `05/10` |
| **OQ-16** | **Initial live capital** for `APPROVAL`, and rollout amounts | T5-06 | `ADR-020`, `05/11` |
| **OQ-17** | **RESOLVED 2026-11-14 (ADR-029).** A file secret on the host with strict permissions, read-only in the container, excluded from backups. Generation, path (`~/.aidss-trader-master.key`, `0600`), rotation, and re-entry procedure written in `09/02` and `10/06` R10 | T1-04 | `ADR-014`, `05/13`, `09/02`, `10/06` |
| **OQ-18** | **DECIDED 2026-11-14 (ADR-038).** T2-07 runs after the connector and mock exist; Phase A may run earlier at the owner's discretion. Still needs the owner's Read-only key | T2-07 | `06/03` to `06/11`, `06/14` |
| **OQ-19** | **RESOLVED 2026-11-14 (ADR-041).** Halt at 250 ms measured skew; the host must be NTP-disciplined | T2-05 | `NFR-T08`, `06/04` |
| **OQ-20** | **RESOLVED 2026-11-14 (ADR-040).** Manual off-host backups to an external disk or the owner's PC. Frequency and retention are the owner's (worksheet L1) | T6-03 | `10/04`, `03/06` |
| **OQ-21** | **RESOLVED 2026-11-14 (ADR-033).** `admin` may `HALT`; `CANCEL`, `FLATTEN`, resume stay with `trader` | T5-04 | `01/06`, `05/08` |
| **OQ-22** | **RESOLVED 2026-11-14 (ADR-035, ADR-042).** Maker-first at the touch, `MOC` on entries, `EXPIRE_TAKER`; reprice after 5 min, at most 3; approval expires in 1 h; `UNKNOWN` queried 5 times in 30 s | n/a | `05/02`, `05/04`, `05/07`, `06/10` |
| **OQ-23** | **RESOLVED 2026-11-14 (ADR-034).** Local midnight WIB (UTC+7) | T4-01 | `05/03` |
| **OQ-24** | **RESOLVED 2026-11-14 (ADR-030).** Public during development; **private before production (T5-06)**. While public, assume everything pushed is copied: no secret, configuration value, or owner number in the image | T1-01, T5-06 | `09/00` T20, `09/07`, `10/02` |
| **OQ-25** | **DEFERRED BY DECISION 2026-11-14 (ADR-045).** Whether to enable a veto, and its thresholds, are decided after the post-MVP evidence exists; thresholds are set before the evidence is read | post-MVP | `08/02`, `08/06` |
| **OQ-26** | **RESOLVED 2026-11-14 (ADR-039).** A host script with a read-only role alerts directly to Telegram. Known gap: nothing alerts if the host is down | T6-04 | `10/02`, `10/05` |

## Stage-11 owner follow-ups (2026-11-17)

- Off-host backup: run the prepared tool against the host personally, rehearse restoring that encrypted file in isolation, and choose frequency/retention (ADR-040). Fixture verification does not establish a real copy.
- Firewall: answer the per-port A/B/C/D questions and exact SSH/LAN source questions in `docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md`. Identify java 6547 and bridge clients. No rule is approved/applied; nft syntax, IPv6, timed rollback and persistence require a separate owner-led rehearsal.

## Specification Gaps Found While Writing the Documents

| Gap | Where | Action |
|---|---|---|
| Indodax documentation disagrees with itself in about twenty places | `06/11` | Phases A and B of T2-07 ran on 2026-11-18 and settled D1, D3 (read side), D10 to D13, D17, D18, D20, D21 (`06/11` Resolved); D2, D4 to D9, D14 to D16, D19 need phase C (a Trade key, T5-06) or stay documentation-only |
| The platform's `Timeframe` includes `H4`, but no market-data adapter was checked for 4H bars | `06/13` | Post-MVP (ADR-032) |
| Exchange `FILL` versus `FILLED` status in WebSocket examples | `06/11` D5 | Moot while WebSocket is deferred; unknown status halts |
| The exact interaction of mixed query and body parameters when signing | `06/04` | Signed GET observed 2026-11-18; a signed POST (create order) is phase C |
| `GET order` visibility lag after acceptance is stated but not quantified | `06/06` | T2-07, mock `visibility lag` |
| No `/api/pairs` fee fields on some pairs | `06/05` | Observed present on all 450 pairs (2026-11-18); still optional, and whether they include tax and clearing is OQ-5 |
| The analysis API connects to PostgreSQL as the bootstrap superuser, which bypasses every grant, so ADR-021's role isolation is not real until it uses a limited role | `deploy/trader/bootstrap.sql`, `deploy/trader/isolate_analysis_role.sql`, `deploy/trader/rollback_analysis_role.sql`, `deploy/trader/docker-compose.trader.yml` | **Plan and SQL ready (2026-11-15); rehearsed on local PostgreSQL 18 (7/7 `-m postgres` + rollback clean); awaiting owner approval** to run on `10.1.200.13` (`10/06` R13) |
| Saving an Indodax credential (`PUT /trader/v1/credentials/indodax`) refuses when no exchange URL is configured, because the endpoint tests the candidate key against the exchange before storing | `src/aidss_trader/api/app.py`, `/trader/credentials` | Expected fail-closed behavior; owner must configure `AIDSS_TRADER_INDODAX_BASE_URL` before saving an Indodax key |
| Frozen price-feed detection (`R5`): a feed returning HTTP 200 with stale/identical prices passes age-based freshness | `MEMORY/DECISIONS.md` ADR-052 (`proposed`, deferred by the owner 2026-11-17) | Owner chooses the option and thresholds after a paper run has produced price data |
| Per-pair strategy parameter overrides: one `EmaAdxParams` set currently applies to all allowlisted pairs | `MEMORY/DECISIONS.md` ADR-049 (`accepted (owner, 2026-11-16)`) | Single parameter set applies to all pairs; per-pair override design not adopted (reopen only if owner requests) |
| Pruning job for `trading.idempotency_key` (`DELETE` already granted to `trader_rw`; expired rows are ignored after 24h) | `MEMORY/DECISIONS.md` ADR-051 (`accepted (owner, 2026-11-16)`) | Opportunistic pruning (`_Replays._prune_expired` in `src/aidss_trader/api/app.py`) deletes expired (>24h) rows in its own transaction after `put()`; tested in `tests/trader/test_d_gaps.py` (`test_put_prunes_expired_rows_but_keeps_fresh_rows`, `test_pruning_failure_does_not_fail_put_or_request`); not yet run on VM PostgreSQL 16 |
| Out-of-process liveness cron (`deploy/trader/check_liveness.py`, Acceptance A13 verified on fake Telegram) | `docs/10-OPERATIONS/06-RUNBOOKS.md` R14 | Awaiting owner approval to install cron/systemd on `10.1.200.13` |
| Anchor freshness monitor (`deploy/trader/aidss-anchor-watch.sh`, `aidss-anchor-watch.cron` draft) | `docs/10-OPERATIONS/06-RUNBOOKS.md` R16 | Awaiting owner decisions on `AIDSS_ANCHOR_MAX_AGE_S` threshold and alert channel/hook (`AIDSS_ANCHOR_ALERT_CMD`) |
| Host firewall Stage 2 (non-AIDSS ports and `java` 6547); Stage 1 (`22`, `8000`, `9443` from `10.1.101.0/24` + `wt0`) rendered & `nft -c` validated (unapplied) | `docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md`, `deploy/host/firewall/inventory-clients.sh` | Awaiting read-only host client inventory (`inventory-clients.sh`) and owner per-port decisions before applying |
| Tamper-evidence design for the audit log | `09/04` | T1-05 ADR |
| Step-up authentication mechanism for high-impact actions | `09/01` | T5-01 ADR |
| The promotion gate for the backtest now reads stored BACKTEST runs (ADR-059, 2026-11-18) and refuses a typed figure. **Still typed by the owner:** `live_capital_used_idr` and `slippage_vs_paper_pct` for APPROVAL to AUTO, both measurable from the ledger and the paper book | `src/aidss_trader/api/app.py` (promote), `promotion/gates.py` | Owner decision, before any APPROVAL period produces evidence; a true portfolio backtest (with the open-position and exposure limits) would replace the per-pair sum |

## Deliberate Deferrals

| Item | Why deferred | Returns when |
|---|---|---|
| Market-data and private WebSockets | ADR-011 | Stops prove too slow, or the fee split is needed (`06/09`) |
| Deadman Switch | Legacy-auth only (ADR-007) | OQ-3 resolved |
| USDT pairs | ADR-005 | A new ADR |
| Intraday and scalping | ADR-012 | A new ADR |
| Pair auto-discovery | ADR-005 | A new ADR |
| AI-triggered strategies | ADR-004 | A new ADR and an amended language guard |
| Two-person rule, multiple users | ADR-015 | More than one operator exists |
| Email as a second alert channel | The owner declined it | A later decision |
| Tax reporting | OQ-1 | The owner asks |
| Mobile app or push beyond the chosen channel | Out of scope | n/a |

## Resolved

| ID | Resolved | By | Notes |
|---|---|---|---|
| OQ-14 | 2026-11-14 | ADR-028 | Operator screens in the existing front end; token check via `GET /auth/me` |
| OQ-17 | 2026-11-14 | ADR-029 | Master key in a host file secret |
| OQ-24 | 2026-11-14 | ADR-030 | Public in development, private before T5-06 |
| OQ-2 | 2026-11-14 | ADR-031 | Telegram, outbound only |
| OQ-13 | 2026-11-14 | ADR-032 | Decided: MVP without AI context, then option B (post-MVP) |
| OQ-21 | 2026-11-14 | ADR-033 | `admin` may `HALT` |
| OQ-23 | 2026-11-14 | ADR-034 | Local midnight WIB |
| OQ-10 | 2026-11-14 | ADR-036 | No automatic `FLATTEN` |
| OQ-22 (rules) | 2026-11-14 | ADR-035 | Rules decided; numbers still open |
| OQ-1 | 2026-11-14 | ADR-037 | Owner's responsibility; no checklist gate |
| OQ-18 | 2026-11-14 | ADR-038 | After the connector and mock exist |
| OQ-26 | 2026-11-14 | ADR-039 | Host script direct to Telegram |
| OQ-20 | 2026-11-14 | ADR-040 | Manual off-host backups |
| OQ-15 | 2026-11-14 | ADR-041 | Reconcile every 60 s |
| OQ-19 | 2026-11-14 | ADR-041 | Skew halt at 250 ms |
| OQ-6 (part) | 2026-11-14 | ADR-041 | Price poll 10 s, watchdog 3 cycles; order poll and lease TTL open |
| OQ-22 (numbers) | 2026-11-14 | ADR-042 | Reprice 5 min x 3; approval 1 h; UNKNOWN 5 in 30 s |
| OQ-6 (rest) | 2026-11-14 | ADR-043 | Order poll 10 s; lease TTL 15 s, heartbeat 5 s |
| OQ-7 | 2026-11-14 | ADR-044 | BTCIDR, ETHIDR (inactive until the liquidity filter passes) |
| OQ-25 | 2026-11-14 | ADR-045 | Deferred to the post-MVP evidence review |
