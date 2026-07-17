"""Перевод фактов движка в combat-события клиента (P2.12)."""

from typing import get_args

import pytest

from app.domain.combat.engine import EngineEvent, translate_engine_events
from app.domain.combat.models import CombatEventType, EventPosition, Position, UnitWaitReason


def all_engine_kinds() -> list[str]:
    return list(get_args(EngineEvent.model_fields["kind"].annotation))


def test_every_engine_fact_kind_has_a_client_mapping() -> None:
    # Тотальность: новый вид факта без маппинга ломает этот тест, а не теряет
    # события молча в бою.
    for kind in all_engine_kinds():
        fact = EngineEvent(kind=kind)
        [event] = translate_engine_events([fact])
        assert isinstance(event.type, CombatEventType), kind
        assert event.message, kind


def test_attack_fact_maps_to_full_animation_contract() -> None:
    snapshot = {
        "units": [{"id": "u1", "row": 3, "col": 1}],
        "players": [{"id": "p1", "mana": 4}],
    }
    fact = EngineEvent(
        kind="attack",
        unit_id="u1",
        target_id="u2",
        amount=2,
        before=5,
        after=3,
        from_cell=(3, 1),
        to_cell=(1, 1),
        phase="iterations",
        iteration=2,
        affected_cells=[(2, 0), (2, 1)],
        snapshot=snapshot,
    )
    [event] = translate_engine_events([fact], sequence_start=7)
    assert event.type == CombatEventType.ATTACK
    assert event.actor_id == "u1" and event.target_id == "u2"
    assert event.damage == 2 and event.before_hp == 5 and event.after_hp == 3
    assert event.from_position == EventPosition(row=3, col=1)
    assert event.to_position == EventPosition(row=1, col=1)
    assert event.sequence == 7 and event.micro_step == 2 and event.phase == "iterations"
    assert event.affected_cells == [Position(row=2, col=0), Position(row=2, col=1)]
    assert event.snapshot == snapshot


def test_tower_ghost_row_is_valid_in_animation_event() -> None:
    fact = EngineEvent(
        kind="attack",
        unit_id="tower",
        target_id="u1",
        amount=1,
        from_cell=(-1, 2),
        to_cell=(0, 2),
    )
    [event] = translate_engine_events([fact])
    assert event.from_position == EventPosition(row=-1, col=2)


def test_ability_fact_keeps_structured_trigger_and_effect_kind() -> None:
    fact = EngineEvent(
        kind="ability_triggered",
        unit_id="red-skull",
        trigger="on_death",
        effect_kind="deal_damage",
        from_cell=(2, 1),
    )
    [event] = translate_engine_events([fact])
    assert event.actor_id == "red-skull"
    assert event.ability_trigger == "on_death"
    assert event.effect_kind == "deal_damage"


def test_unit_scoped_facts_put_the_unit_into_target_id() -> None:
    heal = EngineEvent(kind="heal", unit_id="u1", amount=3, before=2, after=5, phase="spells")
    status = EngineEvent(kind="status_applied", unit_id="u1", status_id="poison", amount=2)
    [heal_event, status_event] = translate_engine_events([heal, status])
    # Пострадавший/облагодетельствованный юнит — target, актор не выдумывается.
    assert heal_event.actor_id is None and heal_event.target_id == "u1"
    assert heal_event.type == CombatEventType.HEAL and heal_event.after_hp == 5
    assert heal_event.damage is None  # рост HP — не урон, попапом урона не идёт
    assert status_event.type == CombatEventType.STATUS_APPLIED
    assert "poison" in status_event.message
    # V9: попап «Яд +N» строится по структурным полям, а не по message.
    assert status_event.status_id == "poison"
    assert status_event.status_stacks == 2
    assert heal_event.status_id is None and heal_event.status_stacks is None


def test_waited_fact_keeps_the_server_reason() -> None:
    fact = EngineEvent(
        kind="unit_waited",
        unit_id="matesha",
        wait_reason=UnitWaitReason.DEFENSE_NO_TARGET,
        from_cell=(3, 1),
        phase="iterations",
        iteration=2,
    )
    [event] = translate_engine_events([fact])
    assert event.type == CombatEventType.UNIT_WAITED
    assert event.actor_id == "matesha"
    assert event.wait_reason == UnitWaitReason.DEFENSE_NO_TARGET
    assert event.from_position == EventPosition(row=3, col=1)


def test_player_facts_and_sequence_numbering() -> None:
    facts = [
        EngineEvent(kind="spell_cast", player_id="p1", card_id="bolt_card", phase="spells"),
        EngineEvent(kind="card_drawn", player_id="p2", amount=1, phase="draw"),
        EngineEvent(kind="mana_changed", player_id="p2", amount=2, before=1, after=3),
    ]
    events = translate_engine_events(facts)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.actor_id for event in events] == ["p1", "p2", "p2"]
    assert events[0].type == CombatEventType.SPELL_CAST
    # V7: видимый розыгрыш несёт карту структурно (арт всплытия каста);
    # добор карту НЕ раскрывает (анти-чит).
    assert events[0].card_id == "bolt_card"
    assert events[1].card_id is None
    # micro_step вне итераций — 0 (как спавны в MVP-контракте).
    assert all(event.micro_step == 0 for event in events)


def test_unknown_kind_fails_loudly() -> None:
    fact = EngineEvent(kind="attack")
    object.__setattr__(fact, "kind", "wormhole")  # обход валидации — симуляция бага
    with pytest.raises(ValueError, match="no client mapping"):
        translate_engine_events([fact])
