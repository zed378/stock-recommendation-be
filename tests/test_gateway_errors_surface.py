"""AI-layer failures must reach the caller as answers, not as 500s.

Found in production: asking for a journal reflection returned "Internal Server
Error". The cause was a configuration decision - the reflection agent handles
personal financial data, and no provider was marked as self-hosted, so the
router refused to send it to a third party. That refusal is correct. Reporting
it as a server fault is not: it hides the message explaining how to fix it, and
it sends whoever is on call looking for a bug that does not exist.

The handler is registered once for the whole application rather than caught per
route, because every endpoint that reaches the gateway can raise these and the
one that forgot was the one someone hit.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidss.llm.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    CircuitOpenError,
    GatewayError,
    NoEligibleProviderError,
)
from aidss.llm.router import ModelRouter, ProviderBinding, Sensitivity, TaskComplexity
from aidss.main import _install_gateway_error_handler
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider


def app_raising(exc: GatewayError) -> TestClient:
    app = FastAPI()

    @app.get("/boom")
    def boom() -> dict:
        raise exc

    _install_gateway_error_handler(app)
    # `raise_server_exceptions=False` so an unhandled error surfaces as a 500
    # response rather than propagating - which is what the browser saw.
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (NoEligibleProviderError("no self-hosted provider"), 503),
        (BudgetExceededError(spent=10.0, ceiling=5.0), 429),
        (CircuitOpenError("openai_compatible", 30.0), 503),
        (AllProvidersFailedError({"a": "timeout"}), 502),
    ],
)
def test_each_failure_gets_a_status_that_says_what_happened(exc, expected: int) -> None:
    response = app_raising(exc).get("/boom")
    assert response.status_code == expected, (
        f"{type(exc).__name__} surfaced as {response.status_code}; a 500 would say "
        "the server is broken when it is not"
    )


def test_the_message_reaches_the_caller() -> None:
    """The whole point. "Internal Server Error" is what this replaces."""
    response = app_raising(NoEligibleProviderError("marked as self-hosted")).get("/boom")
    assert "self-hosted" in response.json()["detail"]


def test_an_open_circuit_says_when_to_come_back() -> None:
    response = app_raising(CircuitOpenError("provider", 42.0)).get("/boom")
    assert response.headers["Retry-After"] == "42"


def test_an_unknown_gateway_error_still_gets_a_gateway_status() -> None:
    """A new subclass must not fall back to 500 just for being new."""

    class SomethingNew(GatewayError):
        pass

    assert app_raising(SomethingNew("odd")).get("/boom").status_code == 502


# --- the routing decision the error was reporting --------------------------


def binding(*, self_hosted: bool) -> ProviderBinding:
    return ProviderBinding(
        name="openai_compatible",
        provider=FixtureAIProvider(),
        model="m",
        handles=frozenset(TaskComplexity),
        self_hosted=self_hosted,
    )


def test_sensitive_work_is_refused_without_a_self_hosted_provider() -> None:
    """The behaviour is right and must not be softened: portfolio positions and
    journal entries do not go to a third party by default."""
    router = ModelRouter([binding(self_hosted=False)])
    with pytest.raises(NoEligibleProviderError):
        router.chain(TaskComplexity.COMPLEX, Sensitivity.SENSITIVE)


def test_the_refusal_names_the_setting_that_fixes_it() -> None:
    """"No provider is configured" was true and useless - one *was* configured,
    and it was excluded by a rule the reader has no reason to know about."""
    router = ModelRouter([binding(self_hosted=False)])
    with pytest.raises(NoEligibleProviderError, match="AIDSS_AI_SELF_HOSTED"):
        router.chain(TaskComplexity.COMPLEX, Sensitivity.SENSITIVE)


def test_a_self_hosted_provider_may_take_sensitive_work() -> None:
    router = ModelRouter([binding(self_hosted=True)])
    assert router.chain(TaskComplexity.COMPLEX, Sensitivity.SENSITIVE)


def test_an_unhandled_complexity_reports_that_instead_of_privacy() -> None:
    """Two different causes must not share one message: the fix for each is
    different, and a privacy message sent to someone with a role problem points
    them at the wrong setting."""
    light_only = ProviderBinding(
        name="small",
        provider=FixtureAIProvider(),
        model="m",
        handles=frozenset({TaskComplexity.LIGHT}),
        self_hosted=True,
    )
    with pytest.raises(NoEligibleProviderError, match="handles complexity"):
        ModelRouter([light_only]).chain(TaskComplexity.COMPLEX, Sensitivity.PUBLIC)


def test_no_providers_at_all_says_so_plainly() -> None:
    with pytest.raises(NoEligibleProviderError, match="configured at all"):
        ModelRouter([]).chain(TaskComplexity.LIGHT, Sensitivity.PUBLIC)


def test_the_operator_assertion_reaches_the_binding() -> None:
    """A self-hosted model published at a public domain is indistinguishable
    from a third-party API by inspection, so the operator has to be able to say
    which it is."""
    from aidss.config import Settings
    from aidss.llm.provisioning import build_bindings

    settings = Settings(
        jwt_secret="test-secret-not-for-production-0123456789abcdef",
        ai_provider="openai_compatible",
        ai_base_url="https://ai.example.com/v1",
        ai_api_key="k",
        ai_self_hosted=True,
    )
    assert build_bindings(None, settings)[0].self_hosted is True


def test_the_default_assumes_a_third_party() -> None:
    """Wrong in the safe direction: refusing to send positions somewhere they
    could have gone costs a feature, and the reverse costs the data."""
    from aidss.config import Settings
    from aidss.llm.provisioning import build_bindings

    settings = Settings(
        jwt_secret="test-secret-not-for-production-0123456789abcdef",
        ai_provider="openai_compatible",
        ai_base_url="https://ai.example.com/v1",
        ai_api_key="k",
    )
    assert build_bindings(None, settings)[0].self_hosted is False
