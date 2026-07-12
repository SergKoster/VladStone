"""Гонка резолва матча: оптимистическая блокировка (ARCHITECTURE §8.6).

Сценарий гонки: роут /combat/resolve и фоновый таймер-воркер одновременно
резолвят один матч. Победить должен ровно один; второй обязан получить отказ,
а не молча затереть чужой результат.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch, raises
from sqlalchemy import text
from sqlalchemy.orm.exc import StaleDataError

from app.api.routes import combat as combat_routes
from app.db.models import CombatMatchRecord
from app.db.session import SessionLocal
from app.domain.combat.engine.battle import create_v4_battle, resolve_v4_turn
from app.main import create_app
from app.services.combat_matches import (
    create_combat_match_record,
    load_v4_battle,
    save_v4_battle,
)


def test_second_writer_gets_stale_data_error_and_first_result_survives() -> None:
    create_app()
    match = create_v4_battle(match_id=f"local_pve_{uuid4().hex}")
    with SessionLocal() as first, SessionLocal() as second:
        record_first = create_combat_match_record(first, match=match, owner_user_id=None)
        first.commit()
        record_second = second.get(CombatMatchRecord, match.id)

        winner_state = load_v4_battle(record_first)
        winner_state.turn += 1
        save_v4_battle(record_first, winner_state)
        first.commit()

        loser_state = load_v4_battle(record_second)
        loser_state.turn += 100
        save_v4_battle(record_second, loser_state)
        with raises(StaleDataError):
            second.commit()
        second.rollback()

    with SessionLocal() as check:
        stored = load_v4_battle(check.get(CombatMatchRecord, match.id))
        assert stored.turn == winner_state.turn


def test_resolve_route_returns_409_when_competitor_wins_midflight(
    monkeypatch: MonkeyPatch,
) -> None:
    client = TestClient(create_app())
    start = client.post("/api/combat/start")
    assert start.status_code == 200
    match_payload = start.json()["match"]

    def resolve_with_competitor(state, **kwargs):
        # Пока запрос считает ход, «таймер-воркер» успевает сохранить матч:
        # версия записи в БД уходит вперёд загруженной в этом запросе.
        with SessionLocal() as competitor:
            competitor.execute(
                text("UPDATE combat_matches SET version = version + 1 WHERE id = :id"),
                {"id": state.id},
            )
            competitor.commit()
        return resolve_v4_turn(state, **kwargs)

    monkeypatch.setattr(combat_routes, "resolve_v4_turn", resolve_with_competitor)

    response = client.post(
        "/api/combat/resolve",
        json={"match_id": match_payload["id"], "turn": match_payload["turn"], "placements": []},
    )

    assert response.status_code == 409
    assert "already resolved" in response.json()["detail"]
