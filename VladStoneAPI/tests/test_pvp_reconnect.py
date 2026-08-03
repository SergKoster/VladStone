"""PVP-6: reconnect получает viewer-safe старт ленты, а не голый финал."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.api.routes.ws as ws_routes
from app.core.config import get_settings
from app.main import create_app


def _login(client: TestClient, label: str) -> None:
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"resume-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200


def _started_pvp() -> tuple[TestClient, TestClient, str]:
    creator = TestClient(create_app())
    joiner = TestClient(create_app())
    _login(creator, "creator")
    _login(joiner, "joiner")
    created = creator.post("/api/matches/invite")
    assert created.status_code == 201
    match_id = created.json()["match"]["id"]
    token = created.json()["invite"]["share_path"].rsplit("/", 1)[-1]
    assert joiner.post("/api/matches/join", json={"token": token}).status_code == 200
    return creator, joiner, match_id


def _resolve_first_pvp_turn(creator: TestClient, joiner: TestClient, match_id: str) -> dict:
    assert creator.post(
        "/api/combat/ready",
        json={"match_id": match_id, "turn": 1, "ready": True},
    ).status_code == 200
    assert joiner.post(
        "/api/combat/ready",
        json={"match_id": match_id, "turn": 1, "ready": True},
    ).status_code == 200
    response = creator.get(f"/api/combat/{match_id}")
    assert response.status_code == 200
    return response.json()


def test_pvp_reconnect_payload_replays_from_viewer_safe_turn_start() -> None:
    creator, joiner, match_id = _started_pvp()
    payload = _resolve_first_pvp_turn(creator, joiner, match_id)

    assert payload["resolved_turn"] == 1
    assert payload["match"]["turn"] == 2
    assert payload["events"]
    resume = payload["resume"]
    assert resume is not None
    assert resume["resume_from_sequence"] == 0
    assert resume["match"]["turn"] == 1
    assert resume["match"]["status"] == "planning"
    # Resume никогда не раскрывает руку соперника: это отдельный viewer-safe
    # payload начала хода, а не сырой JSON state из БД.
    own = next(player for player in resume["match"]["players"] if player["id"] == "p1")
    enemy = next(player for player in resume["match"]["players"] if player["id"] == "p2")
    assert own["hand"]
    assert enemy["hand"] == []


def test_pvp_websocket_clamps_resume_cursor_to_last_resolved_turn() -> None:
    creator, joiner, match_id = _started_pvp()
    payload = _resolve_first_pvp_turn(creator, joiner, match_id)
    last_sequence = payload["last_sequence"]
    assert isinstance(last_sequence, int) and last_sequence > 1

    with creator.websocket_connect(
        f"/ws/matches/{match_id}?resume_turn=1&resume_from_sequence=2"
    ) as socket:
        snapshot = socket.receive_json()
    assert snapshot["type"] == "match.snapshot"
    assert snapshot["resume"]["resume_from_sequence"] == 2
    assert snapshot["events"] == payload["events"]

    # Курсор другого turn не может пропустить события текущей сохранённой ленты.
    with creator.websocket_connect(
        f"/ws/matches/{match_id}?resume_turn=99&resume_from_sequence={last_sequence}"
    ) as socket:
        stale_snapshot = socket.receive_json()
    assert stale_snapshot["resume"]["resume_from_sequence"] == 0


def test_pvp_websocket_rejects_unknown_origin_outside_local(monkeypatch) -> None:
    creator, _joiner, match_id = _started_pvp()
    production_settings = get_settings().model_copy(
        update={
            "environment": "production",
            "cors_origins": ["https://vladstone.example"],
        }
    )
    monkeypatch.setattr(ws_routes, "get_settings", lambda: production_settings)

    with pytest.raises(WebSocketDisconnect):
        with creator.websocket_connect(
            f"/ws/matches/{match_id}",
            headers={"origin": "https://attacker.example"},
        ):
            pass
