"""Regression coverage for the one-active-match account invariant."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import CombatMatchRecord
from app.db.session import SessionLocal
from app.main import create_app


def _login(client: TestClient, label: str) -> str:
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"admission-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200
    token = client.cookies.get("refresh_token")
    assert token is not None
    return token


def _active_match_id(response) -> str:
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_match_exists"
    return detail["current_match_id"]


def test_second_pve_start_returns_current_match_and_active_list_has_one_row() -> None:
    client = TestClient(create_app())
    _login(client, "pve")

    first = client.post("/api/combat/start")
    assert first.status_code == 200
    match_id = first.json()["match"]["id"]

    assert _active_match_id(client.post("/api/combat/start")) == match_id
    active = client.get("/api/combat/active").json()["matches"]
    assert [match["id"] for match in active] == [match_id]


def test_pve_and_invite_share_slot_and_surrender_releases_it() -> None:
    client = TestClient(create_app())
    _login(client, "cross-mode")

    pve = client.post("/api/combat/start").json()["match"]
    assert _active_match_id(client.post("/api/matches/invite")) == pve["id"]

    assert client.post(f"/api/combat/{pve['id']}/surrender").status_code == 200
    invite = client.post("/api/matches/invite")
    assert invite.status_code == 201
    assert invite.json()["match"]["status"] == "waiting_for_opponent"


def test_invite_joiner_with_pve_is_redirected_to_its_current_match() -> None:
    creator = TestClient(create_app())
    joiner = TestClient(create_app())
    _login(creator, "creator")
    _login(joiner, "joiner")

    invite = creator.post("/api/matches/invite").json()
    token = invite["invite"]["share_path"].rsplit("/", 1)[-1]
    pve = joiner.post("/api/combat/start").json()["match"]

    assert _active_match_id(joiner.post("/api/matches/join", json={"token": token})) == pve["id"]
    assert joiner.post(f"/api/combat/{pve['id']}/surrender").status_code == 200
    assert joiner.post("/api/matches/join", json={"token": token}).status_code == 200


def test_stale_slot_is_expired_and_replaced_by_new_pve() -> None:
    client = TestClient(create_app())
    _login(client, "stale")
    first = client.post("/api/combat/start").json()["match"]
    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, first["id"])
        assert record is not None
        record.updated_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()

    replacement = client.post("/api/combat/start")
    assert replacement.status_code == 200
    assert replacement.json()["match"]["id"] != first["id"]
    with SessionLocal() as db:
        stale = db.get(CombatMatchRecord, first["id"])
        assert stale is not None and stale.status == "expired"
