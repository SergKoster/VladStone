from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.routes.combat as combat_routes
from app.core.config import get_settings
from app.db.models import CombatMatchRecord
from app.db.session import SessionLocal
from app.main import create_app
from app.services.combat_matches import load_v4_battle


def _login(client: TestClient, label: str) -> str:
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"pvp-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200
    token = client.cookies.get("refresh_token")
    assert token is not None
    return token


def test_invite_joins_two_seats_and_keeps_hands_viewer_safe() -> None:
    client = TestClient(create_app())
    creator_cookie = _login(client, "creator")
    joiner_cookie = _login(client, "joiner")

    created = client.post("/api/matches/invite", cookies={"refresh_token": creator_cookie})
    assert created.status_code == 201
    lobby = created.json()["match"]
    assert lobby["status"] == "waiting_for_opponent"
    assert lobby["planning_deadline"] is None
    token = created.json()["invite"]["share_path"].rsplit("/", 1)[-1]

    assert (
        client.post(
            "/api/matches/join",
            json={"token": token},
            cookies={"refresh_token": creator_cookie},
        )
        .status_code
        == 409
    )
    joined = client.post(
        "/api/matches/join",
        json={"token": token},
        cookies={"refresh_token": joiner_cookie},
    )
    assert joined.status_code == 200
    joiner_match = joined.json()["match"]
    assert joiner_match["status"] == "planning"
    assert joiner_match["viewer_id"] == "p2"
    assert next(p for p in joiner_match["players"] if p["id"] == "p2")["hand"]
    assert next(p for p in joiner_match["players"] if p["id"] == "p1")["hand"] == []

    creator_match = client.get(
        f"/api/combat/{lobby['id']}", cookies={"refresh_token": creator_cookie}
    )
    assert creator_match.status_code == 200
    creator_payload = creator_match.json()["match"]
    assert creator_payload["viewer_id"] == "p1"
    assert next(p for p in creator_payload["players"] if p["id"] == "p1")["hand"]
    assert next(p for p in creator_payload["players"] if p["id"] == "p2")["hand"] == []

    intruder_cookie = _login(client, "intruder")
    assert (
        client.get(f"/api/combat/{lobby['id']}", cookies={"refresh_token": intruder_cookie})
        .status_code
        == 403
    )

    with SessionLocal() as db:
        state = load_v4_battle(db.get(CombatMatchRecord, lobby["id"]))
        assert {player.user_id for player in state.players if not player.is_bot}
        assert len(state.units) == 10


def test_pvp_ready_resolves_only_when_both_players_confirm() -> None:
    client = TestClient(create_app())
    creator_cookie = _login(client, "ready-creator")
    joiner_cookie = _login(client, "ready-joiner")
    created = client.post("/api/matches/invite", cookies={"refresh_token": creator_cookie})
    token = created.json()["invite"]["share_path"].rsplit("/", 1)[-1]
    match_id = created.json()["match"]["id"]
    assert client.post(
        "/api/matches/join", json={"token": token}, cookies={"refresh_token": joiner_cookie}
    ).status_code == 200

    ready_a = client.post(
        "/api/combat/ready",
        json={"match_id": match_id, "turn": 1, "ready": True},
        cookies={"refresh_token": creator_cookie},
    )
    assert ready_a.status_code == 200
    with SessionLocal() as db:
        state = load_v4_battle(db.get(CombatMatchRecord, match_id))
        assert state.ready_player_ids == ["p1"]
        assert state.ready_since is None

    ready_b = client.post(
        "/api/combat/ready",
        json={"match_id": match_id, "turn": 1, "ready": True},
        cookies={"refresh_token": joiner_cookie},
    )
    assert ready_b.status_code == 200
    resolved = client.get(f"/api/combat/{match_id}", cookies={"refresh_token": joiner_cookie})
    assert resolved.status_code == 200
    assert resolved.json()["match"]["turn"] == 2

    assert (
        client.post(
            "/api/combat/resolve",
            json={"match_id": match_id, "turn": 2},
            cookies={"refresh_token": creator_cookie},
        ).status_code
        == 409
    )


def test_pvp_turn_rate_limit_is_independent_per_authenticated_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app())
    creator_cookie = _login(client, "rate-creator")
    joiner_cookie = _login(client, "rate-joiner")
    created = client.post("/api/matches/invite", cookies={"refresh_token": creator_cookie})
    token = created.json()["invite"]["share_path"].rsplit("/", 1)[-1]
    match_id = created.json()["match"]["id"]
    assert client.post(
        "/api/matches/join",
        json={"token": token},
        cookies={"refresh_token": joiner_cookie},
    ).status_code == 200

    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(combat_routes, "TURN_ACTION_LIMIT", 2)
    payload = {"match_id": match_id, "turn": 1}

    assert client.post(
        "/api/combat/plan",
        json=payload,
        cookies={"refresh_token": creator_cookie},
    ).status_code == 200
    assert client.post(
        "/api/combat/plan",
        json=payload,
        cookies={"refresh_token": creator_cookie},
    ).status_code == 200
    assert client.post(
        "/api/combat/plan",
        json=payload,
        cookies={"refresh_token": creator_cookie},
    ).status_code == 429

    # The joiner has a separate bucket. With the old owner-based key this
    # request incorrectly inherited the creator's exhausted limit.
    assert client.post(
        "/api/combat/plan",
        json=payload,
        cookies={"refresh_token": joiner_cookie},
    ).status_code == 200


def test_pvp_websocket_serializes_each_connection_for_its_viewer() -> None:
    creator = TestClient(create_app())
    joiner = TestClient(create_app())
    _login(creator, "ws-creator")
    _login(joiner, "ws-joiner")
    created = creator.post("/api/matches/invite")
    match_id = created.json()["match"]["id"]
    token = created.json()["invite"]["share_path"].rsplit("/", 1)[-1]
    assert joiner.post("/api/matches/join", json={"token": token}).status_code == 200

    with creator.websocket_connect(f"/ws/matches/{match_id}") as creator_ws:
        with joiner.websocket_connect(f"/ws/matches/{match_id}") as joiner_ws:
            creator_snapshot = creator_ws.receive_json()["match"]
            joiner_snapshot = joiner_ws.receive_json()["match"]

            assert creator_snapshot["viewer_id"] == "p1"
            assert joiner_snapshot["viewer_id"] == "p2"
            assert next(p for p in creator_snapshot["players"] if p["id"] == "p1")["hand"]
            assert next(p for p in creator_snapshot["players"] if p["id"] == "p2")["hand"] == []
            assert next(p for p in joiner_snapshot["players"] if p["id"] == "p2")["hand"]
            assert next(p for p in joiner_snapshot["players"] if p["id"] == "p1")["hand"] == []
