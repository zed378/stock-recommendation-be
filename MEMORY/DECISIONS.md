# Decisions (ADRs)

Every architectural and product decision for the **AIDSS Trader** (Indodax crypto auto-trading)
subsystem, plus every deviation from `docs/`. Format:

```markdown
### ADR-NNN — <Title>

**Date:** YYYY-MM-DD
**Status:** proposed | accepted | superseded by ADR-NNN

**Decision:** <one or two sentences>

**Rationale:** <why this, in this context>

**Alternatives considered:** <what was rejected, and why>

**Implications:** <including the bad ones>
```

ADRs are **never edited to look better**. A superseded ADR is marked superseded and left in place.

**Status meaning.** `accepted` = the project owner chose it in the 2026-11-14 design interview (the
options and the answer are recorded in `MEMORY/records/2026-11-14-trader-docs-scaffolding.md`).
`proposed` = derived by the author from evidence, not yet confirmed by the owner. A `proposed` ADR is
safe to build on only where `TASKS/BACKLOG.md` says so.

Scope note: these ADRs govern the Trader. The analysis platform's own decisions live in
`docs/archive/Dokumen_Perencanaan_AI_Investment_Decision_Support.md` and are unchanged.

---

### ADR-001 — Trading is a separate execution service; the analysis platform stays read-only

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Order execution lives in a separate service (`aidss-trader`, Python package
`aidss_trader`) with its own container, credentials, and database role. The existing analysis platform
(`src/aidss`) keeps its "no order, no broker, no execution" hard constraint unchanged and keeps its
architecture test (`tests/test_architecture_constraints.py`) unmodified. The constraint is amended **only
for the crypto-trading domain, and only by this ADR**.

**Rationale:** The analysis platform states, in the archived planning document (sections 1, 3, 4) and in
FR-09, that it has no path to order execution, and enforces that with a test that scans `src/aidss` for
order tables, `/order` and `/trade` routes, and identifiers such as `place_order`. Keeping execution in a
separate package outside that tree preserves the guarantee for everything that already exists, and
limits the blast radius of a trading bug to one service.

**Alternatives considered:**
- A `aidss.trading` package in the same process. Rejected: needs an allowlist in the guard test, and puts
  the order path inside the process that serves analysis traffic.
- Removing the constraint globally. Rejected: it would also unlock stock (IDX) execution, which nobody
  asked for.

**Implications:** Two deployables to build, release, and monitor. A new guard test is required to keep
the boundary honest (`aidss` must not import `aidss_trader`, and the reverse is limited to a documented
read-only interface). The README's "no execution" statement must be qualified to say it describes the
analysis platform.

---

### ADR-002 — Indodax Trade API 2.0 (TAPI v2) is the API of record

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Orders, cancels, balances, and order/trade history use Trade API 2.0 (`/api/v2/...`,
HMAC-SHA256, `X-APIKEY` + `Sign` headers, a dedicated TAPIv2 key). The legacy private API
(`https://indodax.com/tapi`, `method=trade`, HMAC-SHA512) is **not used**. Candle history comes from the
public REST endpoint `/tradingview/history_v2`, which is unauthenticated.

**Rationale:** The official docs say existing legacy integrations must migrate and that legacy `method`
parameters will be decommissioned on a date to be announced.

**Alternatives considered:** TAPI 2.0 plus a legacy key for the Deadman Switch and Private WebSocket
(rejected for now: two keys, two auth schemes). Legacy only (rejected: scheduled for removal).

**Implications:** The Deadman Switch (`/countdownCancelAll`) and the Private WebSocket order-update token
are documented only with legacy auth, so they are **unavailable** under this decision (see ADR-007 and
ADR-011). Whether a TAPIv2 key works with them is unverified (`BACKLOG.md` OQ-3). The OHLC endpoint
lives on the public host that also serves the legacy public API; its long-term status is unknown
(`BACKLOG.md` OQ-4).

---

### ADR-003 — Staged autonomy: PAPER, APPROVAL, AUTO per strategy

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Every strategy runs in exactly one mode. `PAPER` simulates fills and never contacts the
order endpoint. `APPROVAL` creates an order only after the owner approves the specific intent. `AUTO`
creates orders from valid intents without approval, still bounded by every risk limit. Promotion between
modes requires the measurable gates in ADR-020. A new or changed strategy starts in `PAPER`.

**Rationale:** The account holds real funds, and the system's value depends on being trustworthy before
it is autonomous.

**Alternatives considered:** Semi-automatic forever (rejected by the owner as a permanent ceiling);
immediately fully automatic (rejected: no evidence yet).

**Implications:** Mode is a first-class field on strategy, intent, order, and audit rows. Paper results
must be labelled everywhere they appear and can never be presented as real fills.

---

### ADR-004 — Deterministic rules decide; AI and Kronos are context and veto only

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Strategies are deterministic, testable rules that decide entries and exits. Output from the
analysis platform's AI agents and from Kronos-base (CPU) may be attached to an intent as context and may
**veto** an entry. They never create, size, price, or modify an order.

**Rationale:** The analysis platform deliberately forbids execution language in model output
(`aidss.prompts.language`) and computes confidence deterministically. Wiring a model's words to an
exchange order would invert both.

**Alternatives considered:** AI recommendation as trigger (rejected: needs the language guard amended and
is harder to audit); per-strategy choice (deferred: more documents and tests).

**Implications:** A veto is an additional reason to not trade, never a reason to trade. A missing or
failed AI/Kronos result must not block a strategy unless that strategy is configured to require it;
the default is "context unavailable, rules proceed".

---

### ADR-005 — Pair universe is an explicit allowlist of IDR pairs

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The Trader may trade only pairs on an owner-maintained allowlist of IDR-quoted pairs. A
pair is automatically suspended while it fails the liquidity filter (24-hour volume and spread
thresholds, `BACKLOG.md` OQ-8) or the exchange reports it suspended or in maintenance.

**Rationale:** Indodax lists hundreds of pairs with very different liquidity and minimum order sizes.

**Alternatives considered:** Auto-discovery with approval; all pairs that pass a filter; IDR plus USDT.
All rejected for the first release; USDT adds a second quote currency to accounting and risk.

**Implications:** Adding a pair is an audited configuration change. USDT pairs are out of scope.

---

### ADR-006 — LIMIT-first order policy; MARKET only for emergency exits

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Entries and normal exits use `LIMIT` orders (`GTC`, optionally `MOC` so the order is
always a maker). `MARKET` is used only for stop-loss exits, kill-switch `FLATTEN`, and other emergency
liquidation.

**Rationale:** Fees are asymmetric. The public pairs sample shows 0.1 percent maker and 0.2 percent taker,
and each fill also carries tax and clearing charges (Private WebSocket `fillInformation`). Using `MARKET`
only when certainty matters keeps costs down without risking an unfilled stop.

**Alternatives considered:** LIMIT only (rejected: a stop may never fill in a fast fall); MARKET for
everything (rejected: taker fees and slippage).

**Implications:** The Order Manager needs fill timeouts, cancel-and-reprice rules, and partial-fill
handling. `BUY MARKET` can only be expressed as `quoteOrderQty` in IDR.

---

### ADR-007 — Stops are bot-side; a watchdog and alerts cover bot failure; no Deadman Switch

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Trade API 2.0 rejects `STOP_LIMIT` (`stop_limit_not_available`), so stop-loss and
take-profit are enforced by the Exit Monitor inside the Trader. A watchdog detects a stalled Trader or
price feed and raises a critical alert. The Deadman Switch is not used (ADR-002).

**Rationale:** There is no exchange-side stop to rely on.

**Alternatives considered:** Tight exposure limits as the only mitigation; take-profit only with no
automatic stop. Both rejected as the primary design.

**Implications:** While the Trader or its price feed is down, **open positions have no stop**. This
residual risk is accepted by the owner and is listed in `docs/09-SECURITY-PRIVACY/00-THREAT-MODEL.md`
and `docs/10-OPERATIONS/06-RUNBOOKS.md`. Exposure limits (ADR-009) bound its size.

---

### ADR-008 — Risk-based position sizing with absolute caps

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Quantity is `equity x risk_percent / (entry - stop)`, rounded down to the pair's quantity
increment, then clamped by per-pair exposure, total exposure, and an absolute IDR cap per order. Equity
is read from the exchange account balances. An order below the pair's minimum is not placed.

**Rationale:** Sizing from stop distance makes every trade lose about the same amount if its stop
holds.

**Alternatives considered:** Fixed IDR per trade; owner choice per strategy.

**Implications:** Every entry intent must carry a stop. A strategy with no stop cannot be sized and is
rejected at validation.

---

### ADR-009 — Hard circuit breakers, checked before every order

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The Risk Engine enforces, outside any strategy's control: maximum daily loss, maximum
drawdown from peak equity, halt after N consecutive losses; maximum open positions, per-pair exposure, and
total exposure; a price-deviation guard against fat-finger prices, a stale-data guard, and an internal
rate throttle below Indodax's limits; per-pair cooldown and a configurable trading window. Numeric
values are owner-set (`BACKLOG.md` OQ-9).

**Rationale:** A strategy bug must not be able to exceed a limit.

**Alternatives considered:** None for the set; the owner selected all four groups.

**Implications:** Every limit has a named test. There is no code path from a strategy to the exchange that
does not pass the Risk Engine.

---

### ADR-010 — Tiered kill switch: HALT, CANCEL, FLATTEN

**Date:** 2026-11-14
**Status:** accepted

**Decision:** `HALT` stops new orders. `CANCEL` is `HALT` plus cancelling all open orders. `FLATTEN` is
`CANCEL` plus closing all positions with `MARKET`. Each can be triggered manually (UI or API) or by a
circuit breaker, with the tier per trigger configured by the owner. Automatic `FLATTEN` is limited to
conditions the owner lists (`BACKLOG.md` OQ-10).

**Rationale:** Different incidents need different responses, and flattening in a thin market is itself a
cost.

**Alternatives considered:** HALT and CANCEL only; HALT only.

**Implications:** The kill switch must work when the Strategy Engine is broken, so it is a separate
component with its own tests. It is the highest-priority control in the system.

---

### ADR-011 — Market data by REST polling; no WebSocket in the first release

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Candles come from `/tradingview/history_v2`, prices from `/api/v2/ticker/price` and
`/api/v2/ticker/bookTicker`, order and fill state from `GET /api/v2/openOrders`, `GET /api/v2/order`,
`GET /api/v2/order/histories`, and `GET /api/v2/myTrades`. Market-data and private WebSockets are
deferred.

**Rationale:** Simplest to test, matches the swing horizon (ADR-012), and avoids the legacy-auth Private
WebSocket token (ADR-002).

**Alternatives considered:** REST backfill plus WebSocket live; candles built from ticks.

**Implications:** Stop reaction time equals the Exit Monitor's polling interval (`BACKLOG.md` OQ-6).
Order-status latency is polling latency. Public rate limits (180 or 300 requests per minute per IP) bound
the number of pairs and the polling interval together.

---

### ADR-012 — Swing horizon: 4-hour to daily candles

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Decisions are made on 4H and 1D candles. Scalping and intraday horizons are out of scope.

**Rationale:** Compatible with CPU-only Kronos inference, REST polling, and 0.1 to 0.2 percent fees per
side.

**Alternatives considered:** Intraday 15m to 1H; scalping at 1m or less.

**Implications:** The available timeframes are 240 (4H) and 1D from the OHLC endpoint. There is no 5 minute
timeframe in the docs.

---

### ADR-013 — API key is Read plus Trade only; withdrawal is never implemented

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The Trader's key has Reading and Spot Trading permission only. At startup and on every
reconciliation the Trader calls `GET /api/v2/account` and refuses to run if `canWithdraw` or
`canWithdrawFiat` is true. No withdrawal, deposit-address, or fiat endpoint client exists in the code.

**Rationale:** The worst outcome of a leaked trade key should not include moving funds out.

**Alternatives considered:** Separate Read and Trade keys; a key including Withdrawal.

**Implications:** Indodax offers IP restriction only when Withdrawal is selected, so this key **cannot be
IP-locked**. A leaked key could place or cancel orders. That risk is accepted, mitigated by key storage
(ADR-014), limits (ADR-009), and rotation, and documented in the threat model.

---

### ADR-014 — Credentials are stored encrypted in the database and managed through the UI

**Date:** 2026-11-14
**Status:** accepted (storage); the separate master key is **proposed**

**Decision:** The Indodax API key and secret are stored encrypted (Fernet) in the Trader's schema, entered
through an admin screen, never returned by the API (masked hint only), and every change is audited.
**Proposed:** the encryption key is a dedicated `AIDSS_TRADER_MASTER_KEY`, not derived from
`AIDSS_JWT_SECRET`.

**Rationale:** Follows the existing `ai_providers` pattern. The proposed separation exists because
`aidss.security.secrets` derives its Fernet key from `AIDSS_JWT_SECRET`; if the Trader reused it, a
database dump plus the JWT secret held by the analysis API would recover the exchange key.

**Alternatives considered:** Server-side secret file only; external secret manager.

**Implications:** Rotating the master key makes stored credentials unreadable until re-entered. Backups
must not place the master key beside the dump.

---

### ADR-015 — Single owner; a new TRADER role

**Date:** 2026-11-14
**Status:** accepted

**Decision:** One owner operates the Trader. A new role, `TRADER`, carries the trading permissions
(`docs/01-PRODUCT-REQUIREMENTS/06-ROLE-PERMISSION-MATRIX.md`). Existing roles (`viewer`, `investor`,
`admin`) are read-only for trading data.

**Rationale:** One operator today; a second approver is not available.

**Alternatives considered:** `TRADER` plus `RISK_ADMIN` (two-person rule); every investor trades.

**Implications:** No two-person control exists for promotion to `AUTO` or for raising limits. The audit
log and the promotion gates (ADR-020) are the compensating controls.

---

### ADR-016 — Notifications go in-app and to a mobile messaging channel

**Date:** 2026-11-14
**Status:** accepted (in-app plus mobile push); **the channel is not chosen**

**Decision:** Trading events appear in the in-app notification centre and are also pushed to the owner's
phone through Telegram or WhatsApp. The owner answered "Telegram/WhatsApp" without picking one
(`BACKLOG.md` OQ-2). Trading events use a vocabulary separate from the analysis platform's closed
`NotificationEvent` set.

**Rationale:** A "Trader is down" alert is useless if it only appears in an app nobody has open.

**Alternatives considered:** In-app only; in-app plus email.

**Implications:** A new outbound integration and secret. Message content may reveal positions, so it is
redacted per `docs/09-SECURITY-PRIVACY/05-SENSITIVE-DATA-REDACTION.md`.

---

### ADR-017 — Documentation is written in English

**Date:** 2026-11-14
**Status:** accepted

**Decision:** `docs/`, `MEMORY/`, `TASKS/`, `CLAUDE.md`, and `AGENTS.md` are in English. Conversation with
the owner is in Indonesian.

**Rationale:** Consistent with the reference repository and with technical terms that have no stable
Indonesian equivalent.

**Alternatives considered:** Indonesian throughout; Indonesian docs with English agent files.

**Implications:** None beyond style.

---

### ADR-018 — The analysis platform planning document is archived, not deleted

**Date:** 2026-11-14
**Status:** accepted

**Decision:** `Dokumen_Perencanaan_AI_Investment_Decision_Support.md` moved to `docs/archive/` with
`git mv`. Its content is unchanged. The README's one reference to it was updated.

**Rationale:** About 494 "Section N" citations in 301 source and test files refer to its section
numbers. They cite section numbers, not the file path, so moving the file leaves them valid.

**Alternatives considered:** Leave in place; delete after migrating content (rejected: the content is the
specification of the analysis platform and is not migrated).

**Implications:** The citations still resolve to the same sections, now in the archive.

---

### ADR-019 — Reference strategy: EMA plus ADX trend-following, swing

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The first fully specified strategy is trend-following using EMA and ADX on 4H or 1D
candles, with an ATR-based stop. The strategy interface is pluggable so others can follow.

**Rationale:** Low trade frequency suits the fee structure and the swing horizon.

**Alternatives considered:** Breakout with volume confirmation; mean-reversion (RSI plus Bollinger).

**Implications:** Indicator values come from the analysis platform's deterministic indicator engine or an
equivalent tested implementation (`docs/05-MODULE-SPECIFICATIONS/01-STRATEGY-ENGINE.md`). Parameters are
not tuned yet (`BACKLOG.md` OQ-11).

---

### ADR-020 — Mode promotion requires strict, measurable gates

**Date:** 2026-11-14
**Status:** accepted (principle); **thresholds are open** (`BACKLOG.md` OQ-12)

**Decision:** `PAPER` to `APPROVAL` requires a passing backtest with realistic fees, tax, and clearing,
at least four weeks of paper trading, a minimum trade count, and drawdown within limit. `APPROVAL` to
`AUTO` requires at least four weeks live with small capital, reconciliation with no unexplained
difference, and no unexplained kill-switch event.

**Rationale:** Autonomy must be earned with evidence.

**Alternatives considered:** Moderate gates; owner-discretion only.

**Implications:** The numbers in the gates are not set and must be set by the owner before any promotion.
Until then no strategy may leave `PAPER`.

---

### ADR-021 — Isolation: separate container, separate schema, separate PostgreSQL role

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The `trader` service runs as its own container in the same Docker Compose project, using
the existing PostgreSQL server and database but a dedicated schema (`trading`) and a dedicated
PostgreSQL role. The analysis API's role has no write privilege on `trading`, and the Trader's role has
no write privilege outside it. It has its own Alembic history, its own image, and its own package
(ADR-001).

**Rationale:** One host and one backup, with the access boundary enforced by the database.

**Alternatives considered:** Separate database; separate host.

**Implications:** One shared PostgreSQL instance remains a shared failure domain. Backup and restore of the
`trading` schema must be rehearsed (`docs/10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md`).

---

### ADR-022 — The exchange is the source of truth; reconcile periodically; PnL by weighted average cost

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Indodax is authoritative for balances, orders, and trades. The local ledger is append-only,
built from fills. On start and at a fixed interval the Trader compares orders, trades, and balances with
Indodax. Any difference triggers `HALT` and an alert; it is never silently corrected. PnL uses weighted
average cost, and fee, tax, and clearing are recorded separately.

**Rationale:** A timed-out order or a fill outside the bot would otherwise make local state diverge.

**Alternatives considered:** Daily reconciliation; the local ledger as the source of truth.

**Implications:** Reconciliation consumes rate limit. History endpoints cap their range at 7 days
(`order/histories`, `myTrades`), which bounds how far back a reconciliation can look.

---

### ADR-023 — The documentation set mirrors the reference tree in full

**Date:** 2026-11-14
**Status:** accepted

**Decision:** `docs/` follows the reference repository's 13-category structure at full breadth (about 100
files), adapted to the trading domain. Where a decision does not exist yet, the document says so and
points to `BACKLOG.md`; it does not invent one.

**Rationale:** The owner asked for a full mirror.

**Alternatives considered:** A focused 35 to 45 file set; a minimal 15 file set.

**Implications:** Some documents are short because little is decided. That is intended.

---

### ADR-024 — Orders are idempotent and unknown outcomes are resolved by query, never by retry

**Date:** 2026-11-14
**Status:** proposed

**Decision:** Every order is created with a deterministic `newClientOrderId` (letters, digits, `_`, `-`,
at most 36 characters) derived from its intent. After a timeout or a 5xx on create or cancel, the Order
Manager queries by `clientOrderId` before doing anything else and never re-sends the create blindly.

**Rationale:** The create endpoint reports success only that the order was accepted, and the order "may not
be immediately available" through `GET /api/v2/order`. A blind retry could place a second order.
Indodax also rejects duplicate client order IDs (`-2010`), which makes the ID a usable idempotency key.

**Alternatives considered:** Retry with a fresh ID (rejected: duplicates).

**Implications:** A new order state, `UNKNOWN`, with its own resolution and alerting rules.

---

### ADR-025 — All money and quantities are `Decimal`, quantized to the pair's increments

**Date:** 2026-11-14
**Status:** proposed

**Decision:** Prices, quantities, balances, fees, and PnL are `Decimal` (stored as `NUMERIC`), never
`float`. Quantities are rounded down to `quantity_increment` and prices to the pair's price increment from
`/api/pairs` and `/api/price_increments`.

**Rationale:** The API returns prices and quantities as strings, and rejects a quantity with more
precision than allowed (`-1130`).

**Alternatives considered:** `float` (rejected: rounding error in an accounting system).

**Implications:** A test asserts no `float` reaches the ledger or the order payload builder.

---

### ADR-026 — Orders are written ahead of sending

**Date:** 2026-11-14
**Status:** proposed

**Decision:** The Order Manager persists and commits the order row (state `SUBMITTING`, with its
`clientOrderId`) **before** it sends a create request, and updates it after the response. If persisting
fails, no request is sent.

**Rationale:** If the process dies after sending and before recording, the Trader would not know an order
may exist. A write-ahead row means every possible exchange-side order has a local trace that the next start
resolves by querying `clientOrderId` (ADR-024).

**Alternatives considered:** Record after the response (rejected: a crash window loses knowledge of a live
order); rely on reconciliation alone (rejected: slower, and it would halt trading for a case the design can
handle).

**Implications:** A database outage halts trading, which is intended. Each create costs one extra committed
write before the request, which is negligible at swing frequency.

---

### ADR-027 — Exactly one active Trader instance, enforced by a database lease

**Date:** 2026-11-14
**Status:** proposed

**Decision:** The Trader acquires and renews a lease in the `trading` schema before it evaluates
strategies or sends any order. An instance that cannot hold the lease idles. A holder that stops renewing
loses it.

**Rationale:** Two instances sending orders for the same strategy would duplicate them. The analysis
platform already uses a self-healing lease for its scheduler (`aidss.jobs.leader`), so the pattern is
proven in this code base.

**Alternatives considered:** A PostgreSQL advisory lock (rejected: ties correctness to connection
lifetime and is not portable to the SQLite test path); relying on deployment to run one container
(rejected: a deployment mistake would then lose money).

**Implications:** A short window after a crash during which no instance trades, until the lease expires.
Stops are unmonitored during that window (ADR-007); the lease timeout is therefore a safety setting
(`TASKS/BACKLOG.md` OQ-6 covers the related polling interval).

---

### ADR-028 — Operator screens live in the existing front end; the Trader verifies logins through the analysis API

**Date:** 2026-11-14
**Status:** accepted (decision); one implementation detail to verify (below)

**Decision:** The Trader's operator screens are new pages in the existing React front end, calling the
Trader's own API. The Trader does **not** hold the analysis platform's JWT signing secret. It verifies a
bearer token by calling the analysis API's `GET /auth/me` with that token and reading the user and role from
the answer.

**Rationale:** One login and one UI for the owner. `GET /auth/me` exists and, like every authenticated route
in the analysis API, re-checks user status on each request, so a suspended user's token stops working at
once. A Trader that held the signing secret could mint tokens for the analysis platform if compromised.

**Alternatives considered:** Sharing the JWT secret (rejected: coupling of compromise); a separate small
front end with its own login (rejected for the first release: more UI and a second identity to manage).

**Implications:** Every Trader request that needs authorization makes a call to the analysis API, so the
analysis API being down means the Trader's **operator surface** is unavailable, though the Trader itself
keeps running. The kill switch must therefore also be reachable without that path: the command-line tool
(`docs/05-MODULE-SPECIFICATIONS/08-KILL-SWITCH.md`) is not optional. A short-lived verification cache is a
possible optimization but is not decided. **To verify before building:** that `GET /auth/me` returns the role
needed, that the `trader` role can be added to the platform's `UserRole` without disturbing it (a change in
`aidss`, which must keep its architecture test passing), and the behavior under load.

---

### ADR-029 — The master key lives in a file secret on the host

**Date:** 2026-11-14
**Status:** accepted

**Decision:** `AIDSS_TRADER_MASTER_KEY` is stored as a file on the deployment host with strict permissions,
outside git, mounted read-only into the Trader container as a Docker secret or equivalent. The container
environment holds only the **path** (`AIDSS_TRADER_MASTER_KEY_FILE`), never the key itself. This refines the
custody question left open in ADR-014 (OQ-17).

**Rationale:** Restarts stay unattended (the Trader recovers by itself and then waits for the owner to
resume). Keeping the value out of environment variables keeps it out of `docker inspect` output and process
listings.

**Alternatives considered:** The owner enters the key at every start (strongest against host theft, but
leaves open positions unmonitored after every reboot until the owner acts); an environment variable in an
`.env` on the host (simplest, easiest to leak into backups or a repository).

**Implications:** Anyone with root on the host can read the key. The file is excluded from every backup,
and the database dump never sits beside it. Generation, permissions, rotation, and a re-entry procedure are
still to be written into the runbooks (`docs/09-SECURITY-PRIVACY/02-SECRETS-AND-KEY-ROTATION.md`).

---

### ADR-030 — The Trader image may be public during development; it becomes private before production

**Date:** 2026-11-14
**Status:** accepted (owner's explicit choice, overriding the recommendation in `docs/09-SECURITY-PRIVACY/07`)

**Decision:** While the Trader is under development, its image may be published to a public registry
repository. **Before the first live-money stage (T5-06) it must be moved to a private repository.**

**Rationale:** The owner's words: public for now; private once finished and in production.

**Alternatives considered:** Private from the start (recommended by the author; declined by the owner).

**Implications:** Anything pushed while public must be **assumed copied**: making a repository private later
does not recall copies others have pulled or cached. Therefore, while public, the image must contain **no**
secret, no configuration values, no owner numbers, and no real strategy parameters (all of which live in the
database, ADR-014, and the settings registry). Trading logic and its tests are visible to anyone. The change to
private is a release-checklist item and a T1-01 follow-up (`TASKS/PHASE-T1-FOUNDATION.md`,
`docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`).

---

### ADR-031 — Mobile alerts go to Telegram, outbound only

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The mobile channel for alerts is Telegram, used outbound only (a bot sending to the owner). It is
never a control surface. WhatsApp is not planned. This resolves the "Telegram or WhatsApp" part of ADR-016.

**Rationale:** The owner's choice. A single recipient and outbound-only messages are what a personal bot
needs.

**Alternatives considered:** WhatsApp Business API; Telegram now with WhatsApp later (both declined).

**Implications:** The Telegram bot token is a credential: stored encrypted, never logged, rotatable. Facts
about Telegram's Bot API (limits, delivery behavior, what the provider can read) were **not researched here**
and are verified in task T5-02 before building. The notifier stays behind a small interface, so another
channel can be added without touching other components.

---

### ADR-032 — The MVP ships without AI context; the candle-in endpoint (option B) follows

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The first release runs on deterministic rules only, with **no AI or Kronos context** for crypto
pairs. After the MVP, the analysis platform gains a stateless candle-in forecast endpoint (option B in
`docs/06-INTEGRATIONS/13-AIDSS-ANALYSIS-PLATFORM.md`), and the Trader's context bridge runs first in
**record-only** mode to build evidence before any veto is enabled.

**Rationale:** ADR-004 makes AI a veto, never a requirement, so nothing in the trading path needs it. Option B
is the smallest change to the analysis platform and keeps model runtimes out of the Trader.

**Alternatives considered:** Build option B within the MVP; option A (full crypto asset support); never use AI
context for crypto.

**Implications:** Tasks T3-05 and T3-06 are **deferred to post-MVP**. FR-T09 (veto) is post-MVP. The veto rules
and the evaluation method remain specified so the work can resume. There is no AI evidence for crypto pairs
until the bridge has run for a period after the MVP.

---

### ADR-033 — The `admin` role may `HALT`

**Date:** 2026-11-14
**Status:** superseded by ADR-048

**Decision:** Besides `trader`, the platform `admin` role may trigger `HALT`. `CANCEL`, `FLATTEN`, and resume
remain `trader` only.

**Rationale:** `HALT` only stops new orders, so letting more people press it fails safe.

**Alternatives considered:** `trader` only.

**Implications:** A compromised `admin` account could halt trading, which is an availability risk (not a loss
risk). Every `HALT` is audited and notified as `kill_switch_used`, so it is visible and reversible only by the
owner's resume.

---

### ADR-034 — "A day" for the daily-loss limit is local midnight WIB

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The daily-loss limit measures from midnight WIB (UTC+7). WIB has no daylight saving, so this is
a fixed offset from UTC.

**Rationale:** Matches the owner's calendar and is easy to explain.

**Alternatives considered:** UTC midnight; a rolling 24 hours.

**Implications:** The loss allowance resets at 00:00 WIB, which can give a fresh budget in the middle of a
market move. The drawdown limit is cumulative and unaffected. This says nothing about where Indodax's own daily
candle starts, which is a separate, still open question (OQ-4).

---

### ADR-035 — Order placement: maker-first at the best bid or ask, `MOC` on entries, `EXPIRE_TAKER`

**Date:** 2026-11-14
**Status:** accepted (the rules); the **numbers** (reprice wait, maximum reprices, approval expiry, `UNKNOWN`
query attempts and window) remain open under OQ-22

**Decision:** A buy `LIMIT` is placed at the **best bid** and a sell `LIMIT` at the **best ask** (maker-first).
Entries use `MOC` (maker or cancel), so an order that would cross the book is cancelled rather than filled as
a taker. Every order is sent with `selfTradePreventionMode = EXPIRE_TAKER`: if the new order would match one of
the Trader's own resting orders, the **new** order expires and the existing state is kept.

**Rationale:** Fees are asymmetric (ADR-006); resting at the touch captures the maker fee. `MOC` guarantees it.
A self-trade means the design failed to avoid one, so the most conservative response is to do nothing new.

**Alternatives considered:** One tick inside the spread; crossing the spread; `EXPIRE_MAKER` (the exchange
default, which could cancel a resting take-profit); `EXPIRE_BOTH`; plain `GTC` on entries.

**Implications:** Orders at the touch may never fill when price runs away; the reprice rule, with a bounded
count, handles that, and an entry that is cancelled or exhausted is abandoned for that signal. Stop exits stay
`MARKET` (ADR-006). `MOC` rejections will appear as cancelled entries and must be counted separately from
failures.

---

### ADR-036 — There is no automatic `FLATTEN`

**Date:** 2026-11-14
**Status:** accepted (refines ADR-010)

**Decision:** No automatic trigger may cause `FLATTEN`. Circuit breakers, the reconciler, and the watchdog may
trigger `HALT` or `CANCEL` only. `FLATTEN` is always a human decision.

**Rationale:** In a thin market, selling everything at market can itself realize large losses. The owner chose
to keep that decision manual.

**Alternatives considered:** Automatic `FLATTEN` on the drawdown breaker; on security events; on both.

**Implications:** When the owner cannot be reached, positions stay open with only the bot-side stops
(ADR-007), and the exposure limits (ADR-009) bound the size. The setting `auto_flatten_conditions` does not
exist. Test `test_unlisted_condition_cannot_flatten` now means that **no** automatic code path can request
`FLATTEN`.

---

### ADR-037 — Legal and tax considerations are the owner's; no checklist gate

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The owner states that the legal, regulatory, tax, and Indodax-terms aspects of automated crypto
trading have been considered. The release checklist does **not** gate on them. The documents continue to say
that these matters are outside the system and that it gives no legal advice.

**Rationale:** The owner's decision and responsibility.

**Alternatives considered:** A checklist item requiring the owner's statement before real money; a task to
record advice from a professional.

**Implications:** The author still **recommends** reading Indodax's terms on automated trading and
market manipulation (Indodax's STP page treats self-trades from automated systems as a concern) and
confirming the tax treatment of fills (each fill carries a tax amount). The system will not prompt for it.

---

### ADR-038 — The live read-only verification runs after the connector and the mock exist

**Date:** 2026-11-14
**Status:** accepted

**Decision:** Task T2-07 (the owner-led read-only verification against the real exchange) is done at the end of
phase T2, after the connector and mock are built, as planned.

**Rationale:** The mock exists to be corrected, the redaction and capped script are ready, and the owner is
involved once.

**Alternatives considered:** Running the public, key-less phase earlier; deferring all live contact to T5-06.

**Implications:** Until then every Indodax detail is "documented, not yet observed", and an assumption that is
wrong is discovered after the connector is written. Phase A of the plan (public endpoints, no key) can still be
run earlier at the owner's discretion.

---

### ADR-039 — A host script outside the Trader alerts on a stale heartbeat, straight to Telegram

**Date:** 2026-11-14
**Status:** accepted

**Decision:** A scheduled script on the deployment host reads the Trader's heartbeat from the database with a
**read-only** role (`trader_monitor`, `SELECT` on the heartbeat only) and sends an alert **directly to
Telegram**, without passing through the Trader. Its bot token is a root-only file on the host.

**Rationale:** The in-process watchdog dies with the process, so it cannot announce the case that matters most:
the Trader down with positions open (ADR-007).

**Alternatives considered:** An external uptime service receiving heartbeats; both.

**Implications:** **If the host itself is down, nothing alerts.** The owner accepted this gap. A second secret
(the host's Telegram token) and a third database role exist. An external service remains a possible later
addition.

---

### ADR-040 — Off-host backups are manual, to an external disk or the owner's PC

**Date:** 2026-11-14
**Status:** accepted

**Decision:** The owner copies backups of the `trading` schema off the host manually, to an external disk or
their own PC. Nothing automatic does it.

**Rationale:** The owner's choice; simplest, no third party.

**Alternatives considered:** Another host over SSH; encrypted cloud object storage.

**Implications:** The **RPO of the audit trail is the time since the owner last copied it**, and a host loss
loses everything since then. The exchange remains the source of truth for trading state (ADR-022), so state can be
rebuilt, but the audit trail, strategy history, and local annotations cannot. A backup before every release stays
mandatory. A reminder or an automatic off-host copy would be possible later additions and would need the owner's
approval.

---

### ADR-041 — Timing: price poll every 10 s, watchdog after 3 missed cycles, reconcile every 60 s, clock-skew halt at 250 ms

**Date:** 2026-11-14
**Status:** accepted. Order poll interval and the lease TTL and heartbeat stay open (OQ-6, partly decided)

**Decision:** The Exit Monitor polls prices every **10 seconds**. The watchdog raises `CRITICAL` after **three
missed poll cycles** (30 seconds at that interval). Reconciliation runs every **60 seconds**. The Trader halts
before sending a signed request when the measured clock skew exceeds **250 ms**.

**Rationale:** The owner's choices. Indodax rejects a request whose timestamp is 1 second or more ahead of its
clock (and one older than `recvWindow` behind it), so the skew limit must be far below 1 second; 250 ms leaves
headroom for network latency.

**Alternatives considered:** Slower polling (30 s, 60 s, 5 min); a more or less patient watchdog (2, 5, 10
cycles); reconciliation every 5, 15, or 60 minutes; a skew limit of 500 or 750 ms.

**Implications:** A stop is seen within about 10 seconds plus processing, and the Trader tells the owner within
about 30 seconds of a stalled monitor. Reconciliation at 60 seconds costs roughly `2P + 2` private requests per
minute for `P` pairs (history and trades per pair, plus open orders and the account), on top of order polling,
against a documented limit of 300 per minute per IP; it must be re-budgeted if the allowlist grows
(`docs/02-ARCHITECTURE/08`). A 250 ms skew limit makes any NTP drift or a slow time endpoint halt trading, so the
measurement must account for round-trip time (verified in T2-05). The unprotected window after a crash is the
lease TTL plus this watchdog time, and the lease TTL is not decided yet.

---

### ADR-042 — Order placement numbers: reprice after 5 min, at most 3 reprices, approval expires in 1 hour, `UNKNOWN` queried 5 times in 30 s

**Date:** 2026-11-14
**Status:** accepted. Completes OQ-22 (with ADR-035)

**Decision:** A resting entry or normal-exit `LIMIT` that has not filled is cancelled and repriced after **5
minutes**, at most **3** times, after which that signal is abandoned. An intent in `APPROVAL` mode expires after
**1 hour**. An order in state `UNKNOWN` is queried by `clientOrderId` **5 times over 30 seconds**; if still not
found, trading on that pair is held, a `CRITICAL` alert is raised, and only the owner confirms "not found".

**Rationale:** The owner's choices. The author recommended the first three; the owner chose the same for all of
them and the fourth with no recommendation given.

**Alternatives considered:** Reprice waits of 1 min, 15 min, 1 hour; 0 or 10 reprices; approval expiry of 15
min, 2 h, 3 h; `UNKNOWN` queried 10 times in 2 min or 20 times in 10 min.

**Implications:** A chased entry lasts at most about 20 minutes (the first attempt plus three reprices at 5
minutes each). The approval expiry is well under the 4-hour candle period, as required. **The `UNKNOWN` window is
short:** Indodax states a freshly accepted order "may not be immediately available", and that lag is not
quantified in the documentation, so a real order can still be invisible after 30 seconds. The consequence is a
held pair and a `CRITICAL` alert (a safe failure), not a duplicate order, because the create is never re-sent
(ADR-024). The visibility lag is to be observed at T5-06 and may justify lengthening the window.

---

### ADR-043 — Order polling every 10 s; lease TTL 15 s with a 5 s heartbeat

**Date:** 2026-11-14
**Status:** accepted. Completes OQ-6

**Decision:** While any order is open, the Order Manager polls `openOrders` every **10 seconds**. The
single-instance lease (ADR-027) has a **15 second TTL** renewed by a heartbeat every **5 seconds**.

**Rationale:** The owner's choices. The author recommended 10 s for order polling and gave no recommendation on
the lease, a safety number.

**Alternatives considered:** Order polling at 5 s or 30 s; lease TTL 30 s with a 10 s heartbeat, or 60 s with a
20 s heartbeat.

**Implications:** The short TTL minimizes the delay before a restarted Trader may trade (at most 15 s) and
therefore the unmonitored window after a crash. The price is **sensitivity**: three missed heartbeats
(a database stall of about 15 s) make a healthy Trader lose its lease and stop trading until it reacquires it.
That is a safe failure, but it may produce halts during brief database slowness.

---

### ADR-044 — Initial allowlist: BTCIDR and ETHIDR

**Date:** 2026-11-14
**Status:** accepted. Completes OQ-7; the pairs stay inactive until OQ-8 is answered

**Decision:** The first allowlist is `BTCIDR` and `ETHIDR`. A pair is tradable only after the liquidity filter
(minimum 24-hour quote volume and maximum spread, OQ-8) is configured and the pair passes it (ADR-005).

**Rationale:** The owner's choice. The author had recommended starting with `BTCIDR` alone for the first
`APPROVAL` period.

**Alternatives considered:** `BTCIDR` only; an owner-written list.

**Implications:** Two pairs double the observation load and the per-pair reconciliation requests (about
`2P + 2` private requests per minute, so 6 per minute with `P = 2`). Exposure limits and the per-pair
exposure cap (OQ-9) apply to each. The documentation's examples use these two pairs; their actual liquidity and
minimum order sizes were not verified here and must be checked at Indodax (OQ-8, T2-03).

---

### ADR-045 — Whether to enable an AI veto is decided later, with evidence

**Date:** 2026-11-14
**Status:** accepted. Closes OQ-25 for the MVP

**Decision:** No AI or Kronos veto is enabled in the MVP, and **whether one is ever enabled, and its
thresholds, are decided after the post-MVP evidence exists** (ADR-032): the bridge runs record-only, the
counterfactual evaluation is done, and only then the owner sets thresholds and decides.

**Rationale:** There is no AI context for crypto pairs yet, so there is nothing to set thresholds against.

**Alternatives considered:** Never enable a veto; set thresholds now.

**Implications:** The thresholds must be set **before** the evidence is read, as the evaluation method
requires; that ordering is now an explicit step of the post-MVP review. The veto settings stay unset and the
rule never fires until then.

---

### ADR-046 — Step-up authentication: a single-use grant minted after password re-entry

**Date:** 2026-11-14
**Status:** accepted (owner, 2026-11-16): the 5-minute single-use window as written

**Decision:** `FLATTEN`, promotion to `AUTO`, a limit increase, and a credential change each need a
**step-up grant** in addition to the bearer token. The Trader mints a grant only after the user re-enters their
password, which the Trader checks by calling the analysis API's existing `POST /auth/login` and requiring that
the returned token resolves (via `/auth/me`) to the same user id as the session. A grant is random, stored only
as a SHA-256 hash, bound to one user and one scope, valid for **5 minutes**, and **single use**.

**Rationale:** It needs no new infrastructure and no password handling in the Trader (the password is forwarded,
never stored or logged). A stolen idle session cannot flatten or promote without the password.

**Alternatives considered:** TOTP (needs enrolment, a new secret, and a user-model change in the analysis
platform); a typed confirmation phrase only (does not stop a stolen session).

**Implications:** The 5-minute window is adjustable. If the analysis API is down the step-up fails closed, so
`FLATTEN` from the UI is unavailable; the command-line kill tool does not depend on it (ADR-028).

---

### ADR-047 — A fresh install starts HALTED; signal exits in APPROVAL mode are not queued

**Date:** 2026-11-14
**Status:** accepted (owner, 2026-11-16): both parts, a fresh install starts HALTED and signal exits in APPROVAL mode are not queued

**Decision:** (1) When the runtime finds no trading-state row it creates one as `HALTED` ("initial state:
awaiting the owner's resume"). Trading starts only when the owner resumes with a note. (2) In `APPROVAL` mode only
*entries* wait for approval; a strategy's signal exit is sent through the Risk Engine without a card, the same
as a stop, because the owner approves entries and the protective exits that follow need no further approval
(`docs/05-MODULE-SPECIFICATIONS/07`, "Scope of Approval").

**Rationale:** Without (1) a database with no state row reads as `RUNNING`, and a fresh install would be one
limits change away from trading. For (2), a position held while an exit card expires unanswered is the
dangerous outcome.

**Alternatives considered:** Starting `RUNNING` once limits are set; queueing signal exits for approval.

**Implications:** The first thing an owner does after setting limits is resume. If the owner wants signal exits
approved too, the runtime routes them to the approval workflow instead.


---

### ADR-048 — The `admin` role holds every trader permission

**Date:** 2026-11-14
**Status:** accepted (the owner's instruction in this session). Supersedes ADR-033

**Decision:** `admin` has the same trade permissions as `trader`: approve and deny, edit strategy parameters,
change limits and the allowlist, promote and demote, `HALT`, `CANCEL`, `FLATTEN`, resume, manage the credential,
and read the audit log. `investor` and `viewer` stay read-only. Step-up authentication (ADR-046) still applies to
`FLATTEN`, promotion to `AUTO`, and loosening a limit for both roles.

**Rationale:** The owner administers the platform and wants one account to operate the Trader. There is one owner
(ADR-015), so a second role with partial rights added friction and no control.

**Alternatives considered:** Keeping `admin` to `HALT` only; a separate `trader` account.

**Implications:** Anyone given the platform `admin` role can now flatten positions and replace the exchange key, so
granting `admin` is granting control of the money. The analysis API's role management is therefore part of the
trading threat model: an `admin` account takeover is a trading takeover, and the step-up is the only extra barrier.
The password is the weakest point; a second factor is worth considering (ADR-046 alternatives).

---

### ADR-049 — Per-pair strategy parameter overrides and version tracking

**Date:** 2026-11-15
**Status:** accepted (owner, 2026-11-16): option 1, one parameter set for all pairs. The per-pair override design below is not adopted; revisit only if the owner asks

**Decision:** Keep a strategy-level parameter set (`strategy_params:<strategy_id>`) as the shared baseline, and allow optional per-pair overrides stored under `strategy_params:<strategy_id>:<pair>` in `trading.trader_setting`. When a pair has an override:
1. Its effective parameter hash is `EmaAdxStrategy(params).version_id()`, which differs from the baseline version id.
2. Under ADR-020 ("a changed strategy version starts again in `PAPER`"), a pair whose effective version changes must not inherit an `APPROVAL` or `AUTO` promotion earned under different parameters. Therefore, if the owner enables per-pair overrides, `trading.strategy` (`StrategyRow`) either keys on `(strategy_id, pair)` or requires all allowlisted pairs to pass promotion gates under the composite version map before the strategy promotes.
3. No default override values exist (OQ-11); an override is created only when the owner explicitly sets all seven `EmaAdxParams` fields for that pair, and deleting the override resets that pair to the shared baseline (and returns it to `PAPER`).

**Rationale:** `BTCIDR` and `ETHIDR` (and thinner IDR pairs added later via the allowlist) can have different volatility and trend persistence on 4H candles, so a single ADX threshold or ATR stop multiple across every pair may be too tight for one and too loose for another. However, allowing silent per-pair parameter edits while keeping a single strategy-wide `APPROVAL`/`AUTO` mode would bypass ADR-020's promotion discipline.

**Alternatives considered:**
1. **Single parameter set for all pairs (current implementation):** simplest; one version id and one promotion state per `strategy_id`, at the cost of one-size-fits-all indicator periods across pairs.
2. **Mandatory per-pair parameters with no shared baseline:** forces the owner to configure every pair separately before any pair can evaluate in `PAPER`, increasing setup friction without benefit when two pairs share parameters.
3. **Per-pair parameter overrides without resetting mode:** rejected because changing indicator periods or ATR stop multiples on a live pair without returning to `PAPER` violates ADR-020.

**Implications:** No code change is made to `EmaAdxStrategy` or `settings_store.get_strategy` until the owner chooses between Alternative 1 (keep single set for MVP) and the proposed design (per-pair override with per-pair or composite version reset to `PAPER`).


---

### ADR-050 - Dependency pinning for the Trader image (S13)

**Date:** 2026-11-15
**Status:** accepted (option 1, chosen by the owner on 2026-11-15); implemented in the repository, built into the deployed image `zed378/aidss-trader:7d03693` (2026-11-16)

**Decision:** Option 1, a lockfile with hashes. `requirements-trader.lock` is generated by `uv pip compile pyproject.toml --generate-hashes --python-version 3.12 --python-platform linux` (the command is in the file's header) and installed by `Dockerfile.trader` with `pip install --require-hashes --no-deps -r requirements-trader.lock`. The unpinned `pip install --upgrade pip` is gone, and the package itself is no longer pip-installed (building it would fetch an unpinned `setuptools`): its source is on `PYTHONPATH=/app/src`. Options considered:
1. **Lockfile with hashes** (chosen). Strongest; every update is a reviewed diff.
2. Exact `==` pins in a requirements file, no hashes. Does not stop a tampered upload of a pinned version.
3. Keep ranges, pin only the base image digest. Leaves transitive drift.

**Rationale:** The Trader holds a key that can trade; an unreviewed transitive upgrade is a supply-chain path to it.

**Evidence:** The lock lists 44 packages, and a local image built from it has the same 44 package versions as the deployed `aidss-trader:e410ab7` (`pip freeze` compared; the only difference is the `aidss` package itself), so adopting it changes no running dependency. A lock with every hash of one package altered makes the build fail (`THESE PACKAGES DO NOT MATCH THE HASHES`, exit 1). `pip check` on the new image reports no broken requirements and `python -m aidss_trader --help` runs. `test_s13_dependencies_are_pinned` (a strict `xfail`) is replaced by three tests: every locked package has hashes; the Dockerfile installs only from the lock with `--require-hashes --no-deps`; and the lock still satisfies `pyproject.toml` (a dependency added or raised there without regenerating the lock fails the suite).

**Implications:** Someone owns the update routine: regenerate the lock with the command in its header, read the diff, build, run the suite. The base image is still the floating tag `python:3.12-slim` (option 3 was not adopted, so OS-level patches arrive with each build and are not reproducible); a digest pin can be added later. The lock is Linux and Python 3.12 only. Installing only what the Trader imports (instead of all of `[project].dependencies`) is ADR-053.

---

### ADR-051 - Durable Idempotency-Key replay table

**Date:** 2026-11-15
**Status:** accepted (owner, 2026-11-16); implemented additively in migration `0008_indexes_idempotency`

**Decision:** Store each successful mutation answer in `trading.idempotency_key` (`key_hash` primary key, `body_hash`, `status_code`, `response_body`, `media_type`, `created_at`). `key_hash` is a SHA-256 over token, method, path, and key, so neither the token nor the key is stored. Entries older than 24 hours are ignored. `trader_rw` has `SELECT, INSERT, DELETE` only. If the table cannot be reached, the API falls back to the in-memory copy rather than failing the request.

**Rationale:** The in-memory cache lost every key on restart, so a client retry after a restart executed twice (a gap named in the S7 record). The approval and kill paths are idempotent by design; this closes the gap for the rest.

**Alternatives considered:** Keep memory only (documented gap); use Redis (new service for one table); fail the request when the table is unreachable (stricter, but turns a database blip into refused HALT calls).

**Implications:** `response_body` can contain whatever the API returns; credential responses never include secrets (S1), and the body is still operator-visible data. Opportunistic pruning (`_Replays._prune_expired`, added in Task H) deletes rows older than 24 hours inside its own transaction after each `put()`, using `DELETE` already granted to `trader_rw` in migration `0008`, so a pruning failure never fails or rolls back the API request. Not verified on real PostgreSQL by this change.

---

### ADR-052 - Frozen price-feed detection (R5)

**Date:** 2026-11-15
**Status:** proposed; **deferred by the owner on 2026-11-17** until a paper run has produced price data (no option and no threshold chosen; nothing is implemented)

**Decision:** Not yet taken. A feed that returns a fresh timestamp with an unchanged price passes the freshness check. Options:
1. **Identical price for N consecutive cycles** on pairs the owner marks liquid; N is the owner's number.
2. **Compare the ticker against the latest closed candle** and halt when they diverge beyond an owner-set tolerance.
3. **Both**, halting on either.

**Rationale:** Acting on a frozen price can place orders at a level the market has left.

**Risks:** Option 1 false-positives on thin pairs and quiet hours (a real price can repeat), which would HALT trading for no cause; option 2 false-positives around candle boundaries and gaps. Both thresholds are owner numbers (limits that gate loss); none is chosen here.

**Implications:** No behavior changes until the owner picks an option and supplies the values through `TASKS/BACKLOG.md`.

---

### ADR-053 - The Trader image installs only the Trader's own dependencies

**Date:** 2026-11-15
**Status:** accepted (the owner asked for it on 2026-11-15, after it was listed as a separate decision in ADR-050); implemented in the repository, built into the deployed image `zed378/aidss-trader:7d03693` (2026-11-16)

**Decision:** `requirements-trader.in` lists the Trader's direct dependencies (fastapi, uvicorn, pydantic, pydantic-settings, SQLAlchemy, alembic, psycopg[binary], cryptography, httpx), with the same lower bounds as `pyproject.toml`. `requirements-trader.lock` is compiled from that file instead of from all of `[project].dependencies`. `uvicorn` is the plain package, not `uvicorn[standard]`.

**Rationale:** `src/aidss_trader` and `alembic_trader` import none of pandas, numpy, curl_cffi, bcrypt, PyJWT, croniter, pgvector or email-validator, yet the image carried them (and uvloop, httptools, websockets, watchfiles, PyYAML through the `[standard]` extra). Every package in an image that holds a trading key is surface that has to be patched and reviewed.

**Evidence:** The lock goes from 44 to 28 packages; all 28 that remain keep exactly the versions already locked, and none was added. A local image built from it is 291 MB, against 593 MB for the image built from the 44-package lock. In that image `pip check` is clean and all 73 `aidss_trader` modules import. Against a throwaway PostgreSQL 16, migrations `0001..0008` ran as `trader_owner` (30 tables in `trading`), and the Trader, run as `trader_rw`, started `HALTED`, reported healthy, answered `/trader/v1/status` with `401` and the security headers, and ran cycles with no traceback. Three tests keep it honest: the lock satisfies every direct requirement; `requirements-trader.in` uses the same bounds as `pyproject.toml`; and a new third-party import anywhere in the Trader fails the suite by name (checked with a probe `import pandas`).

**Risks and limits:** The event loop is plain asyncio instead of uvloop (uvicorn picks uvloop only when installed); the Trader's traffic is a few operator requests and the exchange client, so this is not expected to matter, but it is a runtime difference from the image running now. The smoke test did not talk to a real analysis API or exchange. A dependency the Trader later needs must be added to `requirements-trader.in` and the lock regenerated; the import-guard test says which one.

**Implications:** `pyproject.toml` still describes the analysis platform and is unchanged. The analysis image is not affected.

---

### ADR-054 — External Audit Log Head-Hash Anchoring (`T1-05`)

- **Date:** 2026-11-15
- **Status:** accepted (owner, 2026-11-16): option 1, hourly cron writing the anchor file outside the database volume (suggested path `/var/lib/aidss-anchor/anchor.jsonl`); installing the cron on the host is part of the host hardening steps and not yet done
- **Deciders:** Engineering; owner chose option 1 and an hourly schedule on 2026-11-16
- **Context:** `docs/09-SECURITY-PRIVACY/04-AUDIT-LOGGING.md` requires recording the audit chain's head hash outside the database so a database owner cannot silently truncate or rewrite `trading.audit_log`, and states the external target should be recorded as an ADR. `chain_head(session)` existed, but no external anchor writer, verifier, or CLI entry point had been built.
- **Options:**
  1. Append-only JSONL file outside the database (`record_head_anchor` / `verify_head_anchor`) driven by `python -m aidss_trader audit-anchor --out <path>` (plus `--verify-only`), with idempotent appends when `(seq, head_hash)` has not advanced and `AuditChainBroken` failure on DB truncation or hash mismatch.
  2. Direct remote syslog / external object-storage push from the Trader process on every audit write.
- **Decision:** Implement Option 1 in `src/aidss_trader/audit/log.py` and `src/aidss_trader/__main__.py` with zero new dependencies. Host-level scheduling (e.g., cron / systemd timer writing to an off-DB host file or synced volume) and `--out` path choice are left for the owner to confirm on the VM.
- **Consequences:**
  - `verify_chain` + external anchor comparison now detects whole-table DB rewrites or truncations across runs.
  - Until the owner schedules `audit-anchor --out <path>` on the deployment host, the mechanism is verified only in hermetic tests.

### ADR-055 — Starter profiles for the owner numbers (a draft, not a default)

- **Date:** 2026-11-16
- **Status:** proposed for the Rp 1,000,000 profile; **accepted by the owner on 2026-11-18 for the Rp 50,000 profile** (multiple-choice answers: profile, limits as written, paper costs kept with tax and clearing flagged unverified under OQ-5). Accepted means the owner approved the values; it is not yet loaded into the instance, which only the owner does with `import_owner_profile.py`
- **Context:** `08-OWNER-NUMBERS-WORKSHEET` lists every number that limits loss and leaves each blank on purpose; the Trader has no default for them. Entering about forty values one screen at a time is slow, and the owner's account may be as small as Rp 50,000, where the exchange minimum order changes what a sensible risk per trade is.
- **Decision:** Keep the runtime unchanged (no default is compiled in; an unset field still disables the strategy). Add two **editable profile files** that the owner can adjust and a read-only checker: `deploy/trader/owner-defaults.rp50000.json`, `owner-defaults.rp1000000.json`, `deploy/trader/check_owner_defaults.py`, documented in `docs/01-PRODUCT-REQUIREMENTS/09-OWNER-NUMBERS-STARTER-PROFILE.md`. The profiles are conservative, 4H, BTCIDR and ETHIDR. Costs are pessimistic placeholders and are not observed values (OQ-5 stays open); the minimum order and stop distance are stated assumptions (`basis`).
- **Options:** (1) compile defaults into the Trader (rejected: a forgotten setting would become a permissive one, FR-T11); (2) a profile file plus checker, applied by the owner (chosen); (3) leave all blank (rejected by the owner's request).
- **Consequences:** Nothing trades differently until the owner enters values. The profiles must be kept in step with the limit names and ranges (a test, `tests/trader/test_owner_defaults.py`, fails on drift). Loading a profile into an instance is a separate step done by the owner: `deploy/trader/import_owner_profile.py` (added 2026-11-17) signs in as the owner and writes through the Trader's own `/trader/v1` routes, dry run by default, applying only a file whose status the owner has changed to `accepted`, and never resuming, promoting, changing a mode or touching credentials.


### ADR-056 — A venue-neutral exchange port; Indodax is the first adapter; futures are not designed yet

- **Date:** 2026-11-18
- **Status:** accepted (owner, 2026-11-18, multiple-choice: a venue-neutral layer with Indodax as the first adapter, and only a gap left for futures, no futures code or data model)
- **Context:** Every consumer (order manager, reconciler, kill switch, loop, credential check, operator API) named `IndodaxClient` directly, so a second exchange would have meant editing all of them. The owner expects to add Binance futures later. That venue is not a variation on Indodax spot: its core objects are positions, not balances, and it adds leverage, short exposure, margin, liquidation and funding, none of which the Risk Engine, the ledger or the reconciler model today (ADR-002 is spot only).
- **Decision:** Add `connector/port.py`, a `Protocol` named `ExchangeClient` listing the spot operations the Trader actually uses, with no withdrawal, deposit or transfer method (ADR-013). All consumers depend on it. `IndodaxClient` is unchanged and satisfies it. `runtime/assembly.py` holds the one table of venues (`VENUES`) selected by the new setting `AIDSS_TRADER_EXCHANGE` (default `indodax`); an unknown name is refused, never defaulted. No Binance code, no futures fields in the schema, no futures limits.
- **Options:** (1) leave `IndodaxClient` everywhere (rejected: every new venue edits every consumer); (2) a port plus a venue table (chosen); (3) design futures data now (rejected by the owner: it touches money paths with no decision on leverage, shorting or margin limits).
- **Consequences:** Behaviour is unchanged; the Trader still starts without an exchange when the URLs are unset. A test fails if any module other than the client, the package export and the assembly names `IndodaxClient`, if the port gains a withdrawal-like method, or if the Indodax signatures drift from the port. A second **spot** venue is one adapter plus one table entry. A derivatives venue needs its own port (positions, margin, funding), its own risk rules and its own ADR, written before the code, and the owner's decision on whether leverage and shorting are allowed at all.
- **Not decided:** whether Binance futures will be added, with what leverage cap, whether shorts are allowed, and whether the owner may use that venue from Indonesia (the owner's responsibility to confirm before any key is created).

### ADR-057 — IDX data: fundamentals from a licensed API (EODHD); the IDX site is not fetched around its bot protection

- **Date:** 2026-11-18
- **Status:** accepted (owner, 2026-11-18, multiple-choice and typed answers: official source with an API; EODHD for fundamentals; the daily trading-summary job left running as it is)
- **Context:** The IDX adapter (`market_idx.py`) is refused with `403` by the site's bot management from the VM's address. Jobs `market.trading_summary` died on 2026-11-09, 10, 16 and 17, `fundamentals.refresh` on 2026-11-09, 10 and 18, `issuers.sync` on 2026-11-18 (all `[idx] refused (403) by bot protection`). The cause is not proven (a datacenter address treated differently, or a stale browser profile). A browser-profile change was tried on the worker and reverted the same day at the owner's request. An outbound proxy setting (`AIDSS_IDX_PROXY_URL`) exists in code, unset and undeployed. Lightpanda (a headless browser) was installed in a container and tested on neutral pages only (`example.com`, an inline script page): it renders JavaScript. It was not run against `idx.co.id`.
- **Decision:** Fundamentals for IDX tickers come from a licensed, documented API: the new `eodhd` adapter, used through the composite provider (`AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd`, prices from Yahoo). The key is stored on the host by `deploy/host/set-eodhd-key.sh` (typed at a prompt, never in chat or argv). Until a key exists the provider stays `idx`, because `eodhd` without a key refuses to construct. The daily trading summary with foreign flow has no public official API that was found; the owner chose to leave its job running, so it keeps failing with `403` until a licensed source exists.
- **Not adopted:** rotating browser profiles, a deployed proxy, and a headless browser (Lightpanda) used to get past the IDX bot protection. IDX publishes a data licence agreement, and passing a protection the site applies to this address is not a basis the project can rely on or defend. This ADR is not an authorisation to do so; the agent working on this repository declined to run it, and an ADR does not substitute for permission from IDX.
- **Revisit when:** IDX (or a vendor under an IDX licence) gives written permission or a licence that covers automated access, or a vendor covers foreign flow. That needs a new ADR that cites the permission.
- **Consequences:** Fundamentals cost money and depend on a plan that includes the vendor's Fundamentals API (one request costs 10 of its daily calls; `AIDSS_FUNDAMENTALS_DAILY_QUOTA` must be set from the plan; the default 25 is Alpha Vantage's). The adapter was written from the vendor's documentation and has not been run against a live key, so coverage and field names for `.JK` are unverified until `tests/test_eodhd_live.py` runs. Foreign-flow features stay unavailable and the failing job stays visible rather than hidden.
