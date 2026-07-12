"""HTTP-слой боя v4 (этап 15в): старт, резолв, каталог, WS, гейт, награда."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditLog, CombatMatchRecord
from app.db.session import SessionLocal
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.engine.battle import BattleStateV4, build_context, create_v4_battle
from app.domain.combat.engine.content import DECK_CARD_IDS_V4
from app.domain.combat.engine.towers import towers_of
from app.domain.combat.models import MatchLifecycleStatus
from app.main import create_app
from app.services.combat_matches import (
    RULESET_EXPIRED_MESSAGE,
    create_combat_match_record,
    load_v4_battle,
)
from app.services.combat_turn_timers import resolve_expired_planning_matches


def test_card_catalog_is_v4_content() -> None:
    client = TestClient(create_app())
    response = client.get("/api/combat/catalog")
    assert response.status_code == 200
    cards = {card["id"]: card for card in response.json()["cards"]}
    # 12 карт §14.1, все обычные, юниты несут покрытия и зону спавна.
    assert len(cards) == 12
    assert all(card["rarity"] == "common" for card in cards.values())
    bruiser = cards["test_bruiser"]
    assert bruiser["card_type"] == "unit"
    assert bruiser["stats"]["hp"] == 4 and bruiser["stats"]["damage"] == 2
    assert bruiser["board"] == {"rows": 5, "cols": 5}
    assert cards["banka"]["card_type"] == "spell"


def test_start_serves_a_v4_board_with_towers() -> None:
    client = TestClient(create_app())
    start = client.post("/api/combat/start")
    assert start.status_code == 200
    match = start.json()["match"]
    assert match["turn"] == 1 and match["status"] == "planning"
    assert match["rows"] == 5 and match["cols"] == 5
    viewer = next(p for p in match["players"] if p["id"] == match["viewer_id"])
    opponent = next(p for p in match["players"] if p["id"] != match["viewer_id"])
    assert not viewer["is_bot"] and viewer["team"] != opponent["team"]
    assert len(viewer["hand"]) == 3
    assert viewer["deck_count"] == len(DECK_CARD_IDS_V4) - 3
    assert opponent["hand"] == [] and opponent["hand_count"] == 3
    for player in match["players"]:
        assert "deck" not in player and "user_id" not in player
    # 10 башен на призрачных рядах.
    towers = [u for u in match["units"] if u["is_tower"]]
    assert len(towers) == 10 and {u["row"] for u in towers} == {-1, 5}


def test_resolve_plays_a_card_and_advances_the_turn() -> None:
    client = TestClient(create_app())
    match = client.post("/api/combat/start").json()["match"]
    viewer = next(p for p in match["players"] if p["id"] == match["viewer_id"])
    catalog = {c["id"]: c for c in client.get("/api/combat/catalog").json()["cards"]}
    # Дешёвый юнит из руки, ставим в свой задний ряд (BOTTOM = ряд 4).
    unit = next(
        (cid for cid in viewer["hand"] if catalog[cid]["card_type"] == "unit"
         and catalog[cid]["cost"] <= 2),
        None,
    )
    placements = [{"card_id": unit, "row": 4, "col": 2}] if unit else []
    resolve = client.post(
        "/api/combat/resolve",
        json={"match_id": match["id"], "turn": 1, "placements": placements},
    )
    assert resolve.status_code == 200
    resolved = resolve.json()["match"]
    assert resolved["turn"] == 2 and resolved["status"] == "planning"
    if unit:
        assert any(u["blueprint_id"] == unit and not u["is_tower"] for u in resolved["units"])

    # Тот же ход второй раз — 409 (уже сыгран).
    stale = client.post(
        "/api/combat/resolve",
        json={"match_id": match["id"], "turn": 1, "placements": []},
    )
    assert stale.status_code == 409


def test_finished_v4_match_claims_reward_once() -> None:
    client = TestClient(create_app())
    email = "combat-reward@example.com"
    login = client.post("/api/auth/google/dev-login", json={"email": email, "name": "R"})
    user_id = login.json()["user"]["id"]
    before = client.get("/api/me").json()["coins"]

    # Матч, где у бота нет башен → человек побеждает первым же резолвом.
    state = create_v4_battle(match_id=f"local_pve_{uuid4().hex}", user_id=user_id)
    ctx = build_context(state)
    bot_towers = towers_of(ctx, "p2")
    state.units = [u for u in state.units if u not in bot_towers]
    with SessionLocal() as db:
        create_combat_match_record(db, match=state, owner_user_id=user_id)
        db.commit()

    payload = {"match_id": state.id, "turn": state.turn, "placements": []}
    first = client.post("/api/combat/resolve", json=payload)
    assert first.status_code == 200
    assert first.json()["match"]["result"]["status"] == "finished"
    assert client.get("/api/me").json()["coins"] == before + 5

    second = client.post("/api/combat/resolve", json=payload)
    assert second.status_code == 409  # матч завершён
    assert client.get("/api/me").json()["coins"] == before + 5

    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.user_id == user_id)
                .where(AuditLog.action.in_(["combat.match_finished", "combat.reward_claimed"]))
            )
        )
    assert "combat.match_finished" in actions and "combat.reward_claimed" in actions


def test_active_list_returns_started_match() -> None:
    client = TestClient(create_app())
    email = f"active-{uuid4().hex}@example.com"
    client.post("/api/auth/google/dev-login", json={"email": email, "name": "A"})
    assert client.get("/api/combat/active").json()["matches"] == []
    started = client.post("/api/combat/start").json()["match"]
    matches = client.get("/api/combat/active").json()["matches"]
    assert [m["id"] for m in matches] == [started["id"]]


def test_match_websocket_snapshot_ping_and_update() -> None:
    client = TestClient(create_app())
    email = f"ws-{uuid4().hex}@example.com"
    client.post("/api/auth/google/dev-login", json={"email": email, "name": "W"})
    started = client.post("/api/combat/start").json()["match"]

    with client.websocket_connect(f"/ws/matches/{started['id']}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "match.snapshot"
        assert snapshot["match"]["id"] == started["id"]
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        resolve = client.post(
            "/api/combat/resolve",
            json={"match_id": started["id"], "turn": 1, "placements": []},
        )
        assert resolve.status_code == 200
        update = ws.receive_json()
        assert update["type"] == "match.updated" and update["match"]["turn"] == 2


def test_deadline_resolves_by_timer_without_client() -> None:
    match = create_v4_battle(
        match_id=f"local_pve_{uuid4().hex}", now=datetime.now(UTC) - timedelta(minutes=1)
    )
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        resolved = resolve_expired_planning_matches(db)
        db.commit()
    assert match.id in {state.id for state in resolved}
    with SessionLocal() as db:
        state = load_v4_battle(db.get(CombatMatchRecord, match.id))
    assert state.turn == 2 and state.status == MatchLifecycleStatus.PLANNING


def test_outdated_ruleset_match_expires_on_get_and_rejects_resolve() -> None:
    client = TestClient(create_app())
    match_id = f"local_pve_old_{uuid4().hex}"
    # Запись старого формата (v2 MVP-shape) — гейт обязан погасить её без парса.
    old_state_json = (
        f'{{"id":"{match_id}","ruleset_version":2,"status":"planning","turn":1,'
        '"players":[],"units":[],"result":{"status":"active"}}'
    )
    with SessionLocal() as db:
        db.add(
            CombatMatchRecord(
                id=match_id,
                owner_user_id=None,
                state_json=old_state_json,
                status="planning",
                winner_id=None,
            )
        )
        db.commit()

    get_response = client.get(f"/api/combat/{match_id}")
    assert get_response.status_code == 200
    payload = get_response.json()["match"]
    assert payload["status"] == "expired" and payload["result"]["status"] == "expired"
    assert any(RULESET_EXPIRED_MESSAGE in entry["message"] for entry in payload["log"])

    resolve = client.post(
        "/api/combat/resolve",
        json={"match_id": match_id, "turn": 1, "placements": []},
    )
    assert resolve.status_code == 409
    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match_id)
        assert record.status == MatchLifecycleStatus.EXPIRED.value


def test_ruleset_version_is_three() -> None:
    # Ремап v4 живой — версия поднята, старые матчи гаснут гейтом.
    assert RULESET_VERSION == 3
    state = create_v4_battle(match_id="local_pve_000042")
    assert isinstance(state, BattleStateV4)
    assert state.ruleset_version == 3
