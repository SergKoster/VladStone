"""Сериализация матча v4 наружу (этап 15в): viewer-специфичный payload.

Тот же контракт-каркас, что у MVP (combat_payloads.combat_response): match с
players/units/rows/cols/viewer_id + events. Анти-чит инварианты R12 сохранены:
колода наружу не уходит (только deck_count), рука — только своему владельцу.
Юниты — в формате v4 (blueprint/стойка/статусы), клиент рисует по ним поле.
"""

from app.domain.combat.engine.battle import BattleStateV4, build_context
from app.domain.combat.engine.content import CARDS
from app.domain.combat.engine.tags import TAG_TOWER
from app.domain.combat.engine.translate import translate_engine_events
from app.domain.combat.engine.units import current_stance, effective_stats, unit_tags
from app.domain.combat.helpers import human_players


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
        "stance": current_stance(unit, blueprint).value,
        "is_tower": TAG_TOWER in tags,
        "statuses": [
            {"id": s.id, "stacks": s.stacks, "ttl": s.ttl} for s in unit.statuses
        ],
        "remaining_steps": unit.remaining_steps,
        "remaining_attacks": unit.remaining_attacks,
    }


def v4_combat_response(
    state: BattleStateV4,
    *,
    viewer_id: str | None = None,
    events: list | None = None,
) -> dict:
    """Payload матча для одного клиента; events — факты последнего хода."""
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
    }
