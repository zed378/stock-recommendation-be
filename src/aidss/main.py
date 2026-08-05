"""FastAPI application factory.

Product positioning note that belongs in code, not just in documentation: this
service is a decision-support tool. It reads market data and produces analysis.
It has no execution engine and no broker adapter, and the absence is enforced
by ``tests/test_architecture_constraints.py`` rather than left to convention.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

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
    market,
    portfolio,
    reports,
    system,
    watchlist,
)
from aidss.config import Settings, get_settings
from aidss.llm.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    CircuitOpenError,
    GatewayError,
    NoEligibleProviderError,
)
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
    app.include_router(market.router)
    _install_gateway_error_handler(app)
    return app


#: How each gateway failure should reach the caller. The distinction is not
#: cosmetic: a client can retry a 503 and must not retry a 402-shaped budget
#: refusal, and an operator reading 500s in a dashboard learns nothing about
#: which of the two happened.
_GATEWAY_STATUS: tuple[tuple[type[GatewayError], int], ...] = (
    (BudgetExceededError, status.HTTP_429_TOO_MANY_REQUESTS),
    (CircuitOpenError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (NoEligibleProviderError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (AllProvidersFailedError, status.HTTP_502_BAD_GATEWAY),
)


def _install_gateway_error_handler(app: FastAPI) -> None:
    """Turn AI-layer failures into answers rather than 500s.

    Registered once for the whole application rather than caught per route.
    Every endpoint that reaches the gateway can raise these, and the one that
    forgot was the one someone hit: a configuration problem - no provider
    permitted to see personal financial data - surfaced as "Internal Server
    Error", which hides the very message that explains how to fix it.

    A 500 also says the wrong thing. None of these is a bug in the server; they
    are a budget reached, a breaker open, or a provider not configured for the
    request. Reporting them as faults sends whoever is on call looking for one.
    """

    @app.exception_handler(GatewayError)
    async def handle_gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        code = next(
            (status_code for kind, status_code in _GATEWAY_STATUS if isinstance(exc, kind)),
            status.HTTP_502_BAD_GATEWAY,
        )
        headers = {}
        if isinstance(exc, CircuitOpenError):
            # Standard, and actionable: the breaker already knows how long.
            headers["Retry-After"] = str(max(1, int(exc.retry_after)))
        return JSONResponse(status_code=code, content={"detail": str(exc)}, headers=headers)


app = create_app()
