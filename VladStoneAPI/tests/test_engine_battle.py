"""Живой матч v4 (этап 15в): создание, резолв, винкон/суд, payload."""

import random
from datetime import UTC, datetime, timedelta

from app.domain.combat.engine.battle import (
    JUDGEMENT_TURN,
    BattleStateV4,
    create_v4_battle,
    resolve_v4_turn,
)
from app.domain.combat.engine.content import DECK_CARD_IDS_V4
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent
from app.domain.combat.engine.payload import v4_combat_response
from app.domain.combat.engine.towers import towers_of
from app.domain.combat.models import MatchLifecycleStatus
from app.domain.combat.timing import resolution_buffer_seconds, turn_duration_seconds


def make_battle(seed: int = 1) -> BattleStateV4:
    return create_v4_battle(match_id="local_pve_000042", user_id=7, rng=random.Random(seed))


def human_of(state: BattleStateV4):
    return next(p for p in state.players if not p.is_bot)


def test_new_battle_has_towers_hands_and_deterministic_coin() -> None:
    state = make_battle()
    assert state.turn == 1 and state.status == MatchLifecycleStatus.PLANNING
    assert state.planning_deadline is not None
    # 5 башен на игрока = 10 юнитов, стартовые руки по 3 из 12-карточной колоды.
    assert len(state.units) == 10
    for player in state.players:
        assert len(towers_of_state(state, player.id)) == 5
        assert len(player.hand) == 3
        assert len(player.deck) == len(DECK_CARD_IDS_V4) - 3
    # Монетка выводится из id матча — воспроизводима (C1).
    again = create_v4_battle(match_id="local_pve_000042", rng=random.Random(9))
    assert again.spell_coin == state.spell_coin


def towers_of_state(state, player_id):
    from app.domain.combat.engine.battle import build_context

    return towers_of(build_context(state), player_id)


def test_resolve_advances_turn_and_serializes_round_trip() -> None:
    state = make_battle()
    human = human_of(state)
    # Сыграть дешёвого юнита из руки в свою зону спавна.
    playable = next(cid for cid in human.hand if cid in ("test_bruiser", "red_skull", "matesha"))
    events = resolve_v4_turn(
        state,
        human_intents=PlayerIntents(
            player_id=human.id, spawns=(SpawnIntent(card_id=playable, row=4, col=2),)
        ),
    )
    assert state.turn == 2 and state.status == MatchLifecycleStatus.PLANNING
    assert isinstance(events, list)

    # Персистентность: состояние переживает JSON round-trip (запись в БД).
    restored = BattleStateV4.model_validate_json(state.model_dump_json())
    assert restored.turn == 2
    assert len(restored.units) == len(state.units)
    assert restored.spell_coin == state.spell_coin
    assert restored.last_resolved_turn == 1
    assert restored.last_events == events


def test_win_condition_when_all_enemy_towers_gone() -> None:
    state = make_battle()
    from app.domain.combat.engine.battle import build_context

    ctx = build_context(state)
    bot_towers = towers_of(ctx, "p2")
    state.units = [u for u in state.units if u not in bot_towers]  # снесли башни бота
    resolve_v4_turn(state, human_intents=PlayerIntents(player_id=human_of(state).id))
    assert state.status == MatchLifecycleStatus.FINISHED
    assert state.result.status == "finished"
    assert state.result.winner_team == 0  # команда человека
    assert state.result.reward_coins == 5


def test_judgement_decides_at_the_threshold_turn() -> None:
    state = make_battle()
    state.turn = JUDGEMENT_TURN
    # Ослабим одну башню бота — у человека «крепче слабейшая» при равном числе.
    from app.domain.combat.engine.battle import build_context

    ctx = build_context(state)
    towers_of(ctx, "p2")[0].current_hp = 1
    from app.domain.combat.engine.battle import apply_context

    apply_context(state, ctx)

    events = resolve_v4_turn(state, human_intents=PlayerIntents(player_id=human_of(state).id))
    assert events == []  # на суде ходы не разыгрываются
    assert state.status == MatchLifecycleStatus.FINISHED
    assert state.result.winner_team == 0


def test_turn_timer_shrinks_from_turn_15_to_floor() -> None:
    # DESIGN §3.5: база до 14-го хода, с 15-го −1 с за ход, пол 5 с.
    assert turn_duration_seconds(1) == 30
    assert turn_duration_seconds(14) == 30
    assert turn_duration_seconds(15) == 29
    assert turn_duration_seconds(16) == 28
    assert turn_duration_seconds(39) == 5
    assert turn_duration_seconds(100) == 5  # пол держится


def test_deadline_uses_compressed_turn_time_after_resolve() -> None:
    state = make_battle()
    state.turn = 20
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    events = resolve_v4_turn(
        state, human_intents=PlayerIntents(player_id=human_of(state).id), now=now
    )
    assert state.turn == 21
    # Дедлайн 21-го хода = буфер анимации + сжатое время (30 − (21 − 14) = 23 с),
    # а не константные 30 с.
    expected = resolution_buffer_seconds(len(events)) + 23
    assert state.planning_deadline == now + timedelta(seconds=expected)


def test_payload_reports_planning_seconds() -> None:
    state = make_battle()
    assert v4_combat_response(state)["match"]["planning_seconds"] == 30
    state.turn = 39
    assert v4_combat_response(state)["match"]["planning_seconds"] == 5


def test_towers_do_not_emit_unit_waited() -> None:
    state = make_battle()
    tower_ids = {u.id for u in state.units if u.blueprint_id == "tower_default"}
    assert len(tower_ids) == 10  # сценарий не пуст: обе стороны с башнями
    events = resolve_v4_turn(state, human_intents=PlayerIntents(player_id=human_of(state).id))
    waited_ids = {e.unit_id for e in events if e.kind == "unit_waited"}
    # Башни целый ход без цели, но «ожидание» структур — шум, его не эмитим.
    assert waited_ids.isdisjoint(tower_ids)


def test_event_snapshot_carries_counts_but_never_cards() -> None:
    """U3: стопка колоды убывает по кадрам, но состав руки/колоды не течёт."""
    state = make_battle()
    human = human_of(state)
    events = resolve_v4_turn(state, human_intents=PlayerIntents(player_id=human.id))
    draws = [e for e in events if e.kind == "card_drawn" and e.player_id == human.id]
    assert draws, "человек с рукой 3 из 12 обязан добрать карту"
    snapshot_player = next(
        p for p in draws[-1].snapshot["players"] if p["id"] == human.id
    )
    # Кадр card_drawn снят ПОСЛЕ мутации — счётчики уже финальные для хода.
    assert snapshot_player["deck_count"] == len(human.deck)
    assert snapshot_player["hand_count"] == len(human.hand)
    # Ни одно событие хода не раскрывает состав руки или порядок колоды.
    for event in events:
        for player_snapshot in event.snapshot["players"]:
            assert set(player_snapshot) == {"id", "mana", "deck_count", "hand_count"}


def test_payload_hides_deck_and_opponent_hand() -> None:
    state = make_battle()
    human = human_of(state)
    payload = v4_combat_response(state, viewer_id=human.id)["match"]
    viewer = next(p for p in payload["players"] if p["id"] == human.id)
    opponent = next(p for p in payload["players"] if p["id"] != human.id)
    assert len(viewer["hand"]) == 3
    assert opponent["hand"] == [] and opponent["hand_count"] == 3
    assert all("deck" not in p for p in payload["players"])  # колода — секрет
    assert payload["rows"] == 5 and payload["cols"] == 5
    # Башни отмечены для клиента и стоят на призрачных рядах.
    towers = [u for u in payload["units"] if u["is_tower"]]
    assert len(towers) == 10
    assert {u["row"] for u in towers} == {-1, 5}
