from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.combat.cards import STARTER_CARDS
from app.main import create_app


def test_email_code_login_and_collection() -> None:
    client = TestClient(create_app())
    email = f"player-{uuid4().hex}@example.com"

    request_response = client.post("/api/auth/email/request", json={"email": email})
    assert request_response.status_code == 200
    code = request_response.json()["dev_code"]
    assert len(code) == 6

    verify_response = client.post(
        "/api/auth/email/verify",
        json={"email": email, "code": code},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["user"]["email"] == email
    assert "refresh_token" in verify_response.cookies

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["coins"] == 0

    collection_response = client.get("/api/me/collection")
    assert collection_response.status_code == 200
    cards = collection_response.json()["cards"]
    assert {card["id"] for card in cards} == {card.id for card in STARTER_CARDS}

    ascend_response = client.post("/api/me/collection/test_bruiser/ascend", json={})
    assert ascend_response.status_code == 200
    ascended_cards = ascend_response.json()["cards"]
    bruiser_rows = [card for card in ascended_cards if card["id"] == "test_bruiser"]
    assert any(card["ascension"] == "Возвышенный" and card["copies"] == 1 for card in bruiser_rows)
    assert not any(card["ascension"] == "Дефолт" and card["copies"] == 0 for card in bruiser_rows)

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_google_dev_login() -> None:
    client = TestClient(create_app())
    email = f"google-player-{uuid4().hex}@example.com"
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Google Player"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == email
