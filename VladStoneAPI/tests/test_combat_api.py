"""HTTP-слой боя v4 (этап 15в): старт, резолв, каталог, WS, гейт, награда."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AuditLog, CombatMatchRecord
from app.db.session import SessionLocal
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.engine.battle import BattleStateV4, build_context, create_v4_battle
from app.domain.combat.engine.content import DECK_CARD_IDS_V4
from app.domain.combat.engine.payload import v4_combat_response
from app.domain.combat.engine.towers import towers_of
from app.domain.combat.models import MatchLifecycleStatus
from app.main import create_app
from app.services.combat_matches import (
    RULESET_EXPIRED_MESSAGE,
    create_combat_match_record,
    load_v4_battle,
    save_v4_battle,
)
from app.services.combat_turn_timers import (
    resolve_expired_planning_match,
    resolve_expired_planning_matches,
)


def test_card_catalog_is_v4_content() -> None:
    client = TestClient(create_app())
    response = client.get("/api/combat/catalog")
    assert response.status_code == 200
    payload = response.json()
    cards = {card["id"]: card for card in payload["cards"]}
    # 12 карт §14.1, все обычные, юниты несут покрытия и зону спавна.
    assert len(cards) == 12
    assert all(card["rarity"] == "common" for card in cards.values())
    bruiser = cards["test_bruiser"]
    assert bruiser["card_type"] == "unit"
    assert bruiser["stats"]["hp"] == 4 and bruiser["stats"]["damage"] == 2
    assert bruiser["board"] == {"rows": 5, "cols": 5}
    assert bruiser["rules_text"] == "Обычный боец без особой способности."
    assert cards["banka"]["card_type"] == "spell"
    statuses = {status["id"]: status for status in payload["statuses"]}
    assert statuses["poison"] == {
        "id": "poison",
        "name": "Яд",
        "description": "В конце хода носитель получает 1 урон и теряет 1 стак.",
        "icon": "poison",
        "decay": "stacks",
    }
    assert set(statuses) == {"poison", "forced_stance", "zadanie_mark"}


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

@pytest.mark.skip(reason="flaky: рандомная рука без seed, чинить в гл.12 (TODO.md)")
def test_streamed_plan_is_applied_on_deadline_resolve() -> None:
    """V3: дедлайн резолвит ПОСЛЕДНИЙ присланный план, а не пустой ход."""
    client = TestClient(create_app())
    match = client.post("/api/combat/start").json()["match"]
    viewer = next(p for p in match["players"] if p["id"] == match["viewer_id"])
    catalog = {c["id"]: c for c in client.get("/api/combat/catalog").json()["cards"]}
    unit = next(
        cid for cid in viewer["hand"]
        if catalog[cid]["card_type"] == "unit" and catalog[cid]["cost"] <= 2
    )
    plan = client.post(
        "/api/combat/plan",
        json={
            "match_id": match["id"],
            "turn": 1,
            "placements": [{"card_id": unit, "row": 4, "col": 2}],
        },
    )
    assert plan.status_code == 200 and plan.json()["ok"] is True

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match["id"])
        state = load_v4_battle(record)
        assert state.pending_plans  # план сохранён в состоянии матча
        resolved = resolve_expired_planning_match(
            db, record, now=state.planning_deadline + timedelta(seconds=1)
        )
        assert resolved is not None
        db.commit()
    spawned = [
        e for e in resolved.events if e.kind == "spawned" and e.card_id == unit
    ]
    assert spawned, "юнит из сохранённого плана обязан быть поставлен"
    # Планы и готовность живут в рамках одного хода.
    assert resolved.state.pending_plans == {}
    assert resolved.state.ready_player_ids == []


def test_ready_resolves_early_after_bot_delay() -> None:
    """V3: бот «жмёт Готов» через 2 с после игрока — потом ранний резолв."""
    client = TestClient(create_app())
    match = client.post("/api/combat/start").json()["match"]
    ready = client.post(
        "/api/combat/ready",
        json={"match_id": match["id"], "turn": 1, "ready": True},
    )
    assert ready.status_code == 200 and ready.json()["ready"] is True

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match["id"])
        state = load_v4_battle(record)
        assert state.ready_since is not None
        ready_since = state.ready_since
        # Внутри окна отмены раннего резолва нет.
        assert (
            resolve_expired_planning_match(
                db, record, now=ready_since + timedelta(seconds=1)
            )
            is None
        )
        # Окно истекло — ход резолвится задолго до дедлайна.
        resolved = resolve_expired_planning_match(
            db, record, now=ready_since + timedelta(seconds=3)
        )
        assert resolved is not None and resolved.resolved_turn == 1
        db.commit()


def test_timer_tick_survives_unreadable_state_and_expires_it() -> None:
    """V3-фикс: запись с нечитаемым state гасится, не убивая тик воркера.

    Реальный кейс из дев-БД: MVP-форма состояния, ошибочно сохранённая с
    ТЕКУЩИМ ruleset_version в переходном окне подмены движка. Она проходит
    version-гейт, а её парс раньше молча убивал корутину воркера — таймеры
    всех матчей вставали.
    """
    client = TestClient(create_app())
    match = client.post("/api/combat/start").json()["match"]  # здоровый сосед
    broken_id = f"local_pve_{uuid4().hex}"
    with SessionLocal() as db:
        db.add(
            CombatMatchRecord(
                id=broken_id,
                owner_user_id=None,
                status="planning",
                state_json=json.dumps(
                    {
                        "id": broken_id,
                        "ruleset_version": RULESET_VERSION,
                        "status": "planning",
                        "units": [
                            {
                                "id": "bot_ranger",
                                "card_id": "test_ranger",
                                "owner_id": "bot",
                                "position": {"row": 1, "col": 0},
                                "current_hp": 1,
                            }
                        ],
                    }
                ),
            )
        )
        db.commit()

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match["id"])
        deadline = load_v4_battle(record).planning_deadline
        resolved = resolve_expired_planning_matches(
            db, now=deadline + timedelta(seconds=1)
        )
        # Тик пережил битую запись и дорезолвил здорового соседа.
        assert any(r.state.id == match["id"] for r in resolved)
        broken = db.get(CombatMatchRecord, broken_id)
        assert broken.status == "expired"
        raw = json.loads(broken.state_json)
        assert raw["status"] == "expired"
        assert raw["result"]["status"] == "expired"


def test_unready_within_window_cancels_early_resolve() -> None:
    """V3: снятие готовности в окне 2 с — бот тоже «не жмёт», резолва нет."""
    client = TestClient(create_app())
    match = client.post("/api/combat/start").json()["match"]
    client.post(
        "/api/combat/ready", json={"match_id": match["id"], "turn": 1, "ready": True}
    )
    unready = client.post(
        "/api/combat/ready", json={"match_id": match["id"], "turn": 1, "ready": False}
    )
    assert unready.status_code == 200 and unready.json()["ready"] is False

    with SessionLocal() as db:
        record = db.get(CombatMatchRecord, match["id"])
        state = load_v4_battle(record)
        assert state.ready_since is None and state.ready_player_ids == []
        # Далеко за окном, но до дедлайна — резолва нет.
        assert (
            resolve_expired_planning_match(
                db, record, now=datetime.now(UTC) + timedelta(seconds=10)
            )
            is None
        )


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
        http_payload = resolve.json()
        update = ws.receive_json()
        assert update["type"] == "match.updated" and update["match"]["turn"] == 2
        assert update["resolved_turn"] == http_payload["resolved_turn"] == 1
        assert update["last_sequence"] == http_payload["last_sequence"]
        assert update["events"] == http_payload["events"]
        assert update["events"]
        lazy = client.get(f"/api/combat/{started['id']}").json()
        assert lazy["resolved_turn"] == 1
        assert lazy["events"] == http_payload["events"]


def test_deadline_resolves_by_timer_without_client() -> None:
    match = create_v4_battle(
        match_id=f"local_pve_{uuid4().hex}", now=datetime.now(UTC) - timedelta(minutes=1)
    )
    with SessionLocal() as db:
        create_combat_match_record(db, match=match, owner_user_id=None)
        resolved = resolve_expired_planning_matches(db)
        db.commit()
    assert match.id in {result.state.id for result in resolved}
    result = next(result for result in resolved if result.state.id == match.id)
    assert result.resolved_turn == 1
    assert result.events
    payload = v4_combat_response(
        result.state,
        events=result.events,
        resolved_turn=result.resolved_turn,
    )
    assert payload["resolved_turn"] == 1
    assert payload["last_sequence"] == payload["events"][-1]["sequence"]
    with SessionLocal() as db:
        state = load_v4_battle(db.get(CombatMatchRecord, match.id))
    assert state.turn == 2 and state.status == MatchLifecycleStatus.PLANNING


def test_deadline_409_keeps_full_replay_in_websocket_update() -> None:
    client = TestClient(create_app())
    started = client.post("/api/combat/start").json()["match"]

    with client.websocket_connect(f"/ws/matches/{started['id']}") as ws:
        assert ws.receive_json()["type"] == "match.snapshot"
        with SessionLocal() as db:
            record = db.get(CombatMatchRecord, started["id"])
            state = load_v4_battle(record)
            state.planning_deadline = datetime.now(UTC) - timedelta(seconds=1)
            save_v4_battle(record, state)
            db.commit()

        response = client.post(
            "/api/combat/resolve",
            json={"match_id": started["id"], "turn": 1, "placements": []},
        )
        assert response.status_code == 409
        update = ws.receive_json()
        assert update["type"] == "match.updated"
        assert update["resolved_turn"] == 1
        assert update["match"]["turn"] == 2
        assert update["events"]
        assert update["last_sequence"] == update["events"][-1]["sequence"]


def test_evil_dolbiki_and_following_turn_both_broadcast_replay() -> None:
    client = TestClient(create_app())
    state = create_v4_battle(match_id=f"local_pve_{uuid4().hex}")
    human = next(player for player in state.players if not player.is_bot)
    bot = next(player for player in state.players if player.is_bot)
    human.hand = ["evil_dolbiki"]
    human.mana = state.mana_cap
    bot.hand = []
    bot.deck = []
    with SessionLocal() as db:
        create_combat_match_record(db, match=state, owner_user_id=None)
        db.commit()

    with client.websocket_connect(f"/ws/matches/{state.id}") as ws:
        assert ws.receive_json()["type"] == "match.snapshot"
        first = client.post(
            "/api/combat/resolve",
            json={
                "match_id": state.id,
                "turn": 1,
                "placements": [{"card_id": "evil_dolbiki", "row": 4, "col": 2}],
            },
        )
        assert first.status_code == 200
        first_update = ws.receive_json()
        assert first_update["resolved_turn"] == 1
        assert first_update["events"] == first.json()["events"]
        assert {event["type"] for event in first_update["events"]} >= {
            "spawn",
            "ability_triggered",
        }

        second = client.post(
            "/api/combat/resolve",
            json={"match_id": state.id, "turn": 2, "placements": []},
        )
        assert second.status_code == 200
        second_update = ws.receive_json()
        assert second_update["resolved_turn"] == 2
        assert second_update["events"] == second.json()["events"]
        assert second_update["events"]


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
