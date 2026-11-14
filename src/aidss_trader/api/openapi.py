"""Write the Trader API's OpenAPI document, for the front end's generated types.

    python -m aidss_trader.api.openapi frontend/.trader-openapi.json
    (cd frontend && npx openapi-typescript .trader-openapi.json -o src/api/trader-schema.d.ts)

Needs no database, exchange, or analysis API: the document comes from the route
declarations alone, so the context is built from stand-ins that are never called.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from aidss_trader.api.app import ApiContext, create_app


def _unused(*_: Any, **__: Any) -> Any:
    raise RuntimeError("the OpenAPI export never serves a request")


def build_openapi() -> dict[str, Any]:
    ctx = ApiContext(
        session_factory=_unused,
        verifier=None,
        stepup=_unused,
        notifier=_unused,  # type: ignore[arg-type]
        killswitch=_unused,
        submit_approved=_unused,
        thresholds=_unused,
        freshness=lambda: (datetime.now(UTC), True),
    )
    return create_app(ctx).openapi()


if __name__ == "__main__":
    target = sys.argv[1]
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(build_openapi(), fh, indent=2, sort_keys=True)
