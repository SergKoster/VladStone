from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_external_combat_start_requires_a_session(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")

    response = TestClient(create_app()).post("/api/combat/start")

    assert response.status_code == 401


def test_combat_rejects_oversized_intent_lists() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/combat/resolve",
        json={
            "match_id": "any",
            "turn": 1,
            "placements": [
                {"card_id": "test_bruiser", "row": 4, "col": 0} for _ in range(7)
            ],
        },
    )

    assert response.status_code == 422
