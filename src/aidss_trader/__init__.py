"""AIDSS Trader: autonomous spot trading for IDR pairs on Indodax.

Status: phase T1 (foundation). There is no exchange connector, no order code,
and no strategy here yet; those arrive in T2 to T5 (`TASKS/`).

This package is deliberately outside `aidss`. The analysis platform's
architecture test scans `src/aidss` for order tables, routes, and identifiers
and fails the build if it finds any; keeping execution in its own package is
what lets that guarantee stay true for everything that already exists
(ADR-001). Nothing here imports `aidss`, and `aidss` never imports this.
"""

__version__ = "0.1.0"
