"""Сериализация матча v4 наружу (этап 15в): viewer-специфичный payload.

Тот же контракт-каркас, что у MVP (combat_payloads.combat_response): match с
players/units/rows/cols/viewer_id + events. Анти-чит инварианты R12 сохранены:
колода наружу не уходит (только deck_count), рука — только своему владельцу.
Юниты — в формате v4 (blueprint/стойка/статусы), клиент рисует по ним поле.
"""

from app.domain.combat.engine.battle import BattleStateV4, build_context
from app.domain.combat.engine.cards import CardType
from app.domain.combat.engine.content import BLUEPRINTS, CARDS, V4_COLS, V4_ROWS
from app.domain.combat.engine.stances import Stance
from app.domain.combat.engine.statuses import all_status_specs
from app.domain.combat.engine.tags import TAG_TOWER
from app.domain.combat.engine.translate import translate_engine_events
from app.domain.combat.engine.units import (
    current_stance,
    effective_stats,
    stance_turns_left,
    unit_tags,
)
from app.domain.combat.helpers import human_players
from app.domain.combat.timing import turn_duration_seconds


def _unit_payload(unit, blueprint) -> dict:
    stats = effective_stats(unit, blueprint)
    tags = unit_tags(unit, blueprint)
    return {
        "id": unit.id,
        "owner_id": unit.owner_id,
        "side": unit.side.value,
        "blueprint_id": unit.blueprint_id,
        # card_id — для арта (у башен карты нет).
        "card_id": unit.blueprint_id if unit.blueprint_id in CARDS else None,
        "row": unit.row,
        "col": unit.col,
        "current_hp": unit.current_hp,
        "max_hp": stats.hp,
        "damage": stats.damage,
        "move_steps": stats.move_steps,
        "attacks_per_turn": stats.attacks_per_turn,
        "stance": current_stance(unit, blueprint).value,
        # V6: ходов до самостоятельной смены стойки (None = не сменится) —
        # число на иконке стойки; клиент его не вычисляет.
        "stance_turns_left": stance_turns_left(unit, blueprint),
        "is_tower": TAG_TOWER in tags,
        "statuses": [
            {"id": s.id, "stacks": s.stacks, "ttl": s.ttl} for s in unit.statuses
        ],
        "remaining_steps": unit.remaining_steps,
        "remaining_attacks": unit.remaining_attacks,
    }


def _pattern_cells(pattern) -> list[dict]:
    return [{"forward": o.forward, "col": o.col} for o in pattern.offsets]


def v4_catalog_payload() -> list[dict]:
    """Каталог коллекционных карт v4 для клиента (арт, статы, покрытия, зоны).

    Клиент рисует по нему детальную карточку и подсветку зон спавна/покрытий
    (размер поля и зоны — из данных, не хардкод; ARCH §5.1).
    """
    cards = []
    for card in CARDS.values():
        if not card.collectible:
            continue
        entry = {
            "id": card.id,
            "name": card.name,
            "cost": card.cost,
            "rarity": card.rarity.value,
            "card_type": card.card_type.value,
            "rules_text": card.rules_text,
            "board": {"rows": V4_ROWS, "cols": V4_COLS},
        }
        if card.card_type == CardType.UNIT:
            bp = BLUEPRINTS[card.blueprint_id]
            entry["stats"] = {
                "hp": bp.stats.hp,
                "damage": bp.stats.damage,
                "attacks_per_turn": bp.stats.attacks_per_turn,
                "move_steps": bp.stats.move_steps,
            }
            entry["coverage_attack"] = _pattern_cells(bp.coverage(Stance.ATTACK))
            entry["coverage_defense"] = _pattern_cells(bp.coverage(Stance.DEFENSE))
            entry["spawn_rows"] = list(bp.spawn_zone.rows_from_back)
            entry["damage_defense"] = (
                bp.stats_defense.damage if bp.stats_defense and bp.stats_defense.damage else None
            )
        else:
            entry["spell_id"] = card.spell_id
        cards.append(entry)
    return cards


def v4_status_catalog_payload() -> list[dict]:
    """Публичные значения текущих status id для боевого UI (U4/W1)."""
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "icon": spec.icon,
            "decay": spec.decay.value,
        }
        for spec in all_status_specs()
    ]


def v4_combat_response(
    state: BattleStateV4,
    *,
    viewer_id: str | None = None,
    events: list | None = None,
    resolved_turn: int | None = None,
) -> dict:
    """Payload матча для одного клиента; events — факты последнего хода."""
    if events is None and resolved_turn is None:
        events = state.last_events
        resolved_turn = state.last_resolved_turn
    if viewer_id is None:
        humans = human_players(state)
        viewer_id = humans[0].id if humans else None

    ctx = build_context(state)
    players_payload = []
    for player in state.players:
        players_payload.append(
            {
                "id": player.id,
                "side": player.side.value,
                "team": player.team,
                "is_bot": player.is_bot,
                "mana": player.mana,
                "ready": player.id in state.ready_player_ids,
                "hand": list(player.hand) if player.id == viewer_id else [],
                "hand_count": len(player.hand),
                "deck_count": len(player.deck),
            }
        )

    match_payload = {
        "id": state.id,
        "ruleset_version": state.ruleset_version,
        "status": state.status.value,
        "turn": state.turn,
        "rows": state.rows,
        "cols": state.cols,
        "mana_cap": state.mana_cap,
        "planning_deadline": (
            state.planning_deadline.isoformat() if state.planning_deadline else None
        ),
        # Длительность планирования ТЕКУЩЕГО хода (эндшпиль сжимает, DESIGN
        # §3.5). Клиент капает видимый таймер этим числом и не дублирует
        # формулу; буфер анимации в дедлайне остаётся сверху.
        "planning_seconds": turn_duration_seconds(state.turn),
        "players": players_payload,
        "viewer_id": viewer_id,
        "units": [_unit_payload(unit, ctx.blueprint_of(unit)) for unit in state.units],
        "log": [{"message": entry.message} for entry in state.log],
        "result": state.result.model_dump(mode="json"),
    }
    client_events = translate_engine_events(events or [])
    return {
        "match": match_payload,
        "events": [event.model_dump(mode="json") for event in client_events],
        "resolved_turn": resolved_turn,
        "last_sequence": client_events[-1].sequence if client_events else None,
    }
