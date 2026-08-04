"""Public handle onboarding, reservation, redirects and privacy."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def _login(client: TestClient, label: str) -> None:
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"profile-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200


def test_handle_onboarding_public_profile_and_battle_names() -> None:
    owner = TestClient(create_app())
    _login(owner, "owner")

    before = owner.get("/api/me").json()
    assert before["onboarding_required"] is True
    assert before["handle"] is None
    assert owner.put("/api/me/handle", json={"handle": "bad handle"}).status_code == 422

    selected = owner.put("/api/me/handle", json={"handle": "Stone_Player"})
    assert selected.status_code == 200
    assert selected.json()["handle"] == "Stone_Player"
    assert selected.json()["onboarding_required"] is False

    public = TestClient(create_app()).get("/api/profiles/Stone_Player")
    assert public.status_code == 200
    assert public.json()["handle"] == "Stone_Player"
    assert public.json()["collection"]["owned"] > 0
    assert "email" not in public.json()
    assert "coins" not in public.json()

    battle = owner.post("/api/combat/start")
    assert battle.status_code == 200
    names = {player["display_name"] for player in battle.json()["match"]["players"]}
    assert names == {"Stone_Player", "Бот"}


def test_handles_are_case_insensitive_and_history_redirects_to_canonical() -> None:
    owner = TestClient(create_app())
    other = TestClient(create_app())
    _login(owner, "history-owner")
    _login(other, "history-other")

    assert owner.put("/api/me/handle", json={"handle": "First_Name"}).status_code == 200
    assert other.put("/api/me/handle", json={"handle": "first_name"}).status_code == 409

    renamed = owner.put("/api/me/handle", json={"handle": "Second_Name"})
    assert renamed.status_code == 200
    old = owner.get("/api/profiles/First_Name", follow_redirects=False)
    assert old.status_code == 308
    assert old.headers["location"] == "/api/profiles/Second_Name"
    assert owner.get("/api/profiles/first_name").json()["handle"] == "Second_Name"
    assert other.put("/api/me/handle", json={"handle": "FIRST_NAME"}).status_code == 409

    case_only = owner.put("/api/me/handle", json={"handle": "second_name"})
    assert case_only.status_code == 200
    assert case_only.json()["handle"] == "second_name"
