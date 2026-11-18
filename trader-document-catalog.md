# AIDSS Trader — Documentation Catalog

## 1. Purpose

This catalog is the index of the documentation for the **AIDSS Trader**: an autonomous spot-trading service
for IDR pairs on Indodax, designed to sit beside the existing AIDSS analysis platform. It states what each
document is for. **It is the index, not the documentation**: per-topic detail lives in the topic's file.

**The Trader is specified but not built.** `TASKS/PROGRESS.md` is the only authority on what exists.

## 2. Architecture and Behavior Principles

1. **Separate service.** Trading lives in its own package, container, schema, and database role. The analysis
   platform stays read-only and keeps its architecture test unmodified (ADR-001, ADR-021).
2. **Every order passes the Risk Engine.** No path skips it (ADR-009).
3. **Deterministic rules decide.** AI and Kronos are context and may veto an entry; they never create, size,
   price, or modify an order (ADR-004).
4. **Fail closed.** Doubt halts trading; nothing continues "with a warning".
5. **The exchange is the source of truth.** The ledger is reconciled to Indodax; a difference halts
   (ADR-022).
6. **Staged autonomy.** `PAPER`, then `APPROVAL`, then `AUTO`, each earned by measurable gates the owner sets
   (ADR-003, ADR-020).
7. **No withdrawal code, ever.** The key is Read plus Trade; a key reporting withdrawal permission is refused
   (ADR-013).
8. **Idempotent orders.** A write whose outcome is unknown is resolved by query, never by a blind retry
   (ADR-024, ADR-026).
9. **Money is `Decimal`.** Quantized to the pair's increments (ADR-025).
10. **No fabricated data.** Paper, backtest, and live are labelled and never mixed.
11. **Nothing is invented.** Where a decision or a number is not made, the document says so and points to its
    open question. A number that limits loss is never defaulted.

## 3. Repository Structure

```text
CLAUDE.md                     operating instructions for agents
AGENTS.md                     roles and working agreements
trader-document-catalog.md    this file
docs/
├── 00-PROJECT-CONTEXT/
├── 01-PRODUCT-REQUIREMENTS/
├── 02-ARCHITECTURE/
├── 03-DATA-MODEL/
├── 04-UX-UI/
├── 05-MODULE-SPECIFICATIONS/
├── 06-INTEGRATIONS/
├── 07-API-CONTRACTS/
├── 08-AI-AGENT/
├── 09-SECURITY-PRIVACY/
├── 10-OPERATIONS/
├── 11-TESTING-QUALITY/
├── 12-DELIVERY-PLAN/
└── archive/                  the analysis platform's planning document
MEMORY/                       what was done and why (ADRs, records, templates)
TASKS/                        what will be done (phases, progress, backlog)
```

## 4. Document Inventory

### `00-PROJECT-CONTEXT/` (6)

| File | Purpose |
|---|---|
| `00-README.md` | Entry point, reading order by role, ownership |
| `01-SYSTEM-CONTEXT.md` | Boundary, actors, upstream and downstream systems |
| `02-GLOSSARY.md` | Trading and Indodax terms, including the three spellings of a pair |
| `03-DECISION-LOG.md` | Index of ADRs and deviations from the reference structure |
| `04-ASSUMPTIONS-CONSTRAINTS.md` | Sourced constraints, assumptions, safe defaults |
| `05-AI-AGENT-EXECUTION-RULES.md` | What a coding agent may and may not do |

### `01-PRODUCT-REQUIREMENTS/` (9)

| File | Purpose |
|---|---|
| `00-PRODUCT-VISION.md` | What it is, what success is checkable as, what it is not, a plain statement of risk |
| `01-PRODUCT-SCOPE.md` | In scope, out of scope, deferred, MVP boundary |
| `02-STAKEHOLDERS-AND-PERSONAS.md` | The owner and the non-human actors |
| `03-USE-CASES.md` | UC-T01 to UC-T10 journeys |
| `04-FUNCTIONAL-REQUIREMENTS.md` | FR-T01 to FR-T35 with testable acceptance |
| `05-NONFUNCTIONAL-REQUIREMENTS.md` | NFR-T01 to NFR-T19 |
| `06-ROLE-PERMISSION-MATRIX.md` | `trader` role and `trade:*` permissions |
| `07-REQUIREMENTS-TRACEABILITY.md` | Requirement to module, API, planned test, task |
| `08-OWNER-NUMBERS-WORKSHEET.md` | Every owner-set number in one place, blank, with the relationships that must hold |

### `02-ARCHITECTURE/` (10)

| File | Purpose |
|---|---|
| `00-ARCHITECTURE-OVERVIEW.md` | Shape, principles, components, main flow |
| `01-C4-CONTEXT.md` | System context and relationships |
| `02-C4-CONTAINERS.md` | The `trader` container and data stores |
| `03-COMPONENT-ARCHITECTURE.md` | Responsibilities, dependency rules, the emergency path |
| `04-INTEGRATION-TOPOLOGY.md` | Flows to Indodax and other systems; what is not used |
| `05-DATA-INGESTION-AND-SYNC.md` | Polling streams, candle handling, backfill, 7-day windows |
| `06-EVENT-AND-ALERT-FLOW.md` | Trading events, severity, delivery |
| `07-RESILIENCE-AND-DEGRADATION.md` | Retry classes, failure modes, write-ahead, single instance |
| `08-CACHING-AND-PERFORMANCE.md` | Rate limits, request budget, caching rules |
| `09-ARCHITECTURE-DECISIONS.md` | ADRs that shape the architecture; when a new ADR is required |

### `03-DATA-MODEL/` (9)

| File | Purpose |
|---|---|
| `00-CANONICAL-DOMAIN-MODEL.md` | Entities, relationships, cross-cutting fields |
| `01-SOURCE-OF-TRUTH-MATRIX.md` | Which system is authoritative for each fact |
| `02-STATUS-AND-STATE-MACHINES.md` | Order, intent, mode, and trading-state machines |
| `03-TIME-SERIES-AND-MARKET-DATA.md` | Candle schema, normalization, gaps |
| `04-ORDER-POSITION-LEDGER-SCHEMA.md` | Orders, fills, ledger, positions, PnL |
| `05-RISK-AND-AUDIT-SCHEMA.md` | Limits, breakers, kill switch, audit |
| `06-DATA-RETENTION-AND-PROVENANCE.md` | Origin, retention, what is never stored |
| `07-DATABASE-AND-MIGRATION-POLICY.md` | Schema isolation, privileges, additive migrations |
| `08-SETTINGS-REGISTRY.md` | Every setting: type, validation, what happens while unset, who changes it |

### `04-UX-UI/` (4)

| File | Purpose |
|---|---|
| `00-UX-PRINCIPLES.md` | State first, honest labels, deliberate destructive actions |
| `01-TRADING-DASHBOARD-SPEC.md` | The dashboard panels and freshness rules |
| `02-APPROVAL-QUEUE-AND-CONTROLS.md` | Approval card, kill switch, promotion, editors |
| `03-LOADING-EMPTY-ERROR-STALE-STATES.md` | Distinct states, never zero for missing |

### `05-MODULE-SPECIFICATIONS/` (13)

| File | Purpose |
|---|---|
| `01-STRATEGY-ENGINE.md` | Pure-function strategies; the EMA plus ADX reference |
| `02-SIGNAL-TO-INTENT.md` | Sizing, quantization, entry and exit intents |
| `03-RISK-ENGINE.md` | Checks, profiles, circuit breakers |
| `04-ORDER-MANAGER.md` | Create flow, write-ahead, `UNKNOWN`, lifecycle |
| `05-POSITION-AND-LEDGER.md` | Ledger, weighted average cost, the cost split gap |
| `06-PAPER-TRADING-AND-BACKTEST.md` | Conservative paper fills, backtest without look-ahead |
| `07-APPROVAL-WORKFLOW.md` | Approval bound to the exact intent |
| `08-KILL-SWITCH.md` | `HALT`, `CANCEL`, `FLATTEN`; independence |
| `09-EXIT-MONITOR.md` | Bot-side stops, watchdog, what happens when down |
| `10-RECONCILIATION.md` | What is compared, difference kinds, response |
| `11-MODE-PROMOTION.md` | Gates, evidence, why thresholds are not defaulted |
| `12-NOTIFICATIONS.md` | Events, severity, content rules |
| `13-CREDENTIAL-ADMINISTRATION.md` | Store, test, rotate, master key |

### `06-INTEGRATIONS/` (15)

| File | Purpose |
|---|---|
| `00-INTEGRATION-CATALOG.md` | Every integration, its status, and what is excluded |
| `01-CONNECTOR-CONTRACT.md` | Allowlisted operations, result shape, error classes, retry classes |
| `02-CREDENTIALS-AND-AUTH.md` | Credentials held, key requirements, the legacy-auth unknown |
| `03-INDODAX-OVERVIEW.md` | The API surfaces and which are used |
| `04-INDODAX-AUTH-AND-SIGNING.md` | Headers, what is signed, time parameters |
| `05-INDODAX-MARKET-DATA.md` | Pairs, OHLC, tickers, depth |
| `06-INDODAX-ORDERS.md` | Create, cancel, get, open orders, enums |
| `07-INDODAX-ACCOUNT-AND-HISTORY.md` | Account, order history, trade history |
| `08-INDODAX-ERRORS-AND-RATE-LIMITS.md` | Error codes mapped to classes; limits and which binds |
| `09-INDODAX-WEBSOCKETS-AND-DEADMAN-DEFERRED.md` | Deferred features and when to revisit |
| `10-INDODAX-STP-AND-FEES.md` | Self-trade prevention and the cost structure |
| `11-INDODAX-DOCS-DISCREPANCIES.md` | Where Indodax's documentation disagrees with itself |
| `12-NOTIFICATION-CHANNEL.md` | The interface needed; what must be checked before choosing |
| `13-AIDSS-ANALYSIS-PLATFORM.md` | The internal integration and the crypto gap |
| `14-INDODAX-LIVE-VERIFICATION-PLAN.md` | The read-only first contact with the real exchange (T2-07) |

### `07-API-CONTRACTS/` (3)

| File | Purpose |
|---|---|
| `00-API-STANDARDS.md` | Envelope, errors, idempotency, hard rules |
| `01-TRADER-API.md` | Routes and permissions; what does not exist |
| `02-INTERNAL-EVENTS-AND-ERRORS.md` | Event shape, component events, normalized errors |

### `08-AI-AGENT/` (8)

| File | Purpose |
|---|---|
| `00-AI-BOUNDARIES-IN-TRADING.md` | What AI may and must never do |
| `01-ANALYSIS-CONTEXT-BRIDGE.md` | The typed request and response |
| `02-VETO-RULES.md` | Rule shapes; entry only; disabled until evidence |
| `03-KRONOS-ON-CPU.md` | Measured behavior and honest limitations |
| `04-EVIDENCE-AND-HALLUCINATION-CONTROLS.md` | Why the architecture bounds model error |
| `05-HUMAN-REVIEW-AND-AUDIT.md` | What the owner sees and what is stored |
| `06-AI-EVALUATION-AND-TEST-DATA.md` | Counterfactual evaluation, record-only mode |
| `07-ANALYSIS-PLATFORM-CRYPTO-ADAPTER-SPEC.md` | Conditional: the small analysis-platform change that would supply Kronos context for crypto |

### `09-SECURITY-PRIVACY/` (8)

| File | Purpose |
|---|---|
| `00-THREAT-MODEL.md` | Threats, controls, accepted residual risks |
| `01-IDENTITY-RBAC.md` | Identity, roles, step-up authentication |
| `02-SECRETS-AND-KEY-ROTATION.md` | Inventory, rules, rotation, custody |
| `03-NETWORK-AND-TRUST-BOUNDARIES.md` | Boundaries, egress allowlist |
| `04-AUDIT-LOGGING.md` | What is audited, tamper evidence |
| `05-SENSITIVE-DATA-REDACTION.md` | Where redaction applies and how |
| `06-INBOUND-SECURITY.md` | The operator API; the channel is not a control path |
| `07-SOFTWARE-SUPPLY-CHAIN.md` | Dependencies, images, registry visibility |

### `10-OPERATIONS/` (10)

| File | Purpose |
|---|---|
| `00-ENVIRONMENTS-AND-CONFIG.md` | No sandbox; settings with no default |
| `01-LOCAL-DEVELOPMENT.md` | The intended workflow against the mock |
| `02-DEPLOYMENT-ARCHITECTURE.md` | The `trader` service and host considerations |
| `03-RELEASE-AND-ROLLBACK.md` | Procedure; the unprotected window |
| `04-BACKUP-RESTORE-AND-RECOVERY.md` | Schema backup, restore, rehearsal |
| `05-SELF-OBSERVABILITY.md` | Logs, metrics, the watchdog problem |
| `06-RUNBOOKS.md` | R1 to R16 for the owner under stress (including R14 liveness, R15 lock update, R16 anchor watch) |
| `07-INCIDENT-AND-ESCALATION.md` | Severity, response, post-incident records |
| `08-HOST-FIREWALL-PLAN.md` | Unapplied host/Docker firewall proposal (Stage 1 rendered, Stage 2 awaits client inventory), owner questions and rollback |
| `09-MIGRATION-RUNBOOK.md` | Production migration kit, source equivalence and recovery gates |

### `11-TESTING-QUALITY/` (8)

| File | Purpose |
|---|---|
| `00-TEST-STRATEGY.md` | Principles, layers, permanent guard tests |
| `01-UNIT-TESTS.md` | Pure-logic coverage |
| `02-CONNECTOR-CONTRACT-TESTS.md` | Cases per method; both documented forms |
| `03-INTEGRATION-TESTS.md` | I1 to I22 |
| `04-END-TO-END-ACCEPTANCE.md` | A1 to A22 |
| `05-SECURITY-TESTS.md` | S1 to S17 |
| `06-PERFORMANCE-AND-RESILIENCE-TESTS.md` | P1 to P6, R1 to R11, soak |
| `07-FIXTURES-AND-MOCK-SERVERS.md` | The mock exchange and fixture rules |

### `12-DELIVERY-PLAN/` (7)

| File | Purpose |
|---|---|
| `00-ROADMAP.md` | Phases T0 to T6 and what the owner must decide before each |
| `01-IMPLEMENTATION-BACKLOG.md` | Index of task cards |
| `02-AGENT-EXECUTION-ORDER.md` | Order of work and stop points |
| `03-DEFINITION-OF-READY-DONE.md` | Ready and Done, and what is never waivable |
| `04-REQUIREMENT-TO-TEST-MATRIX.md` | NFRs and guards to tests; coverage gaps stated |
| `05-RELEASE-CHECKLIST.md` | Before contact, before real money, before `AUTO` |
| `06-DOCUMENTATION-MAINTENANCE.md` | Keeping documents honest |

## 5. Decision Rule for Adding a Document

Add a document only when a task, an ADR, or the owner needs it. An empty file to complete a tree is not a
document. Ideas for new documents are proposed to the owner first; once confirmed, the document, its
catalog entry, and its tasks are added together.

## 6. Reading Order

`docs/00-PROJECT-CONTEXT/00-README.md` first, then by role as listed there.
