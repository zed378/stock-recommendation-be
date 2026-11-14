# Memory Index

One line per record, newest first. Add new entries at the top.

- [2026-11-14 — T5: operator surface (backend and front end built, unwired)](records/2026-11-14-t5-operator-surface-backend.md) — approvals, step-up (ADR-046 proposed), notifier, promotion, export, API, first front end never rendered in a browser; nothing wired; T5-06 untouched
- [2026-11-14 — T2-T4: Connector, strategy/paper, execution core (built, in review)](records/2026-11-14-t2-t4-connector-strategy-execution.md) — mock-verified only; nothing live, nothing wired into the run loop, no owner numbers set
- [2026-11-14 — T1: Foundation (built, in review)](records/2026-11-14-t1-foundation.md) — credential store, audit chain, lease, limits mechanism, migrations; PostgreSQL privileges and the Docker image NOT verified; analysis DB role is a superuser
- [2026-11-14 — T0: Owner answers, batch 7](records/2026-11-14-owner-answers-batch-7.md) — ADR-043 to 045 (order poll 10 s, lease 15 s/5 s, BTCIDR+ETHIDR, veto decided later); 8 open questions left, all owner numbers or the live check
- [2026-11-14 — T0: Owner answers, batch 6 (order placement numbers)](records/2026-11-14-owner-answers-batch-6.md) — ADR-042 (reprice 5 min x 3, approval 1 h, UNKNOWN 5 queries in 30 s); OQ-22 closed; 11 open questions left
- [2026-11-14 — T0: Owner answers, batch 5 (timing)](records/2026-11-14-owner-answers-batch-5.md) — ADR-041 (price poll 10 s, watchdog 3 cycles, reconcile 60 s, skew halt 250 ms); 12 open questions left
- [2026-11-14 — T0: Owner answers, batch 4](records/2026-11-14-owner-answers-batch-4.md) — ADR-037 to 040 (legal is the owner's, live check after the mock, host liveness script to Telegram, manual backups); two accepted gaps; 14 open questions left
- [2026-11-14 — T0: Owner answers, batch 3](records/2026-11-14-owner-answers-batch-3.md) — ADR-035, 036 (maker-first at the touch, MOC on entries, EXPIRE_TAKER; no automatic FLATTEN); 18 open questions left
- [2026-11-14 — T0: Owner answers, batch 2](records/2026-11-14-owner-answers-batch-2.md) — ADR-031 to 034 (Telegram, MVP without AI context then option B, admin may HALT, day boundary WIB); 19 open questions left
- [2026-11-14 — T0: Owner answers batch 1, four added documents](records/2026-11-14-owner-answers-batch-1.md) — ADR-028 to 030 (UI in existing front end, master key as a host file secret, image public until production); corrects an earlier claim about registering crypto assets
- [2026-11-14 — T0: Trader documentation scaffolding](records/2026-11-14-trader-docs-scaffolding.md) — design interview, 27 ADRs, 100+ documents; found that the analysis platform has no crypto data provider for AI context, that Indodax has no sandbox, and that the trade key cannot be IP-locked
