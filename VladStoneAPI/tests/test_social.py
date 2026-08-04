"""Friends, directional blocks and direct PvP challenges."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def _player(label: str) -> tuple[TestClient, int, str]:
    client = TestClient(create_app())
    response = client.post(
        "/api/auth/google/dev-login",
        json={"email": f"social-{label}-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 200
    user_id = response.json()["user"]["id"]
    handle = f"S_{label[:10]}_{uuid4().hex[:6]}"
    assert client.put("/api/me/handle", json={"handle": handle}).status_code == 200
    return client, user_id, handle


def test_mutual_friend_requests_create_one_accepted_relationship() -> None:
    first, first_id, first_handle = _player("first")
    second, second_id, second_handle = _player("second")

    request = first.post("/api/social/friend-requests", json={"handle": second_handle})
    assert request.status_code == 201 and request.json()["status"] == "pending"
    reciprocal = second.post("/api/social/friend-requests", json={"handle": first_handle})
    assert reciprocal.status_code == 201 and reciprocal.json()["status"] == "accepted"

    first_social = first.get("/api/social").json()
    second_social = second.get("/api/social").json()
    assert first_social["friends"] == [{"user_id": second_id, "handle": second_handle}]
    assert second_social["friends"] == [{"user_id": first_id, "handle": first_handle}]
    assert first_social["incoming_requests"] == second_social["outgoing_requests"] == []


def test_block_removes_friendship_and_prevents_direct_api_bypass() -> None:
    first, first_id, first_handle = _player("blockfirst")
    second, second_id, second_handle = _player("blocksecond")
    assert (
        first.post("/api/social/friend-requests", json={"handle": second_handle}).status_code == 201
    )
    assert (
        second.post("/api/social/friend-requests", json={"handle": first_handle}).status_code == 201
    )

    assert second.post(f"/api/social/blocks/{first_id}").status_code == 200
    assert second.get("/api/social").json()["friends"] == []
    assert (
        first.post("/api/social/friend-requests", json={"handle": second_handle}).status_code == 403
    )
    assert first.post("/api/social/challenges", json={"user_id": second_id}).status_code == 403
    # Public profile is intentionally not hidden by a block.
    assert first.get(f"/api/profiles/{second_handle}").status_code == 200


def test_accepting_one_friend_challenge_creates_one_shared_match() -> None:
    first, first_id, _ = _player("challengefirst")
    second, second_id, second_handle = _player("challengesecond")
    assert (
        first.post("/api/social/friend-requests", json={"handle": second_handle}).status_code == 201
    )
    assert second.post(f"/api/social/friend-requests/{first_id}/accept").status_code == 200

    sent = first.post("/api/social/challenges", json={"user_id": second_id})
    assert sent.status_code == 201
    challenge_id = sent.json()["id"]
    reciprocal = second.post("/api/social/challenges", json={"user_id": first_id})
    assert reciprocal.status_code == 201
    assert reciprocal.json()["id"] == challenge_id
    assert second.get("/api/social").json()["incoming_challenges"][0]["id"] == challenge_id

    accepted = second.post(f"/api/social/challenges/{challenge_id}/accept")
    assert accepted.status_code == 200
    match_id = accepted.json()["match_id"]
    assert match_id
    # A repeated accept is a reliable hand-off, not a second match.
    assert second.post(f"/api/social/challenges/{challenge_id}/accept").json() == {
        "match_id": match_id
    }
    assert [match["id"] for match in first.get("/api/combat/active").json()["matches"]] == [
        match_id
    ]
    assert [match["id"] for match in second.get("/api/combat/active").json()["matches"]] == [
        match_id
    ]
