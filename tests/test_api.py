"""End-to-end API tests (Section 10)."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

# --- Auth ------------------------------------------------------------------


def test_register_then_login(client: TestClient) -> None:
    created = client.post(
        "/auth/register", json={"email": "a@example.com", "password": "correct-horse-battery"}
    )
    assert created.status_code == 201
    assert created.json()["role"] == "investor"

    token = client.post(
        "/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"}
    )
    assert token.status_code == 200
    assert token.json()["token_type"] == "bearer"


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": "correct-horse-battery"}
    client.post("/auth/register", json=payload)
    assert client.post("/auth/register", json=payload).status_code == 409


def test_short_password_is_rejected(client: TestClient) -> None:
    response = client.post("/auth/register", json={"email": "x@example.com", "password": "short"})
    assert response.status_code == 422


def test_login_error_does_not_reveal_whether_the_email_exists(client: TestClient) -> None:
    client.post(
        "/auth/register", json={"email": "known@example.com", "password": "correct-horse-battery"}
    )
    wrong_password = client.post(
        "/auth/login", json={"email": "known@example.com", "password": "wrong-password-here"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-here"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_protected_route_requires_a_token(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client: TestClient, auth_headers) -> None:
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "investor@example.com"


# --- RBAC ------------------------------------------------------------------


def test_investor_cannot_read_provider_configuration(client: TestClient, auth_headers) -> None:
    response = client.get("/providers", headers=auth_headers)
    assert response.status_code == 403


def test_admin_can_read_provider_configuration(client: TestClient, admin_headers) -> None:
    response = client.get("/providers", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "fixture" in body["registered"]["market_data"]
    assert body["active"]["market_data"] == "fixture"


# --- Health ----------------------------------------------------------------


def test_health_reports_database_connectivity(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


# --- Market data & indicators ---------------------------------------------


def test_ingest_then_read_candles_and_indicators(client: TestClient, auth_headers) -> None:
    ingest = client.post(
        "/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers
    )
    assert ingest.status_code == 200
    body = ingest.json()
    assert body["fetched"] > 0
    assert body["inserted"] > 0
    assert body["provider"] == "fixture"
    assert body["indicators_inserted"] > 0

    candles = client.get("/assets/BBCA/candles?limit=50", headers=auth_headers)
    assert candles.status_code == 200
    assert len(candles.json()) == 50

    indicators = client.get("/assets/BBCA/indicators", headers=auth_headers)
    assert indicators.status_code == 200
    payload = indicators.json()
    assert payload["snapshot"]["bars"] > 0
    assert "rsi(period=14)" in payload["snapshot"]["indicators"]
    assert payload["features"]["return_1b"] is not None


def test_indicator_output_carries_a_disclaimer(client: TestClient, auth_headers) -> None:
    """Section 2.7: every analytical output states what it is and is not."""
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 200}, headers=auth_headers)
    payload = client.get("/assets/BBCA/indicators", headers=auth_headers).json()
    disclaimer = payload["disclaimer"].lower()
    assert "not investment advice" in disclaimer
    assert "informational" in disclaimer


def test_indicators_before_any_ingestion_returns_409(client: TestClient, auth_headers) -> None:
    client.post("/assets", json={"ticker": "EMPTY"}, headers=auth_headers)
    response = client.get("/assets/EMPTY/indicators", headers=auth_headers)
    assert response.status_code == 409
    assert "ingest" in response.json()["detail"]


def test_unknown_asset_returns_404(client: TestClient, auth_headers) -> None:
    assert client.get("/assets/NOSUCH/candles", headers=auth_headers).status_code == 404


def test_market_data_requires_authentication(client: TestClient) -> None:
    assert client.get("/assets/BBCA/candles").status_code == 401


# --- Watchlist -------------------------------------------------------------


def test_watchlist_crud(client: TestClient, auth_headers) -> None:
    created = client.post("/watchlist", json={"ticker": "TLKM"}, headers=auth_headers)
    assert created.status_code == 201
    item_id = created.json()["id"]

    listed = client.get("/watchlist", headers=auth_headers)
    assert [item["ticker"] for item in listed.json()] == ["TLKM"]

    duplicate = client.post("/watchlist", json={"ticker": "TLKM"}, headers=auth_headers)
    assert duplicate.status_code == 409

    assert client.delete(f"/watchlist/{item_id}", headers=auth_headers).status_code == 204
    assert client.get("/watchlist", headers=auth_headers).json() == []


def test_watchlist_is_scoped_to_its_owner(client: TestClient, auth_headers) -> None:
    created = client.post("/watchlist", json={"ticker": "BBRI"}, headers=auth_headers)
    item_id = created.json()["id"]

    client.post(
        "/auth/register", json={"email": "other@example.com", "password": "correct-horse-battery"}
    )
    other_token = client.post(
        "/auth/login", json={"email": "other@example.com", "password": "correct-horse-battery"}
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    assert client.get("/watchlist", headers=other_headers).json() == []
    # Knowing the id is not enough - ownership is enforced in the query.
    assert client.delete(f"/watchlist/{item_id}", headers=other_headers).status_code == 404


# --- Portfolio -------------------------------------------------------------


def test_portfolio_holdings_are_marked_as_manual_input(client: TestClient, auth_headers) -> None:
    response = client.post(
        "/portfolio/holdings",
        json={"ticker": "ASII", "quantity": "100", "average_price": "5000"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    holding = response.json()["holdings"][0]
    assert holding["ticker"] == "ASII"
    # There is no broker-sync value in the enum; positions are always entered
    # by the user (Section 2.7).
    assert holding["input_method"] == "manual"


def test_upserting_a_holding_updates_rather_than_duplicates(
    client: TestClient, auth_headers
) -> None:
    client.post(
        "/portfolio/holdings",
        json={"ticker": "ASII", "quantity": "100", "average_price": "5000"},
        headers=auth_headers,
    )
    updated = client.post(
        "/portfolio/holdings",
        json={"ticker": "ASII", "quantity": "150", "average_price": "5100"},
        headers=auth_headers,
    )
    holdings = updated.json()["holdings"]
    assert len(holdings) == 1
    assert Decimal(holdings[0]["quantity"]) == Decimal("150")
    assert Decimal(holdings[0]["average_price"]) == Decimal("5100")


def test_negative_quantity_is_rejected(client: TestClient, auth_headers) -> None:
    response = client.post(
        "/portfolio/holdings",
        json={"ticker": "ASII", "quantity": "-5", "average_price": "5000"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_delete_holding(client: TestClient, auth_headers) -> None:
    created = client.post(
        "/portfolio/holdings",
        json={"ticker": "GOTO", "quantity": "1000", "average_price": "70"},
        headers=auth_headers,
    )
    holding_id = created.json()["holdings"][0]["id"]
    deleted = client.delete(f"/portfolio/holdings/{holding_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/portfolio", headers=auth_headers).json()["holdings"] == []
