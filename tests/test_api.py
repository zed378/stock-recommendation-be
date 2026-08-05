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


# --- Watchlist categories --------------------------------------------------
#
# Named watchlists were always in the schema; every endpoint just hardcoded
# "Default". These tests pin the behaviour now that the name is reachable.


def add(client: TestClient, headers, ticker: str, category: str | None = None, note=None):
    body: dict = {"ticker": ticker}
    if category:
        body["category"] = category
    if note:
        body["note"] = note
    return client.post("/watchlist", json=body, headers=headers)


def test_an_item_lands_in_the_category_it_was_given(client: TestClient, auth_headers) -> None:
    response = add(client, auth_headers, "BBCA", "Perbankan")
    assert response.status_code == 201
    assert response.json()["category"] == "Perbankan"


def test_no_category_means_the_default_one(client: TestClient, auth_headers) -> None:
    assert add(client, auth_headers, "BBCA").json()["category"] == "Default"


def test_the_same_ticker_may_sit_in_two_categories(client: TestClient, auth_headers) -> None:
    """A bank that pays dividends belongs in both, and forcing a choice would
    make the grouping less useful than no grouping."""
    assert add(client, auth_headers, "BBCA", "Perbankan").status_code == 201
    assert add(client, auth_headers, "BBCA", "Dividen").status_code == 201

    listed = client.get("/watchlist", headers=auth_headers).json()
    assert sorted(item["category"] for item in listed) == ["Dividen", "Perbankan"]


def test_a_duplicate_within_one_category_is_still_refused(
    client: TestClient, auth_headers
) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    duplicate = add(client, auth_headers, "BBCA", "Perbankan")
    assert duplicate.status_code == 409
    assert "Perbankan" in duplicate.json()["detail"]


def test_a_category_name_is_trimmed(client: TestClient, auth_headers) -> None:
    """Otherwise "Perbankan" and "Perbankan " become two groups that look
    identical in the interface."""
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "BBRI", "  Perbankan  ")

    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert [row["name"] for row in rows] == ["Perbankan"]


def test_categories_report_their_sizes(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "BBRI", "Perbankan")
    add(client, auth_headers, "ADRO", "Energi")

    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert {row["name"]: row["count"] for row in rows} == {"Energi": 1, "Perbankan": 2}


def test_a_category_can_be_created_without_a_ticker(client: TestClient, auth_headers) -> None:
    """Organising a watchlist used to be possible only while adding to it:
    someone who wanted three groups first had to pick three tickers to put in
    them."""
    response = client.post(
        "/watchlist/categories", json={"name": "Perbankan"}, headers=auth_headers
    )
    assert response.status_code == 201
    assert response.json() == {"name": "Perbankan", "count": 0}

    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert {"name": "Perbankan", "count": 0} in rows


def test_a_created_category_can_be_filled(client: TestClient, auth_headers) -> None:
    """The group made up front must be the same one an add lands in, not a
    second row that happens to share its name."""
    client.post("/watchlist/categories", json={"name": "Energi"}, headers=auth_headers)
    add(client, auth_headers, "ADRO", "Energi")

    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert [row for row in rows if row["name"] == "Energi"] == [
        {"name": "Energi", "count": 1}
    ]


def test_creating_a_category_that_exists_is_refused(client: TestClient, auth_headers) -> None:
    """Returning the existing group would look identical to having made a new
    one, and the reader would believe they had two."""
    add(client, auth_headers, "BBCA", "Perbankan")
    response = client.post(
        "/watchlist/categories", json={"name": "Perbankan"}, headers=auth_headers
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_a_created_category_name_is_trimmed(client: TestClient, auth_headers) -> None:
    client.post(
        "/watchlist/categories", json={"name": "  Perbankan  "}, headers=auth_headers
    )
    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert [row["name"] for row in rows] == ["Perbankan"]


def test_a_blank_category_name_is_refused(client: TestClient, auth_headers) -> None:
    """Whitespace trims to nothing, which would otherwise create a group with an
    invisible name that cannot be told apart from any other."""
    response = client.post(
        "/watchlist/categories", json={"name": "   "}, headers=auth_headers
    )
    assert response.status_code == 422


def test_a_created_category_belongs_to_its_owner(client: TestClient, auth_headers) -> None:
    client.post("/watchlist/categories", json={"name": "Perbankan"}, headers=auth_headers)

    credentials = {"email": "cat-owner@example.com", "password": "correct-horse-battery"}
    client.post("/auth/register", json=credentials)
    token = client.post("/auth/login", json=credentials).json()["access_token"]

    other = {"Authorization": f"Bearer {token}"}
    assert client.get("/watchlist/categories", headers=other).json() == []


def test_an_emptied_category_still_exists(client: TestClient, auth_headers) -> None:
    """Removing the last item empties a group; it does not delete it. Hiding it
    would make the removal look as though it took the group with it."""
    item_id = add(client, auth_headers, "BBCA", "Perbankan").json()["id"]
    client.delete(f"/watchlist/{item_id}", headers=auth_headers)

    rows = client.get("/watchlist/categories", headers=auth_headers).json()
    assert {"name": "Perbankan", "count": 0} in rows


def test_listing_can_be_narrowed_to_one_category(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "ADRO", "Energi")

    listed = client.get("/watchlist", params={"category": "Energi"}, headers=auth_headers).json()
    assert [item["ticker"] for item in listed] == ["ADRO"]


def test_an_item_outside_the_default_category_can_be_deleted(
    client: TestClient, auth_headers
) -> None:
    """The bug categories would have introduced: delete used to scope to the
    "Default" list alone, which would have stranded everything else."""
    item_id = add(client, auth_headers, "BBCA", "Perbankan").json()["id"]
    assert client.delete(f"/watchlist/{item_id}", headers=auth_headers).status_code == 204
    assert client.get("/watchlist", headers=auth_headers).json() == []


def test_an_item_can_be_moved_between_categories(client: TestClient, auth_headers) -> None:
    item_id = add(client, auth_headers, "BBCA", "Perbankan").json()["id"]
    moved = client.patch(
        f"/watchlist/{item_id}", json={"category": "Dividen"}, headers=auth_headers
    )
    assert moved.status_code == 200
    assert moved.json()["category"] == "Dividen"


def test_moving_onto_an_existing_entry_is_refused_cleanly(
    client: TestClient, auth_headers
) -> None:
    """Checked rather than left to the unique constraint, which would surface
    as a 500 with a database message in it."""
    add(client, auth_headers, "BBCA", "Dividen")
    item_id = add(client, auth_headers, "BBCA", "Perbankan").json()["id"]

    clash = client.patch(
        f"/watchlist/{item_id}", json={"category": "Dividen"}, headers=auth_headers
    )
    assert clash.status_code == 409


def test_moving_an_item_that_is_not_yours_is_a_404(client: TestClient, auth_headers) -> None:
    item_id = add(client, auth_headers, "BBCA", "Perbankan").json()["id"]
    client.post(
        "/auth/register", json={"email": "mover@example.com", "password": "correct-horse-battery"}
    )
    token = client.post(
        "/auth/login", json={"email": "mover@example.com", "password": "correct-horse-battery"}
    ).json()["access_token"]

    response = client.patch(
        f"/watchlist/{item_id}",
        json={"category": "Milik Saya"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_a_category_can_be_renamed_carrying_its_items(client: TestClient, auth_headers) -> None:
    """The rename moves the row, not the items - so there is no window where a
    half-applied rename leaves some of them in the old group."""
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "BBRI", "Perbankan")

    renamed = client.patch(
        "/watchlist/categories/Perbankan", json={"name": "Bank"}, headers=auth_headers
    )
    assert renamed.status_code == 200
    assert renamed.json() == {"name": "Bank", "count": 2}

    listed = client.get("/watchlist", headers=auth_headers).json()
    assert {item["category"] for item in listed} == {"Bank"}


def test_renaming_onto_an_existing_category_is_refused(client: TestClient, auth_headers) -> None:
    """Merging is not attempted: it would silently combine two groups the user
    separated on purpose, and the undo is manual."""
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "ADRO", "Energi")

    clash = client.patch(
        "/watchlist/categories/Perbankan", json={"name": "Energi"}, headers=auth_headers
    )
    assert clash.status_code == 409


def test_renaming_a_category_that_is_not_yours_is_a_404(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    client.post(
        "/auth/register", json={"email": "other2@example.com", "password": "correct-horse-battery"}
    )
    token = client.post(
        "/auth/login", json={"email": "other2@example.com", "password": "correct-horse-battery"}
    ).json()["access_token"]

    response = client.patch(
        "/watchlist/categories/Perbankan",
        json={"name": "Milik Saya"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_deleting_a_category_moves_its_items_to_default(
    client: TestClient, auth_headers
) -> None:
    """Deleting a grouping is not the same as deciding to stop following the
    assets in it, and one action doing both makes a mis-click expensive."""
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "BBRI", "Perbankan")

    deleted = client.delete("/watchlist/categories/Perbankan", headers=auth_headers)
    assert deleted.status_code == 200

    listed = client.get("/watchlist", headers=auth_headers).json()
    assert sorted(item["ticker"] for item in listed) == ["BBCA", "BBRI"]
    assert {item["category"] for item in listed} == {"Default"}

    names = [row["name"] for row in deleted.json()]
    assert "Perbankan" not in names


def test_an_asset_already_in_default_is_not_duplicated_by_the_move(
    client: TestClient, auth_headers
) -> None:
    """Per-category uniqueness would reject the move; dropping the row loses
    nothing, because the asset stays followed either way."""
    add(client, auth_headers, "BBCA", "Default")
    add(client, auth_headers, "BBCA", "Perbankan")

    assert client.delete("/watchlist/categories/Perbankan", headers=auth_headers).status_code == 200

    listed = client.get("/watchlist", headers=auth_headers).json()
    assert [(i["ticker"], i["category"]) for i in listed] == [("BBCA", "Default")]


def test_the_default_category_cannot_be_deleted(client: TestClient, auth_headers) -> None:
    """It is where everything else lands, so removing it would leave the
    fallback with nowhere to fall back to."""
    add(client, auth_headers, "BBCA", "Default")
    response = client.delete("/watchlist/categories/Default", headers=auth_headers)
    assert response.status_code == 409
    assert "Default" in response.json()["detail"]


def test_deleting_an_unknown_category_is_a_404(client: TestClient, auth_headers) -> None:
    assert client.delete("/watchlist/categories/Nope", headers=auth_headers).status_code == 404


# --- Watchlist search ------------------------------------------------------


def test_search_matches_a_ticker(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "ADRO", "Energi")

    found = client.get("/watchlist/search", params={"q": "BBC"}, headers=auth_headers).json()
    assert [item["ticker"] for item in found] == ["BBCA"]


def test_search_matches_the_users_own_note(client: TestClient, auth_headers) -> None:
    """The note is where the reason for following something lives, and that is
    more often what someone is looking for than a code they already know."""
    add(client, auth_headers, "BBCA", "Perbankan", note="kandidat dividen kuartal depan")
    add(client, auth_headers, "ADRO", "Energi", note="menunggu laporan Q3")

    found = client.get("/watchlist/search", params={"q": "dividen"}, headers=auth_headers).json()
    assert [item["ticker"] for item in found] == ["BBCA"]


def test_search_is_case_insensitive(client: TestClient, auth_headers) -> None:
    """`like` is case-sensitive on PostgreSQL, which would turn searching your
    own free-text note into a guess about how you typed it."""
    add(client, auth_headers, "BBCA", "Perbankan", note="Kandidat Dividen")
    found = client.get("/watchlist/search", params={"q": "KANDIDAT"}, headers=auth_headers).json()
    assert [item["ticker"] for item in found] == ["BBCA"]


def test_search_matches_a_category_name(client: TestClient, auth_headers) -> None:
    """Someone reading a group heading on screen and typing it into the box
    expects to find that group. Leaving the category out of the search made the
    most obvious query return nothing at all."""
    add(client, auth_headers, "BBCA", "Perbankan")
    add(client, auth_headers, "ADRO", "Energi")

    found = client.get("/watchlist/search", params={"q": "perbank"}, headers=auth_headers).json()
    assert [item["ticker"] for item in found] == ["BBCA"]


def test_search_can_be_narrowed_to_a_category(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan", note="dividen")
    add(client, auth_headers, "ADRO", "Energi", note="dividen")

    found = client.get(
        "/watchlist/search", params={"q": "dividen", "category": "Energi"}, headers=auth_headers
    ).json()
    assert [item["ticker"] for item in found] == ["ADRO"]


def test_search_returns_nothing_rather_than_everything_on_no_match(
    client: TestClient, auth_headers
) -> None:
    add(client, auth_headers, "BBCA", "Perbankan")
    assert client.get("/watchlist/search", params={"q": "zzz"}, headers=auth_headers).json() == []


def test_search_does_not_reach_another_users_items(client: TestClient, auth_headers) -> None:
    add(client, auth_headers, "BBCA", "Perbankan", note="rahasia")
    client.post(
        "/auth/register", json={"email": "nosy@example.com", "password": "correct-horse-battery"}
    )
    token = client.post(
        "/auth/login", json={"email": "nosy@example.com", "password": "correct-horse-battery"}
    ).json()["access_token"]

    found = client.get(
        "/watchlist/search",
        params={"q": "rahasia"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert found.json() == []


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
