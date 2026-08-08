"""HTTP middleware: correlation, metrics, security headers, rate limiting.

Phase 9, Sections 2.6 and 13.

Ordering matters and is set in `main.py`: security headers are applied outermost
so they reach a rate-limited or errored response too. A 429 without
`X-Content-Type-Options` is still a response a browser will sniff.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aidss.observability.logging import bind_request, clear_request, new_request_id
from aidss.observability.metrics import MetricsRegistry, registry

logger = logging.getLogger("aidss.api")

#: Headers appropriate to a JSON API. `default-src 'none'` because this service
#: returns data, never a document that should load anything.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

#: Paths whose response must not be cached anywhere. Portfolio and journal data
#: is personal financial information (Section 26); an intermediary caching it
#: is a disclosure.
_PRIVATE_PREFIXES = ("/portfolio", "/journal", "/auth", "/notifications")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        # Off by default: sending HSTS over plain HTTP in development teaches a
        # browser to refuse the local server, and the fix is not obvious.
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith(_PRIVATE_PREFIXES):
            response.headers["Cache-Control"] = "no-store, private"
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, times the request, and records metrics."""

    def __init__(self, app, *, metrics: MetricsRegistry | None = None) -> None:
        super().__init__(app)
        self._metrics = metrics or registry()

    async def dispatch(self, request: Request, call_next) -> Response:
        # An inbound id is honoured so a trace spans the gateway and this
        # service; otherwise one is minted here.
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        bind_request(request_id)

        requests = self._metrics.counter(
            "aidss_http_requests_total", "HTTP requests handled, by method, route and status"
        )
        latency = self._metrics.histogram(
            "aidss_http_request_duration_seconds", "HTTP request duration in seconds"
        )
        in_flight = self._metrics.gauge(
            "aidss_http_requests_in_flight", "Requests currently being handled"
        )

        started = time.perf_counter()
        in_flight.inc(1.0)

        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - started
            route = _route_template(request)
            requests.inc(method=request.method, route=route, status="500")
            latency.observe(elapsed, method=request.method, route=route)
            logger.exception(
                "request failed", extra={"route": route, "method": request.method}
            )
            raise
        finally:
            in_flight.inc(-1.0)
            clear_request()

        # Resolved *after* the call, because the router is what populates
        # `scope["route"]`. Reading it beforehand labels every request
        # "unmatched", which looks like working instrumentation and measures
        # nothing.
        route = _route_template(request)
        elapsed = time.perf_counter() - started
        requests.inc(method=request.method, route=route, status=str(response.status_code))
        latency.observe(elapsed, method=request.method, route=route)

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request handled",
            extra={
                "route": route,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000, 2),
            },
        )
        return response


def _route_template(request: Request) -> str:
    """The route pattern if the router matched one, else a coarse fallback."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    # Unmatched paths collapse to one label rather than one per 404 probed by a
    # scanner - otherwise an attacker controls the cardinality of the metrics.
    return "unmatched"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """A per-client sliding window (Section 26).

    Keyed on the bearer token when present, falling back to client address.
    Token first because several users behind one NAT should not share a budget,
    and one user with several devices should.

    In-process, so with several replicas the effective limit multiplies by the
    replica count. That is a real limitation, stated rather than hidden; a
    shared store makes it exact.
    """

    def __init__(
        self,
        app,
        *,
        requests_per_minute: int = 120,
        window_seconds: float = 60.0,
        exempt_paths: tuple[str, ...] = ("/health", "/metrics"),
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._window = window_seconds
        self._exempt = exempt_paths
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _key(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            # The token itself is never logged or stored - only its hash is used
            # as a bucket key.
            return f"token:{hash(auth[7:])}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self._exempt:
            # Health and metrics must answer even while a client is throttled,
            # or monitoring goes blind exactly when it is needed.
            return await call_next(request)

        key = self._key(request)
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()

        if len(hits) >= self._limit:
            retry_after = max(1, int(self._window - (now - hits[0])))
            logger.warning("rate limit exceeded", extra={"route": _route_template(request)})
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit of {self._limit} requests per "
                        f"{int(self._window)}s exceeded. Retry in {retry_after}s."
                    )
                },
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)
