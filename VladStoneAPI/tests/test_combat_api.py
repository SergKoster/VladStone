from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditLog, CombatMatchRecord
from app.db.session import SessionLocal
from app.domain.combat.cards import DECK_CARD_IDS
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.models import MatchLifecycleStatus, Position
from app.domain.combat.rules import RANGER_CARD, create_player_match, create_unit
from app.main import create_app
from app.services.combat_matches import (
    RULESET_EXPIRED_MESSAGE,
    create_combat_match_record,
    load_match,
)
from app.services.combat_turn_timers import resolve_expired_planning_matches


def test_card_catalog_matches_combat_stats() -> None:
    client = TestClient(create_app())

    response = client.get("/api/combat/catalog")
    assert response.status_code == 200

    cards = {card["id"]: card for card in response.json()["cards"]}
    ranger = cards["test_ranger"]
    assert ranger["hp"] == RANGER_CARD.stats.hp
    assert ranger["damage"] == RANGER_CARD.stats.damage
    assert ranger["range"] == RANGER_CARD.stats.attack_range
    assert ranger["cost"] == RANGER_CARD.cost
    assert ranger["ascension"] == "Дефолт"


def test_start_and_resolve_combat_turn() -> None:
    client = TestClient(create_app())

    start_response = client.post("/api/combat/start")
    assert start_response.status_code == 200
    match = start_response.json()["match"]
    assert match["turn"] == 1
    assert match["status"] == "planning"
    # The payload names the seat it was serialized for.
    viewer = next(p for p in match["players"] if p["id"] == match["viewer_id"])
    opponent = next(p for p in match["players"] if p["id"] != match["viewer_id"])
    assert not viewer["is_bot"]
    assert viewer["team"] != opponent["team"]
    # Deck cycle: hand of 3 dealt from the shuffled deck, order kept secret.
    assert len(viewer["hand"]) == 3
    assert viewer["deck_count"] == len(DECK_CARD_IDS) - 3
    # Anti-cheat: deck contents never serialize; a hand only goes to its owner.
    for player_payload in match["players"]:
        assert "deck" not in player_payload
        assert "user_id" not in player_payload
    assert opponent["hand"] == []

    get_response = client.get(f"/api/combat/{match['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["match"]["id"] == match["id"]

    # Playing a card that is not in hand is rejected.
    off_hand = next(
        card_id
        for card_id in ["banka", "test_ranger", "test_bruiser", "dolbiki"]
        if card_id not in viewer["hand"]
    )
    rejected = client.post(
        "/api/combat/resolve",
        json={
            "match_id": match["id"],
            "turn": match["turn"],
            "placements": [{"card_id": off_hand, "row": 4, "col": 1}],
        },
    )
    assert rejected.status_code == 409

    # Play the cheapest card actually in hand (starting mana is 2).
    cards_by_id = {
        card["id"]: card for card in client.get("/api/combat/catalog").json()["cards"]
    }
    playable = min(viewer["hand"], key=lambda card_id: cards_by_id[card_id]["cost"])
    placements = (
        [{"card_id": playable, "row": 4, "col": 1}]
        if cards_by_id[playable]["cost"] <= 2
        else []
    )
    resolve_response = client.post(
        "/api/combat/resolve",
        json={"match_id": match["id"], "turn": match["turn"], "placements": placements},
    )
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()["match"]
    assert resolved["turn"] == 2
    assert resolved["status"] == "planning"
    # Every played card ends up as a unit on the board (and in the log).
    if placements:
        assert resolved["units"]
        assert resolved["log"]
    # End of turn draws one card back into the hand.
    resolved_viewer = next(p for p in resolved["players"] if p["id"] == resolved["viewer_id"])
    expected_hand = 3 - len(placements) + 1
    assert len(resolved_viewer["hand"]) == expected_hand
    assert resolved_viewer["hand_count"] == expected_hand
    assert resolved_viewer["deck_count"] == len(DECK_CARD_IDS) - 4

    stale_response = client.post(
        "/api/combat/resolve",
        json={"match_id": match["id"], "turn": match["turn"], "placements": []},
    )
    assert stale_response.status_code == 409


def test_finished_combat_claims_reward_once_for_authenticated_user() -> None:
    client = TestClient(create_app())
    email = "combat-reward@example.com"
    login_response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Reward Player"},
    )
    assert login_response.status_code == 200
    user_id = login_response.json()["user"]["id"]
    before = client.get("/api/me").json()["coins"]

    match = create_player_match(user_id=user_id)
    player = next(candidate for candidate in match.players if not candidate.is_bot)
    bot = next(candidate for candidate in match.players if candidate.is_bot)
    player.hero.hp = 1
    match.units = [
        create_unit(
            unit_id="bot_ranger_at_hero",
            owner_id=bot.id,
            side=bot.side,
            card=RANGER_CARD,
            position=Position(row=4, col=0),
        )
    ]
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=user_id)
        db.commit()

    payload = {"match_id": match.id, "turn": match.turn, "placements": []}

    first_response = client.post("/api/combat/resolve", json=payload)
    assert first_response.status_code == 200
    resolved = first_response.json()["match"]
    assert resolved["status"] == "finished"
    assert resolved["result"]["status"] == "finished"
    assert client.get("/api/me").json()["coins"] == before + 1

    second_response = client.post("/api/combat/resolve", json=payload)
    assert second_response.status_code == 409
    assert client.get("/api/me").json()["coins"] == before + 1

    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.user_id == user_id)
                .where(AuditLog.action.in_(
                    [
                        "combat.turn_resolved",
                        "combat.match_finished",
                        "combat.reward_claimed",
                    ]
                ))
            )
        )
    assert "combat.turn_resolved" in actions
    assert "combat.match_finished" in actions
    assert "combat.reward_claimed" in actions


def test_authenticated_player_can_list_active_combat_matches() -> None:
    client = TestClient(create_app())
    email = f"active-combat-{uuid4().hex}@example.com"
    login_response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Active Player"},
    )
    assert login_response.status_code == 200

    assert client.get("/api/combat/active").json()["matches"] == []

    start_response = client.post("/api/combat/start")
    assert start_response.status_code == 200
    started = start_response.json()["match"]

    active_response = client.get("/api/combat/active")
    assert active_response.status_code == 200
    matches = active_response.json()["matches"]
    assert [match["id"] for match in matches] == [started["id"]]

    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.action == "combat.match_started")
            )
        )
    assert actions


def test_match_websocket_receives_snapshot_ping_and_updates() -> None:
    client = TestClient(create_app())
    email = f"ws-combat-{uuid4().hex}@example.com"
    login_response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Realtime Player"},
    )
    assert login_response.status_code == 200

    start_response = client.post("/api/combat/start")
    assert start_response.status_code == 200
    started = start_response.json()["match"]

    with client.websocket_connect(f"/ws/matches/{started['id']}") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "match.snapshot"
        assert snapshot["match"]["id"] == started["id"]
        assert snapshot["events"] == []

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

        resolve_response = client.post(
            "/api/combat/resolve",
            json={"match_id": started["id"], "turn": started["turn"], "placements": []},
        )
        assert resolve_response.status_code == 200

        update = websocket.receive_json()
        assert update["type"] == "match.updated"
        assert update["match"]["id"] == started["id"]
        assert update["match"]["turn"] == 2

        # Turn 2: the bot has saved 3 mana and spawns its bruiser — the update
        # must carry the spawn events for animation.
        second_resolve = client.post(
            "/api/combat/resolve",
            json={"match_id": started["id"], "turn": 2, "placements": []},
        )
        assert second_resolve.status_code == 200
        second_update = websocket.receive_json()
        assert second_update["type"] == "match.updated"
        assert second_update["match"]["turn"] == 3
        assert second_update["events"]


def test_late_combat_actions_are_rejected_after_server_deadline() -> None:
    client = TestClient(create_app())
    match = create_player_match(now=datetime.now(UTC) - timedelta(minutes=1))
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        db.commit()

    late_response = client.post(
        "/api/combat/resolve",
        json={
            "match_id": match.id,
            "turn": match.turn,
            "placements": [{"card_id": "test_ranger", "row": 4, "col": 1}],
        },
    )

    assert late_response.status_code == 409
    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        resolved = load_match(record)
    human_id = next(player.id for player in resolved.players if not player.is_bot)
    assert resolved.turn == 2
    assert all(unit.owner_id != human_id for unit in resolved.units)
    assert resolved.planning_deadline is not None


def test_expired_planning_matches_can_be_resolved_without_client_request() -> None:
    match = create_player_match(now=datetime.now(UTC) - timedelta(minutes=1))
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        resolved_matches = resolve_expired_planning_matches(db)
        db.commit()

    assert match.id in {resolved.id for resolved in resolved_matches}
    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        resolved = load_match(record)
    assert resolved.turn == 2
    assert resolved.status == MatchLifecycleStatus.PLANNING


def test_outdated_ruleset_match_expires_on_get_and_rejects_resolve() -> None:
    client = TestClient(create_app())
    match = create_player_match()
    match.ruleset_version = RULESET_VERSION + 1
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        db.commit()

    get_response = client.get(f"/api/combat/{match.id}")
    assert get_response.status_code == 200
    payload = get_response.json()["match"]
    assert payload["status"] == "expired"
    assert payload["result"]["status"] == "expired"
    assert payload["result"]["winner_id"] is None
    assert any(RULESET_EXPIRED_MESSAGE in entry["message"] for entry in payload["log"])

    resolve_response = client.post(
        "/api/combat/resolve",
        json={"match_id": match.id, "turn": match.turn, "placements": []},
    )
    assert resolve_response.status_code == 409

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        assert record.status == MatchLifecycleStatus.EXPIRED.value
        state = load_match(record)
    # The resolver never ran: still turn 1, no bot units, no reward.
    assert state.turn == 1
    assert state.units == []
    assert state.result.reward_coins == 0


def test_outdated_ruleset_match_is_expired_not_resolved_by_timer_worker() -> None:
    # Deadline already passed — without the gate the worker would resolve it.
    match = create_player_match(now=datetime.now(UTC) - timedelta(minutes=1))
    match.ruleset_version = RULESET_VERSION + 1
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        changed = resolve_expired_planning_matches(db)
        db.commit()

    # The gate reports the state change so the worker broadcasts it to clients.
    assert match.id in {state.id for state in changed}
    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        state = load_match(record)
    assert state.status == MatchLifecycleStatus.EXPIRED
    assert state.result.status == "expired"
    assert state.turn == 1


def test_outdated_ruleset_match_excluded_from_active_list() -> None:
    client = TestClient(create_app())
    email = f"ruleset-gate-{uuid4().hex}@example.com"
    login_response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Gate Player"},
    )
    assert login_response.status_code == 200
    user_id = login_response.json()["user"]["id"]

    match = create_player_match()
    match.ruleset_version = RULESET_VERSION + 1
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=user_id)
        db.commit()

    active_response = client.get("/api/combat/active")
    assert active_response.status_code == 200
    assert active_response.json()["matches"] == []

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        assert record.status == MatchLifecycleStatus.EXPIRED.value
        actions = list(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.action == "combat.match_expired_ruleset"
                )
            )
        )
    assert actions


def test_stale_authenticated_match_expires_before_active_list() -> None:
    client = TestClient(create_app())
    email = f"stale-combat-{uuid4().hex}@example.com"
    login_response = client.post(
        "/api/auth/google/dev-login",
        json={"email": email, "name": "Stale Player"},
    )
    assert login_response.status_code == 200
    user_id = login_response.json()["user"]["id"]

    match = create_player_match()
    with SessionLocal() as db:
        record = create_combat_match_record(db, match=match, owner_user_id=user_id)
        record.updated_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()

    active_response = client.get("/api/combat/active")
    assert active_response.status_code == 200
    assert active_response.json()["matches"] == []

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match.id)
        assert record is not None
        assert record.status == MatchLifecycleStatus.EXPIRED.value
        assert load_match(record).status == MatchLifecycleStatus.EXPIRED
