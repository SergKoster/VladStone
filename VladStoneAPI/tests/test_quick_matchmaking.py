"""FIFO quick-match queue, reliable transfer and active-slot integration."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import QuickMatchmakingEntry
from app.db.session import SessionLocal
from app.main import create_app


def _login(client: TestClient, label: str) -> int:
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"quick-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200
    return response.json()["user"]["id"]


def test_first_two_quick_players_receive_one_shared_match_and_transfer_id() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    _login(first, "first")
    _login(second, "second")

    assert first.post("/api/matchmaking/quick").json() == {"status": "waiting", "match_id": None}
    second_result = second.post("/api/matchmaking/quick")
    assert second_result.status_code == 200
    match_id = second_result.json()["match_id"]
    assert second_result.json()["status"] == "matched" and match_id

    assert first.get("/api/matchmaking/quick").json() == {
        "status": "matched",
        "match_id": match_id,
    }
    first_active = first.get("/api/combat/active").json()["matches"]
    second_active = second.get("/api/combat/active").json()["matches"]
    assert [match["id"] for match in first_active] == [match_id]
    assert [match["id"] for match in second_active] == [match_id]


def test_cancel_waiting_entry_prevents_future_match() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    _login(first, "cancel-first")
    _login(second, "cancel-second")

    assert first.post("/api/matchmaking/quick").json()["status"] == "waiting"
    assert first.delete("/api/matchmaking/quick").json() == {"status": "idle", "match_id": None}
    assert second.post("/api/matchmaking/quick").json() == {"status": "waiting", "match_id": None}
    assert second.delete("/api/matchmaking/quick").json() == {"status": "idle", "match_id": None}


def test_cancel_after_matching_returns_match_instead_of_losing_transfer() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    _login(first, "transfer-first")
    _login(second, "transfer-second")

    assert first.post("/api/matchmaking/quick").json()["status"] == "waiting"
    matched = second.post("/api/matchmaking/quick").json()
    assert first.delete("/api/matchmaking/quick").json() == matched


def test_pve_admission_removes_waiting_entry_and_active_match_wins() -> None:
    client = TestClient(create_app())
    user_id = _login(client, "pve")
    assert client.post("/api/matchmaking/quick").json()["status"] == "waiting"

    pve = client.post("/api/combat/start").json()["match"]
    assert client.get("/api/matchmaking/quick").json() == {"status": "idle", "match_id": None}
    assert client.post("/api/matchmaking/quick").json() == {
        "status": "matched",
        "match_id": pve["id"],
    }
    with SessionLocal() as db:
        assert db.get(QuickMatchmakingEntry, user_id) is None
