# AI Investment Decision Support Platform

Implementation of `Dokumen_Perencanaan_AI_Investment_Decision_Support.md` — **all nine
phases** of the roadmap in Section 15.

> **Decision support, not a trading bot.** This system reads market data and produces
> analysis. It has no execution engine, no broker adapter, no order endpoint, and no
> database table that could hold one. That absence is an architectural hard constraint
> (Sections 1, 2.3, 3, 4, 8, 10), not a feature scheduled for later — and it is enforced
> by [tests/test_architecture_constraints.py](tests/test_architecture_constraints.py),
> so the build fails if anyone introduces one.

---

## What is built

| Phase | Scope | Status |
|---|---|---|
| **1 — Core Platform** | Plugin architecture (4 provider interfaces), configuration, JWT auth, RBAC, full database schema (Section 8.2) + migration | Done |
| **2 — Market Data** | Market Data Collector, cleaning/validation, normalisation, idempotent upsert, 2 market-data adapters, ingestion run tracking | Done |
| **3 — Indicator Engine** | 13 deterministic indicators + market structure, support/resistance, breakout detection, Feature Engineering | Done |
| **4 — AI Analysis** | LLM Gateway (routing, retry, rate limiting, circuit breaking, fallback, cost tracking), Prompt Manager with 12 versioned templates, Output Validator, Context Builder, Memory Manager, and five agents | Done |
| **5 — Recommendation Engine** | The complete Section 5.4 structure, deterministic confidence calibration, measured price levels, and the rules that make an invalid recommendation unstorable | Done |
| **6 — Portfolio Intelligence** | Concentration, diversification, and correlation metrics; historical risk (drawdown, volatility, VaR, expected shortfall); read-only what-if simulation; Portfolio and Risk analyzers | Done |
| **7 — Knowledge Base & RAG** | Boundary-aware chunking, embedding and retrieval, plus the scheduled per-issuer news pipeline of Section 6.3 with cron presets, batched sentiment scoring, and idempotent ingestion | Done |
| **8 — Reporting & Dashboard** | Asset and portfolio reports in Markdown and JSON, a notification service whose event vocabulary cannot express an instruction, and an operations overview for the admin dashboard | Done |
| **9 — Production & Optimization** | Prometheus metrics, JSON logging with request correlation and credential redaction, security headers, per-client rate limiting, and daily AI budget governance | Done |

Every table Phases 1–9 needed was already defined in the Phase 1 migration, so Phases 5
through 9 required **no schema change at all** beyond one small table for the Memory
Manager — which was the point of building the whole of Section 8.2 up front.

---

## Quick start

Requires Python 3.11+ and Docker (for PostgreSQL only).

```bash
# 1. Environment
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env

# 2. Database (PostgreSQL 16 + pgvector)
docker compose up -d postgres

# 3. Schema
export AIDSS_DATABASE_URL="postgresql+psycopg://aidss:aidss@localhost:5432/aidss"
python -m alembic upgrade head

# 4. Run
python -m uvicorn aidss.main:app --reload      # http://127.0.0.1:8000/docs
python -m aidss.jobs                           # worker + scheduler, separate process
```

The worker is a **separate process on purpose**. Without it running, scheduled news
ingestion never fires and queued analyses sit in the queue — everything else still works,
because nothing on the request path depends on it.

Or the whole stack at once: `docker compose up --build`.

### Try it

```bash
BASE=http://127.0.0.1:8000
curl -X POST $BASE/auth/register -H 'Content-Type: application/json' \
     -d '{"email":"me@example.com","password":"correct-horse-battery"}'
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"me@example.com","password":"correct-horse-battery"}' | jq -r .access_token)

# Fetch prices, compute and store every indicator, derive features
curl -X POST "$BASE/assets/BBCA/ingest" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"timeframe":"1d","days":400}'

# Read the analysis-ready snapshot
curl "$BASE/assets/BBCA/indicators" -H "Authorization: Bearer $TOKEN"

# Run the multi-agent analysis and produce a recommendation
curl -X POST "$BASE/assets/BBCA/analysis" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"timeframe":"1d"}'

# Re-read the stored results without spending anything
curl "$BASE/assets/BBCA/analysis" -H "Authorization: Bearer $TOKEN"
curl "$BASE/assets/BBCA/recommendation" -H "Authorization: Bearer $TOKEN"
```

## Market data

| Provider | Cost | Key | IDX coverage | Status |
|---|---|---|---|---|
| **`yahoo`** (default) | Free | None | Yes, via `.JK` | **Unofficial** — see below |
| `finnhub` | Free tier → paid | Required | Limited | Official, documented |
| `fixture` | Free | None | Synthetic | Deterministic, for tests and offline work |

`yahoo` is the default because it is the only free, key-less source with usable IDX
coverage. That choice is a deliberate trade-off, and it is worth stating what was
traded:

Section 6.1 of the planning document marks this source grey. The chart endpoint is
undocumented, Yahoo's terms restrict automated commercial use, and nothing about it is
guaranteed — it can change shape or start refusing requests without notice. Nothing
here is a source of record; IDX itself is.

What that means in the code, rather than in a warning:

- The parser **validates the response shape** instead of trusting it, so a schema change
  reports itself (`unexpected response shape`) rather than surfacing as a `KeyError`
  three layers up.
- A 429 is mapped to **retryable** and a 403 to **not retryable**, so the collector backs
  off from rate limiting but does not hammer an endpoint that has changed its rules.
- **Null bars are dropped, not zero-filled.** Yahoo emits nulls for halted sessions; a
  zero-filled bar would reach the Indicator Engine and drag every average through it.
- `supports_realtime()` returns **False**. The public endpoint is delayed, and claiming
  otherwise would mislead every caller that checks.
- Replacing it with an official or licensed IDX feed is a change to
  `AIDSS_MARKET_DATA_PROVIDER` alone.

Symbol mapping is automatic: IDX tickers gain a `.JK` suffix (`BBCA` → `BBCA.JK`), and a
ticker that already carries a suffix is passed through untouched, so non-IDX assets can
be registered with their explicit Yahoo symbol.

The adapter's unit tests run entirely against a mocked transport. A separate opt-in
suite checks the live endpoint, because "does the unofficial endpoint still behave as we
expect?" is a real question that deserves a real answer:

```bash
pytest -m network        # hits the live endpoints; deselected by default
```

### Fundamentals come from somewhere else

Yahoo's `quoteSummary` endpoint answers **401** now — the chart endpoint used for prices is
still open, the fundamentals one is not. Four candidates were probed rather than read
about, and the results decided the design:

| Source | Result |
|---|---|
| **Yahoo `quoteSummary`** | 401. An authentication requirement the provider added; not worked around. |
| **Financial Modeling Prep** | Its `demo` key no longer authenticates at all, so no response shape could be verified before writing a parser against it. |
| **Alpha Vantage** | Answers, documented, free keys — and, tested against a real key, publishes **nothing for IDX**. `BBCA.JKT`, `BBCA.JK`, `BBRI.JKT` all return `{}`. Right for US equities, useless for this market. |
| **IDX's own statistics API** | Answers, with real Indonesian fundamentals — behind Cloudflare. This is the one, and the choice is discussed below rather than glossed. |

So the working configuration draws each half from whichever provider can actually supply
it:

```bash
AIDSS_MARKET_DATA_PROVIDER=composite
AIDSS_COMPOSITE_PRICE_PROVIDER=yahoo   # free, no key, real IDX price coverage
AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=idx
```

The composite delegates and holds no parsing of its own, so it cannot develop opinions
that differ from the adapter behind it — and a stored metric is attributed to the half
that answered, because `composite` names a wrapper and answers nobody's question about
where a figure came from.

#### The IDX adapter impersonates a browser, deliberately

The endpoint refuses an ordinary HTTP client; `curl_cffi` presents a browser's TLS
fingerprint so the request is accepted. That was the project owner's decision, taken with
the alternatives above on the table, and it is worth being precise about what it does and
does not involve. There is **no account, no credential, and no paywall**: IDX publishes
these figures for the investing public, free and without a login, so what is got past is
bot management rather than access control. What it does **not** clear is IDX's terms,
which prohibit redistributing this data to third parties commercially — sound for personal
research, and a question to revisit before wider use (Section 13).

Practically: it can break without notice, so the response shape is verified rather than
trusted; a 403 reports *"the bot protection no longer accepts this client"* rather than as
a generic client error, because that is the likeliest single cause and sending someone to
look elsewhere would waste the hour; and requests are paced, since the endpoint
rate-limits without publishing a limit.

Two properties of the payload matter more than everything else in the adapter, because
both are **silent hundred- or billion-fold errors** rather than parse failures, and
neither is documented anywhere:

- **Money is in billions of rupiah.** BBCA's assets arrive as `1538501.81`, meaning
  Rp 1,538 trillion. Stored raw next to another provider's absolute figures, the two are a
  billion apart in one column.
- **`roa` and `roe` are percentages**, where every other provider here reports fractions.
  IDX says `20.66`; Alpha Vantage says `0.345` for the same concept.

Both were established by comparing issuers across three orders of magnitude — Adaro's
Rp 165 trillion, a micro-cap's Rp 4 billion — against known figures. Every conversion is
individually justified in the code, a live test pins the plausibility ranges, and a
recorded-payload test checks that liabilities over equity still reproduces the reported
ratio after scaling, which is an arithmetic identity the conversions cannot satisfy by
accident.

Two fields are **deliberately not stored**. `profitPeriod` is profit including minority
interests where `profitAttrOwner` excludes them, and two near-identical names invite
whichever one a reader happens to pick. `npm` is not the margin the rest of the system
means by `profit_margin` — IDX reports 74.1% for BBCA while `profitAttrOwner / sales` from
the very same row is 56.3%, so it is derived from a different denominator. Both inputs are
stored, so a consistent margin can be derived where it is wanted.

Reported periods get their own treatment. IDX's `fsDate` is not what it sounds like: for
fiscal 2024 it returns a period end, for fiscal 2025 a *filing* date. Keying on it would
make every refetch look like a new period rather than a revision of the same one, so the
stored period is the **fiscal year end** and `period_type` says how much of that year the
figures cover. That needed a fourth basis, `ytd`, because a statement filed in October
carries nine months of revenue: calling it annual overstates by a third, quarterly
understates threefold, and `ttm` is a different window entirely.

#### Alpha Vantage is still there, for US equities

Two things shape that adapter more than its happy path does. It returns **HTTP 200 for
every failure** — bad symbol, exhausted quota, premium-only endpoint — so the body is
inspected before the status code is believed, and the three error keys map onto
retryable/permanent separately (a quota resets; a wrong key does not). And it writes
missing numbers as the **string `"None"`**, which `Decimal` refuses, so one absent field
must not take out the rest of the payload. Analyst targets and rating counts are not
stored: they are other firms' recommendations, and filing them as fundamentals would let a
third party's conclusion enter the evidence base and be cited back as data.

Its free tier allows **25 requests a day**, which is a scheduling problem rather than an
adapter one — see the quota section below.

### Retrieval works without an embedding model

Many self-hosted gateways front chat-only backends and answer `/embeddings` with 404 for
every model they advertise. Naming a chat model does not help; it spends a failed round
trip per batch and can trip the gateway's own rate limiter. So say it up front:

```bash
AIDSS_AI_EMBEDDING_MODEL=       # empty: lexical-only retrieval
```

Text is still chunked, stored, and retrieved — by BM25 alone. **Exact-token search is
unaffected**, and a ticker, a metric name, or a ratio is most of what this domain asks
for. What is lost is paraphrase matching, where a passage answers the question while
sharing none of its words.

This was found by running against a real gateway, and it was worse than a missing feature
before it was fixed: the embedding call had no error handling, so a 404 propagated out of
`index_news` and **took the articles with it**. Now an outage is reported on the index
report and the text survives without its vectors, which is what the retrieval side already
assumed. Verified against both configurations — a chat model that 404s, and no model
configured at all — with all four test queries returning the right passage on `lexical`
alone.

The AI layer defaults to `AIDSS_AI_PROVIDER=fixture` — a deterministic provider, so the
pipeline runs with no key, no network, and no cost. Point
`AIDSS_AI_PROVIDER=openai_compatible` at any OpenAI-compatible endpoint for real
reasoning.

---

## Tests

```bash
python -m pytest              # 846 hermetic tests, SQLite only, no network
python -m ruff check .
```

Two groups are deselected by default, for different reasons — one needs a database, the
other needs a third party to be up. Neither should make `pytest` fail on a laptop with
neither available, and neither is optional when it matters:

```bash
python -m pytest -m postgres  # 11 tests; needs `docker compose up -d postgres`
python -m pytest -m network   # 17 tests; hits Yahoo, IDX, and Alpha Vantage for real
```

The network group earns its keep here more than it usually would: two of the three sources
are undocumented, so "has the contract changed?" is a question only a live call answers.
The IDX tests in particular distinguish *IDX is down* (skip), *the bot protection
tightened* (fail, loudly), and *the units changed* (fail, with the implausible number in
the message).

The PostgreSQL group exists because of a bug the hermetic suite could not have caught. The
embedding columns are declared `vector(1536)`; PostgreSQL enforces that width and SQLite
stores JSON and accepts anything. Twenty-five RAG tests passed green while every production
insert failed. So that group tests only what the dialects disagree about: type and
constraint enforcement, storage format (enum *values* read back through raw SQL, JSONB,
`Decimal` precision, UTC round-trips), and the two concurrency primitives SQLite has no
equivalent for — `SELECT … FOR UPDATE SKIP LOCKED` under 8 threads competing for 40 jobs,
and leader election under 10 threads racing for one lease. It runs against a throwaway
schema and drops it afterwards, so it will not touch a development database.

The suite is organised around the risks the plan itself identifies:

| File | What it protects |
|---|---|
| [test_indicators_reference.py](tests/test_indicators_reference.py) | Every indicator is checked against an independent naive implementation in [tests/reference.py](tests/reference.py). The production code is vectorised on pandas; the reference is a plain loop written from the textbook definition. Two implementations sharing no machinery are unlikely to be wrong the same way. Section 15 names "a formula error slips through for lack of adequate tests" as Phase 3's risk. |
| [test_indicators_properties.py](tests/test_indicators_properties.py) | Analytic facts that hold regardless of implementation: RSI of a rising series is 100, Bollinger bands collapse onto a flat mean, breakout windows exclude the current bar, Ichimoku spans are displaced. Agreement proves two things agree; these prove they agree on the *right* answer. |
| [test_architecture_constraints.py](tests/test_architecture_constraints.py) | The no-execution constraint, as an executable check rather than a paragraph: no order/broker tables, no execution endpoints, no `place_order`-style identifiers, no broker plugin kind, no `broker_sync` value in the holdings enum, no AI import inside the indicator package, no agent schema that accepts unknown fields, and no action-taking method on the AI provider interface. It also checks the *inventory* — that every Section 10 endpoint and every Section 5.2 agent exists — which is how three missing endpoints were found after the nine phases were otherwise complete. |
| [test_prompts.py](tests/test_prompts.py) | The execution-language guard, in both directions: eleven phrasings that must be rejected, and ten pieces of ordinary analytical vocabulary ("buying pressure", "a bullish crossover", "tekanan beli") that must not be. A guard with false positives is one analysts route around. Plus schema validation, fence stripping, and prompt versioning. |
| [test_llm_gateway.py](tests/test_llm_gateway.py) | Retry only on transient failures, exponential backoff with jitter, sliding-window rate limits, circuit opening and half-open trials, fallback ordering, privacy routing, per-agent cost attribution, and the budget ceiling. Time is faked, so a 30-second reset window is tested in microseconds. |
| [test_agents.py](tests/test_agents.py) | Agents decline to run rather than narrate absent data; one broken agent does not fail the run; skipped and failed stay distinct; a corrective retry tells the model what was wrong; stated preferences outrank inferred ones. |
| [test_recommendation_calibration.py](tests/test_recommendation_calibration.py) | That two analyzer sets differing only in the number the model reported calibrate identically — the direct test of Section 5.4's "not an arbitrary number from the LLM". Plus: a lone source scores half agreement, not full; a silent source is not counted as a neutral third opinion; zero conflicting factors scores zero balance; the stop is labelled a suggestion and is never negative. |
| [test_recommendation_engine.py](tests/test_recommendation_engine.py) | Every Section 5.4 rule, in both directions: what must be rejected, and what must be allowed through. A strong label on thin evidence is refused and retried with a correction naming the fix; a persistently invalid recommendation is reported as failed rather than stored. |
| [test_portfolio_metrics.py](tests/test_portfolio_metrics.py) | Concentration and risk arithmetic against analytic cases: n equal weights give an HHI of 1/n, a monotonic rise has no drawdown, two offsetting holdings are calmer than either alone, an unpriced position is flagged rather than silently valued, and a simulation never mutates its input. |
| [test_news_ingestion.py](tests/test_news_ingestion.py) | The idempotency rules that make a retry safe: a failed run does not advance the window, tracking parameters do not create a duplicate, repeated failure flags rather than disables, and a sentiment outage does not lose the articles. Plus the cron guardrail — measured from actual firings, because `*/1` and `0-59` fire identically and look nothing alike. |
| [test_rag.py](tests/test_rag.py) | Chunk boundaries land on paragraphs and sentences, re-indexing replaces rather than appends, news retrieval is filtered by ticker and recency before it is ranked, and vectors from a different embedding model are skipped rather than compared. |
| [test_collector.py](tests/test_collector.py) | Bad bars never reach storage, provider quirks are normalised away, and re-running the same fetch changes nothing. |
| [test_market_yahoo.py](tests/test_market_yahoo.py) | The unofficial endpoint's failure modes, against a mocked transport: null bars dropped rather than zero-filled, 429 retryable and 403 not, an HTML error page reported clearly, and a changed response shape naming itself. Depending on an undocumented source means its breakage paths deserve more test coverage than its happy path. |
| [test_market_alphavantage.py](tests/test_market_alphavantage.py) | Mostly the ways this API lies. It answers **HTTP 200 for every failure**, so a quota note, a demo-key refusal, and an invalid symbol are each checked for the right retryable/permanent verdict — misclassifying the daily limit as permanent would silently stop fundamentals collection for good. Plus: the string `"None"` is absence rather than a parse error, a negative growth figure keeps its sign, intraday stamps are converted from the exchange-local zone the response names, and analyst targets are proven *absent* from what gets stored. The OVERVIEW payload is a real recorded response — testing against invented JSON would test the invention. |
| [test_market_idx.py](tests/test_market_idx.py) | Mostly units, because units are where this provider is dangerous: nothing in the payload says money is in billions of rupiah or that `roe` is a percentage, and a mistake either way is silent. Tested at both ends of the scale — a bank's Rp 1,538 trillion and a micro-cap's Rp 4 billion — plus an arithmetic identity the conversions cannot satisfy by accident (liabilities ÷ equity must still reproduce the reported ratio). Also: `search` is a substring filter, so querying BBCA returns BBCAP too and the ticker is matched exactly; a Cloudflare challenge page is an HTML 200, so the body is the only signal there is. |
| [test_quota.py](tests/test_quota.py) | Every ambiguous case resolves towards spending less, because over-counting collects a little less while under-counting ends in the provider refusing requests — which reads downstream as an outage and triggers retries that spend tomorrow's allowance too. Plus the distinction the whole thing rests on: a job deferred until midnight is **not** charged a retry, or three quiet days would dead-letter a job that had never once been attempted. And a reservation committed on its own session survives the caller's rollback, because the HTTP request it authorised cannot be rolled back with it. |
| [test_market_composite.py](tests/test_market_composite.py) | That delegation is total and provenance survives it: prices reach only the price half, fundamentals only the other, and a metric collected through the composite is attributed to the adapter that answered rather than to the wrapper. A composite wrapping a composite is refused at construction *and* at configuration. It also pins the **shared metric vocabulary** — if one adapter renames `pe_ratio`, rows from the two providers stop being comparable while still looking like they are. |
| [test_plugins.py](tests/test_plugins.py) | The registry actually enforces the plugin contract, and provider choice really is driven by configuration alone (FR-07). |
| [test_jobs.py](tests/test_jobs.py) | Mostly failure paths, because a queue's happy path is the easy part: a permanent error dead-letters without retrying, an abandoned job is reclaimed while a merely-slow one is not, a handler that corrupts its session still has its failure recorded, one bad job does not poison the next, and ticking the scheduler twice enqueues once. Plus leader election — two schedulers, one leader; a follower takes over when the leader stops renewing; an expired lease reports as `expired` rather than as a holder. |
| [test_retrieval_quality.py](tests/test_retrieval_quality.py) | Relevance, not plumbing: the right passage ranks first, a `BBCA` query does not return `BBRI`, `EV/EBITDA` survives tokenisation, padding a document does not raise its score, and IDF never goes negative (the textbook formula does, which would make a matching document score worse than a non-matching one). |
| [test_observability.py](tests/test_observability.py) | That a counter cannot decrease, that the `+Inf` bucket equals the total count (Prometheus rejects an exposition where it does not), that metrics are labelled by route template so a ticker cannot mint a time series, that credentials never reach a log line, and that `/health` and `/metrics` stay reachable while a client is throttled. |
| [test_reporting.py](tests/test_reporting.py) | Counter-evidence appears with equal prominence, what was *not* covered is named, opening a report runs no agents and returns identical text twice, and no notification event can express an instruction. |
| [test_security.py](tests/test_security.py), [test_api.py](tests/test_api.py), [test_api_analysis.py](tests/test_api_analysis.py) | Password policy, token forgery, role boundaries, per-user data ownership, and the full HTTP flow including analysis. |
| [test_postgres_integration.py](tests/test_postgres_integration.py) *(`-m postgres`)* | Only what SQLite cannot show. A wrong-width embedding is rejected by the database; enums are stored as their values, checked through raw SQL rather than through the ORM that would map them back either way; `Decimal` keeps eight decimal places; CHECK and unique constraints hold. And the concurrency: 8 threads over 40 jobs claim each exactly once, 10 racing schedulers produce exactly one leader. The contention assertions were themselves checked — the same pattern run against a naive claim produced 127 double-assignments, so those tests fail when they should. |

---

## The dashboard

Vite + React + TypeScript in [frontend/](frontend/), served by nginx, talking to
the API on the same origin.

```bash
docker compose up -d              # everything, dashboard on :5173

# or, for development
uvicorn aidss.main:app --port 8000
cd frontend && npm install && npm run dev
```

**There is no default account.** Register from the sign-in page; a shipped default
credential is a hole, not a convenience. New accounts get the `investor` role, which covers
everything below — the admin endpoints are a later phase.

### Types are generated, not written

`frontend/src/api/schema.d.ts` comes from the API's own OpenAPI document via
`npm run api:types`, and is committed. That is the coupling that matters: a renamed field
in FastAPI becomes a TypeScript compile error rather than `undefined` on a screen months
later. It already paid for itself twice while this was being built — once when the analysis
endpoint turned out to take its timeframe in the request *body* rather than the query
string, and once on a timeframe typed as `string` where the API accepts an enum.

### Presentation decisions that are product decisions

The recommendation view is where this is a decision-support tool rather than a signal feed,
and three choices carry that:

- **Conflicting factors sit beside supporting ones, at equal weight.** Section 5.4 requires
  counter-evidence to be shown; putting it in a collapsed section under the case *for*
  would satisfy the letter of that and defeat the point.
- **The stance is a label, not a position on a scale.** No green-to-red gradient, because
  `watchlist` is not a weak buy and a gradient invites reading it as one.
- **The model's own confidence is shown struck through, beside the calibrated figure.**
  Hiding it would make the distinction invisible; showing it plainly would suggest it
  counted. It is precisely the number that does not.

Elsewhere the same principle: a skipped agent is shown *with its reason*, because it is the
direct cause of a lower confidence score and hiding it makes the score look arbitrary. A
neutral stance with no target price says why there isn't one. Year-to-date fundamentals
carry a note — but only when a `ytd` row is actually present, so the caveat stays meaningful
instead of becoming boilerplate the eye skips.

The disclaimer is in the footer of every page rather than behind a dialog. A modal accepted
once six months ago is not present on output, which is what Section 13 asks for.

### Bilingual, and that includes the numbers

Indonesian by default, English on a switch. The locale changes number and date formatting
along with the words, because it has to: in Indonesian the dot is a thousands separator, so
`1.234,56` and `1,234.56` are the same string read as two different numbers. Indonesian is
the source of truth for the message catalogue and English is typed against it, so a missing
translation is a compile error rather than a key rendered raw on screen.

### Deployment shape

nginx serves the bundle and proxies `/api` to the API container. One origin, so no CORS and
the bearer token never travels to a second host. The frontend is a **separate image** rather
than static files mounted into FastAPI, and that is deliberate: a mistyped API path returns
a JSON 404 instead of `index.html` with a 200, and the API image ships no HTML at all. The
served image is nginx plus assets — 74 MB, no Node runtime, no `node_modules`.

Verified end to end through that proxy: register → login → watchlist → 269 candles → 7
indicators → 13 IDX fundamentals → analysis with 5 supporting and 5 conflicting factors →
chat. Including the 404: `application/json`, not HTML.

### Three things the type system could not catch

Generated types stop a renamed field. They stop nothing where the API declares a field as a
bare `object`, and all three of these were found by looking at the running application:

- **The indicator snapshot is nested, not flat.** It holds `bars`, `as_of`, `last_close`,
  `structure`, plus nested `indicators`, `levels`, and `breakout` — and MACD, Bollinger,
  ADX, Stochastic, and Ichimoku each carry several components. Rendering it as a flat map
  printed `[object Object]` in four cells. It now formats by scale as well as by shape:
  a moving average is money, an RSI is a plain number, a volatility is a percentage, and
  printing any of them as another is wrong in a way no test would notice.
- **`confidence_basis` was dumped as raw JSON in a scrolling box** — which buried the one
  sentence that makes the score legible: *"Calibrated from 2 usable evidence sources of 3
  possible: coverage 80%, agreement 100%, balance 100%. Capped at 95 because no analysis is
  certain."* That sentence now sits directly under the figure, with the three components
  drawn as bars and the per-agent signals as a table. The raw JSON is still there, folded
  away. A derived confidence that a reader cannot check is no better than an asserted one.
- **The password hint stated a policy that did not exist.** It claimed twelve characters
  with mixed case and a digit; the server enforces ten characters and nothing else.

**Fixed, not accepted:** the `only-export-components` lint warnings on the context files
were first written off here as costing only hot-reload state. That was wrong — the dev log
showed them throwing `useI18n must be used inside an I18nProvider` and white-screening the
app on every edit to either file, because Fast Refresh replaced the module and the context
identity changed underneath every consumer. The hooks now live in `context.ts` beside their
providers; verified by editing both files against a running server and getting two clean
HMR updates.

---

## Architecture

```
src/aidss/
├── config.py            Settings — provider selection is config, never a constant (FR-07)
├── domain/types.py      Provider-agnostic types: Candle, Quote, NewsArticle, ChatMessage
├── plugins/             Section 7 — the four abstraction points
│   ├── interfaces.py    MarketDataProvider · NewsProvider · AIProvider · StorageProvider
│   ├── registry.py      Plugin Manager: registration, contract validation, resolution
│   └── adapters/        fixture · finnhub · openai_compatible · local storage
├── db/                  Section 8.2 — every table, portable across PostgreSQL and SQLite
├── collectors/          Phase 2 — validation → normalisation → idempotent upsert
├── indicators/          Phase 3 — deterministic maths, engine, feature engineering
├── llm/                 Section 12 — gateway, router, resilience, cost, provisioning
├── prompts/             Section 11 — catalog, composer, output schemas, language guard
├── agents/              Section 5 — context builder, memory, analyzers, engine
├── recommendations/     Section 5.4 — calibration, rules, agent, engine
├── portfolio/           Phase 6 — metrics, risk, simulation, analyzers
├── rag/                 Phase 7 — chunking, embedding, retrieval
├── news/                Section 6.3 — cron presets, collector, scheduler
├── reporting/           Phase 8 — reports, notifications, operations overview
├── observability/       Phase 9 — metrics, structured logging, budget
├── jobs/                Section 4 — queue, handlers, worker, scheduler
├── security/            Section 13 — bcrypt, JWT, RBAC
└── api/                 Section 10 — endpoints
```

### Decisions worth knowing

**Numbers are computed, never generated.** The entire `indicators/` package is
LLM-free, and a test enforces that it imports no AI provider. When Phase 4 arrives, the
AI layer receives settled figures and only has to interpret them. This is the plan's
primary mitigation against hallucinated numbers (Sections 2.7, 5.3).

**Idempotency is a property, not a hope.** `historical_prices` is unique on
(asset, timeframe, timestamp) and the collector upserts, so a job that dies halfway
through is safe to retry. The fixture provider anchors its candles to an absolute time
grid for the same reason: overlapping ranges must return identical bars. Both are tested
against the database, and verified live against PostgreSQL.

**Bad data is rejected, not repaired.** Structural violations (high below close,
negative volume, zero price) and implausible jumps are dropped with a recorded reason
rather than silently corrected — a silent fix hides a broken feed. Outliers are measured
against the last *valid* close so one corrupt bar does not cascade.

**Warm-up periods are null, not zero.** An indicator without enough history returns no
value. Zero would read as a measurement of nothing, which is a different claim.

**Swapping a provider is a configuration change.** Adding one means writing a single
adapter and one import line; Core Logic does not change. `GET /providers` shows both
what is registered and what is active. For the AI layer the same applies at runtime:
bindings come from the `ai_providers` table, so an administrator can add a model,
reorder the fallback chain, or route sensitive work to self-hosted inference without a
redeploy.

**The execution-language rule is enforced twice.** Every prompt states it, and
[prompts/validator.py](src/aidss/prompts/validator.py) checks the output regardless of
what the model was told — because a prompt is a request, not a constraint. The check
walks the whole payload, not just the summary field, so a violation hidden in a list
entry is still caught. Section 17 rates an accidental slip into instruction language as
the highest-impact compliance risk in the plan.

**Agents decline rather than improvise.** An analyzer with no data to work on is
recorded as *skipped, with a reason* — distinct from *failed*. Collapsing the two would
hide the difference between "no fundamental data has been ingested" and "the
fundamental analyzer is broken", and the alternative to skipping is fluent, ungrounded
narrative, which is precisely the AI-quality risk in Section 17.

**A failing agent does not fail the analysis.** The remaining analyzers still produce a
result, and the failure is reported next to it. A partial analysis that says what is
missing is more useful than no analysis.

**The confidence score is computed, not reported.** Section 5.4 asks for "a consistently
calibrated score, not an arbitrary number from the LLM". A self-reported confidence
measures how fluent an answer felt, which is close to uncorrelated with how much evidence
stood behind it. So [calibration.py](src/aidss/recommendations/calibration.py) derives it
from three observable properties — how much of the possible evidence was available
(coverage), whether the usable sources agree (agreement), and how one-sided the stated
factors are (balance) — and the model's own number is kept only for comparison. Every
score ships with the sentence that explains it, and the scale stops at 95 because no
analysis is certain.

**A recommendation cannot state a price.** Support, resistance, target, and the suggested
stop are derived from the Indicator Engine with the method recorded; the schema the model
answers with has no price field at all, and `extra="forbid"` makes adding one impossible.
A price invented by a model would sit in the interface beside numbers that were measured.

**A simulation is a question, not a decision.**
[simulation.py](src/aidss/portfolio/simulation.py) has no database session and no import
of any model class — persistence is unreachable rather than merely avoided, and a test
asserts that. A what-if that quietly mutated the stored portfolio would cross the one
line this product exists on the right side of.

**Retrieval is hybrid, and that is what made it testable.** Vector search handles
paraphrase well and exact tokens badly — and this domain is full of exact tokens: a
ticker, a metric name, a ratio. A query for BBCA that returns passages about BBRI is
semantically close and practically useless. BM25 covers exactly that gap, and the two are
combined by reciprocal rank fusion rather than by adding their scores, because cosine
similarity and BM25 are not on comparable scales — whichever happened to have the larger
range would quietly dominate. Every result reports where *each* ranker placed it, because
"vector loved it, lexical never saw it" is the most useful thing to know when a result
looks wrong.

It also closed a gap this README used to admit: retrieval quality was untested, because
the fixture provider's embeddings are pseudo-random and any ordering they produced was
noise. BM25 is deterministic, so relevance is now checkable without a real embedding
model. The live run shows the point plainly — for a `BBCA` query the vector ranker placed
the right document **fourth** and the lexical ranker placed it **first**.

**Exactly one scheduler, enforced rather than instructed.** Several scheduler instances
may run; each tries to hold a database lease and only the holder ticks. A lease rather
than a PostgreSQL advisory lock because it is portable — the mechanism under test is the
one that runs in production — and because it self-heals: an expiry releases it without
anyone having to notice the holder died. The enqueue dedup key is still there, now as a
safety net for the handover window rather than as the design.

**A daily provider allowance is a scheduling problem, not an adapter one.** Alpha
Vantage's free tier is 25 requests a day, and discovering that by being refused is the
expensive way: the refusal arrives as an ordinary provider failure, the job retries with
backoff, and the retries spend tomorrow's allowance too. So the budget is checked first.
A caller reserves a slot, makes the call if it got one, and is told to come back after the
reset if it did not.

Three properties, each learned from something that would otherwise have gone wrong:

- **Atomic**, so two workers cannot both take the last slot — one conditional
  `UPDATE … WHERE used <= limit - count`, the same shape as the leader lease.
- **Committed on its own session.** A reservation taken on the job's transaction is rolled
  back when the job fails, and the HTTP request it authorised cannot be rolled back with
  it. The spend would then have happened at the provider and not in our records, which is
  the one direction of error that ends in being refused.
- **Deferral is not failure.** `queue.defer` returns a job to pending without charging it
  a retry, because "come back after midnight" is not something that went wrong — routing
  it through `fail` would dead-letter a healthy job after three quiet days.

The day is part of the primary key rather than a counter someone has to reset, since
nobody is awake at midnight to reset it. The scheduler queues the stalest assets first,
with an asset that has *no* fundamentals sorting ahead of every asset that has some —
otherwise a large watchlist tops up what it already covers and never reaches what it does
not.

**The queue lives in the database, not a broker.** At this scale that is the better trade
in both directions: a job is enqueued in the same transaction as the rows it concerns, so
there is no window where the data was written and the job was not; and there is no second
system to deploy, monitor, and lose messages in. `SELECT … FOR UPDATE SKIP LOCKED` makes
multi-worker claiming safe on PostgreSQL — verified under real contention, not assumed — and
the SQLite fallback claims optimistically and re-checks, stated as a difference rather than
papered over.

Three failure modes get explicit handling, because a queue is only as trustworthy as its
worst day. A **permanent** error dead-letters immediately, since retrying a malformed
payload three times only delays the alert. A job whose **worker died** is reclaimed after a
lock timeout — otherwise the work silently never happens, which is the worst thing a queue
can do because nothing reports an error. And a handler that **corrupts its own session**
still gets its failure recorded, on a fresh session, rather than leaving the row `RUNNING`
until the reclaim timeout notices.

**The fixture must have production's shape, not a convenient one.** The AI fixture
originally returned 8-dimension embeddings. SQLite stores vectors as JSON and accepted
them; PostgreSQL declares `vector(1536)` and rejected every insert — so the entire RAG
suite passed green while the production path was broken, and only a smoke test against a
real database found it. The width is now a setting (it is a property of the embedding
model, not of the schema), the fixture produces it, and the column type validates it on
*every* dialect so a SQLite test fails for the same reason production would.

**Ingestion is idempotent by construction.** `last_fetched_at` advances only on success,
so a job that dies halfway re-fetches its window instead of skipping it; articles
deduplicate on a hash of URL and headline, so tracking parameters and syndication do not
create copies; and `is_indexed` gates embedding, so a retry does not pay twice. A schedule
that keeps failing is *flagged*, never silently disabled — one that quietly stopped would
look exactly like one finding no news.

**Sentiment is scored in batches, and a wrong index is dropped.** One call per article
turns twenty headlines into twenty round trips. The batch schema keeps each result
separable, and a score referencing an article that was not in the batch is discarded with
a warning rather than attached to whichever article happens to sit at that position.

**Risk figures say what they are.** Every metric carries its observation count, VaR is
withheld below 120 observations rather than computed from a five-day "tail", and the
payload states in words that these describe the past and not the future. A missing figure
reads as "not enough data", never as "no risk".

**An invalid recommendation is unstorable.** Beyond schema and language validation, the
Section 5.4 rules run before anything is written: mandatory narratives must be filled in,
`conflicting_factors` must be non-empty, a label must not contradict unanimous evidence,
and a "strong" label must be backed by calibrated confidence. A violation is fed back as a
specific correction and retried; if it persists, the recommendation is reported as failed
rather than stored with a caveat. Section 15's Phase 5 deliverable is "recommendations
pass schema validation 100%" — the way to reach that is to make the alternative
impossible.

---

## Configuration

All settings use the `AIDSS_` prefix — see [.env.example](.env.example). The ones that
matter most:

| Variable | Default | Notes |
|---|---|---|
| `AIDSS_DATABASE_URL` | local PostgreSQL | |
| `AIDSS_JWT_SECRET` | dev placeholder | **Must** be replaced outside development; use ≥32 bytes |
| `AIDSS_MARKET_DATA_PROVIDER` | `fixture` | `composite`, `yahoo` (free, unofficial), `idx`, `alphavantage`, `finnhub`, or `fixture`. `.env.example` and docker-compose set `yahoo`; the code default stays `fixture` so tests never reach the network. |
| `AIDSS_COMPOSITE_PRICE_PROVIDER` | `yahoo` | Read only when the provider is `composite`. Neither half may itself be `composite` — refused at startup. |
| `AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER` | `idx` | The half that answers `get_fundamentals`, and the name a stored metric is attributed to. `idx` for Indonesian equities; `alphavantage` for US. |
| `AIDSS_IDX_IMPERSONATE` | `chrome` | The `curl_cffi` browser profile. The first thing to change when the IDX adapter starts getting refused. |
| `AIDSS_AI_EMBEDDING_MODEL` | `text-embedding-3-small` | **Empty means lexical-only retrieval**, which is a supported configuration rather than a broken one — see above. |
| `AIDSS_FUNDAMENTALS_DAILY_QUOTA` | `25` | Outbound fundamentals calls per UTC day per provider account. `0` means no ceiling — *unlimited*, not "spend nothing". |
| `AIDSS_FUNDAMENTALS_REFRESH_INTERVAL_DAYS` | `30` | How stale a figure may get before it is queued. Refetching faster than filings change spends an allowance to rewrite identical numbers. |
| `AIDSS_ALPHAVANTAGE_API_KEY` | unset | Free key, 25 requests/day. Without it the `alphavantage` adapter refuses to construct rather than failing later at collection time. |
| `AIDSS_YAHOO_SYMBOL_SUFFIX` | `.JK` | Market suffix for Yahoo symbols; empty for US tickers |
| `AIDSS_ALPHAVANTAGE_SYMBOL_SUFFIX` | `.JKT` | The same idea, different spelling — Jakarta is `.JKT` here, not `.JK` |
| `AIDSS_AI_PROVIDER` | `openai_compatible` | `fixture` for offline runs; `openai_compatible` serves OpenAI, Azure, Ollama, vLLM, LM Studio, Groq, DeepSeek, OpenRouter |
| `AIDSS_AI_BASE_URL` | OpenAI | Point at any OpenAI-compatible endpoint |

Once `ai_providers` has rows, they take precedence over these settings and define the
routing chain (Section 12.10). The settings above are the single-provider fallback that
makes a fresh install work before anything is configured.

Credentials belong in a secret manager, not in these files (Section 13).

---

## Verified end to end

The whole pipeline has been run against PostgreSQL with pgvector and live IDX data, not
only against the test suite:

```
Phase 2–3  BBCA, ASII, TLKM · 323 daily bars each from Yahoo · re-ingest → 0 inserted
Phase 7    28 articles fetched → 28 scored → 28 chunks embedded → RAG search returns hits
Phase 4–5  5 agents ran · watchlist · confidence 78.7 (model self-reported 75)
Phase 6    portfolio 36.1% annualised volatility · −43.4% max drawdown · VaR₉₅ −3.03%
Phase 8    87-line asset report · 54-line portfolio report
Phase 9    /metrics exposes 177 series · security headers present · budget governance live
Queue      POST returned 202 in 65ms · a separate worker process finished the job in ~2s
           a due news schedule fired with no manual trigger: 0 → 25 articles, then
           advanced itself to the next hour
Retrieval  every exact-token query returned the right document first
           `BBCA` → lexical rank 1, vector rank 4 — the case hybrid exists for
```

The confidence figure is worth a second look: it was 54.7 before news was ingested and
78.7 after, because coverage rose from one usable source to two and directional agreement
from 50% (a lone voice) to 100%. Nothing about the prompt changed — the calibration
responded to the evidence, which is what it exists to do.

## Known gaps

Stated plainly rather than left to be discovered:

- **The IDX adapter depends on getting past Cloudflare, and will break.** Not a
  possibility to plan around later — an undocumented endpoint reached through bot
  management is the most fragile thing in this codebase. When it goes, a 403 says so
  specifically and `AIDSS_IDX_IMPERSONATE` is the first thing to try. The live tests
  (`pytest -m network`) are the early warning, and they deliberately *fail* rather than
  skip on a permanent refusal.
- **IDX's terms prohibit redistributing this data commercially.** Personal research is
  fine. This is a real constraint on where the platform can go, not a footnote, and it
  belongs in the Section 13 legal review below.
- **Yahoo's fundamentals endpoint returns 401, and that is not worked around.** The
  parser is complete and tested against a recorded payload, and the live test *skips with
  that reason* rather than failing, so a parser regression would still fail. The
  distinction being drawn: an undocumented but open endpoint is one thing, and an
  authentication requirement the provider added is another.
- **Alpha Vantage publishes no IDX fundamentals.** Confirmed against a real key, not
  inferred: `BBCA.JKT`, `BBCA.JK`, and `BBRI.JKT` all return `{}`. The adapter is complete
  and useful for US equities; it is simply the wrong provider for this market.
- **`ytd` figures are not directly comparable across issuers with different fiscal year
  ends.** A December-year-end company at Q3 carries nine months; a June-year-end company
  at the same date carries three. The basis and the period are both stored so the
  difference is visible, but nothing automatically normalises it.
- **Paraphrase retrieval is unavailable without an embedding model**, which is the
  configuration this deployment runs. Exact-token search is unaffected. Confirming that
  semantic retrieval works when embeddings *are* present still needs a real embedding
  model and a judgement set.
- **Rate-limit and circuit-breaker state is per-process.** Correct for a single worker;
  with several replicas the effective limit multiplies by the replica count. A shared
  store (Redis) makes it exact.
- **Semantic paraphrase retrieval is still unverified.** The lexical half is measured; the
  vector half is only exercised. Confirming that a passage which shares no vocabulary with
  the query but answers it still ranks well needs a real embedding model and a judgement
  set. Until then, expect exact-token retrieval to be good and paraphrase retrieval to be
  unproven.
- **A neutral label gets no target price or stop.** Section 5.4 asks for a target "if a
  basis for calculating one exists"; for a `watchlist` or `hold` stance there is no
  directional basis, and inventing one would defeat the qualification.
- **No streaming endpoint.** Section 12.6 wants it for free-form chat; structured output
  must not stream, and structured output is all this produces.
- **The SQLite queue fallback is single-worker only.** It claims optimistically and
  re-checks, which is correct for the one worker the hermetic tests run. Genuine
  multi-worker contention is covered by `pytest -m postgres`, against the real
  `SKIP LOCKED` path — but only there, and that is the path production uses.

## Next steps

Following Section 19 of the planning document:

1. **Run `pytest -m network` on a schedule.** It is the early warning for the two
   undocumented sources this platform now depends on, and it distinguishes "IDX is down"
   from "the bot protection tightened" from "the units changed" — three findings that
   need three different responses.
2. **Licensed IDX data, if this goes beyond personal use.** Section 19 recommends building
   against a real contract before scale, and the terms constraint above makes that the
   deciding factor rather than a technical preference. Everything downstream is already
   provider-agnostic: it is one settings change.
3. **An embedding model, if paraphrase retrieval is wanted.** The hybrid retrieval path is
   built and the lexical half is measured; adding embeddings is a configuration change
   plus a judgement set to verify the semantic half against.
3. **A retrieval judgement set with a real embedding model**, so the semantic half can be
   measured the way the lexical half now is.
4. **The legal review Section 13 asks for**, before the platform is used more widely than
   personal use. Graded Buy/Sell labels with confidence scores are informational by
   construction here, but whether that positioning holds under OJK rules for investment
   research providers is a question for a lawyer, not for this codebase.
