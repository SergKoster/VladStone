from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import CombatMatchRecord
from app.db.session import SessionLocal
from app.main import create_app
from app.services.combat_matches import load_v4_battle, save_v4_battle


def test_reconnect_deadline_resolution_broadcasts_to_existing_socket() -> None:
    client = TestClient(create_app())
    client.post(
        "/api/auth/google/dev-login",
        json={"email": f"ws-reconnect-{uuid4().hex}@example.com"},
    )
    match_id = client.post("/api/combat/start").json()["match"]["id"]

    with client.websocket_connect(f"/ws/matches/{match_id}") as first:
        assert first.receive_json()["type"] == "match.snapshot"
        with SessionLocal() as db:
            record = db.get(CombatMatchRecord, match_id)
            state = load_v4_battle(record)
            state.planning_deadline = datetime.now(UTC) - timedelta(seconds=1)
            save_v4_battle(record, state)
            db.commit()

        with client.websocket_connect(f"/ws/matches/{match_id}") as second:
            update = first.receive_json()
            snapshot = second.receive_json()

        assert update["type"] == "match.updated"
        assert snapshot["type"] == "match.snapshot"
        assert update["resolved_turn"] == snapshot["resolved_turn"] == 1
        assert update["events"] == snapshot["events"]
