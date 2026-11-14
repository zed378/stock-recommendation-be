# 04 — Requirement to Test Matrix

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |

Functional requirements are traced in `../01-PRODUCT-REQUIREMENTS/07-REQUIREMENTS-TRACEABILITY.md`. This file
adds the non-functional requirements and the guard tests. **Every test named is planned; none exists yet.**

## Non-Functional Requirements

| NFR | Verified by |
|---|---|
| NFR-T01 `Decimal` money | `no_float_in_ledger_or_order_payload` (unit guard); no float column (migration guard) |
| NFR-T02 Fail closed | Integration I6, I7, I11, I12; acceptance A1 to A3, A17 |
| NFR-T03 Restart safety | Integration I1, I10; resilience R6 |
| NFR-T04 Idempotency | Integration I3, I4; unit `client_order_id_is_pure_and_valid` |
| NFR-T05 Exit latency | Performance P2 |
| NFR-T06 Freshness | Integration I11; UI state tests |
| NFR-T07 Rate limits | Integration I13; performance P1 |
| NFR-T08 Time | Integration I12; resilience R8 |
| NFR-T09 Auditability | Security S11; unit audit tests |
| NFR-T10 Security | Security S1, S4, S5, S14 |
| NFR-T11 Availability | Resilience R1 to R7; acceptance A13 |
| NFR-T12 Recoverability | Restore rehearsal record; runbook R9 |
| NFR-T13 Isolation | Integration I14, I15; security S11 |
| NFR-T14 Resource use | Image check (S13); Kronos never in the order path (S12) |
| NFR-T15 Observability | `05-SELF-OBSERVABILITY.md` tests |
| NFR-T16 Testability | CI runs with no network; guard that no test contacts production |
| NFR-T17 Determinism | Unit strategy determinism |
| NFR-T18 Accessibility | UI accessibility checks for approval and kill controls |
| NFR-T19 Maintainability | Boundary guard |

## Guard Tests

| Guard | Test (planned) |
|---|---|
| Analysis platform guarantee | `tests/test_architecture_constraints.py` (existing, unmodified) |
| Import boundary | `test_aidss_does_not_import_trader_and_reverse_is_limited` |
| No withdrawal | `test_connector_methods_equal_allowlist`, `test_no_route_or_identifier_names_withdrawal` |
| No order route | `test_no_route_accepts_order_entry_parameters` |
| Order path | `test_order_mutating_calls_only_from_order_manager_and_killswitch`, `test_every_create_has_a_risk_result` |
| No MARKET on entry | `test_market_only_on_emergency_paths` |
| Paper isolation | `test_paper_mode_sends_no_order_request` |
| Privileges | `test_trader_rw_cannot_update_or_delete_append_only` |
| Veto | `test_no_path_turns_context_into_an_entry` |

## Coverage Gaps Stated Up Front

- **Live exchange behavior** is verified only by the owner-led read-only check (T2-07); until then every
  connector test is against a mock shaped from documentation.
- **Strategy profitability** is not a test outcome.
- **Kronos or AI value** has no evidence until context exists for crypto pairs (post-MVP, ADR-032).
- **Real-time stop reaction under real market conditions** cannot be tested without live exposure; it is
  observed in `APPROVAL` and the first live period.
