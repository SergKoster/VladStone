from fastapi.testclient import TestClient

from app.main import create_app


def test_client_telemetry_event_is_accepted() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/telemetry/client-events",
        json={
            "event": "battle_test_event",
            "payload": {"turn": 1, "units": []},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
