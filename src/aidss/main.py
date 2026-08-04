"""FastAPI application factory.

Product positioning note that belongs in code, not just in documentation: this
service is a decision-support tool. It reads market data and produces analysis.
It has no execution engine and no broker adapter, and the absence is enforced
by ``tests/test_architecture_constraints.py`` rather than left to convention.
"""

from __future__ import annotations

from fastapi import FastAPI

from aidss.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from aidss.api.routes import (
    analysis,
    assets,
    auth,
    jobs,
    journal,
    knowledge,
    portfolio,
    reports,
    system,
    watchlist,
)
from aidss.config import Settings, get_settings
from aidss.observability.logging import configure_logging

DESCRIPTION = """
Decision-support platform for investment analysis.

**Read-only by design.** The API surface has no order, execution, or broker
endpoint, and no module capable of sending an instruction to a trading account.
Every buy/sell decision is made manually by the user, outside this system.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.json_logs)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
    )

    # Load every bundled adapter into the plugin registry. Importing for the
    # side effect is deliberate: adapters self-register via @register.
    import aidss.plugins  # noqa: F401

    # Starlette applies middleware in reverse registration order, so the last
    # added runs outermost. Security headers go last deliberately: a 429 or a
    # 500 needs them just as much as a 200 does.
    app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.enable_hsts)

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(assets.router)
    app.include_router(analysis.router)
    app.include_router(watchlist.router)
    app.include_router(portfolio.router)
    app.include_router(knowledge.router)
    app.include_router(reports.router)
    app.include_router(journal.router)
    app.include_router(jobs.router)
    return app


app = create_app()
