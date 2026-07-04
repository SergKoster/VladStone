from app.domain.combat.board import direction_for_side, is_valid_spawn_position
from app.domain.combat.cards import CARD_BY_ID
from app.domain.combat.events import add_event, log_and_event
from app.domain.combat.factory import create_unit
from app.domain.combat.helpers import player_by_id, unit_at
from app.domain.combat.models import (
    CombatEventType,
    CombatTargetKind,
    MatchState,
    PlayerSide,
    Position,
)
from app.domain.combat.movement import is_on_board_coordinates


def apply_placements(
    match: MatchState,
    placements: list[tuple[str, Position]],
    *,
    owner_id: str,
    side: PlayerSide,
    from_hand: bool = False,
) -> MatchState:
    updated = match.model_copy(deep=True)
    player = player_by_id(updated, owner_id)
    for index, (card_id, position) in enumerate(placements):
        card = CARD_BY_ID[card_id]
        if from_hand and card_id not in updated.player_hand:
            continue
        if player.mana < card.cost:
            continue
        if not is_valid_spawn_position(side, position, updated.rows):
            continue
        occupant = unit_at(updated.units, position)
        if occupant is not None:
            if occupant.side == side:
                continue
            pushed_position = spawn_push_position(side, position)
            if pushed_position is None or unit_at(updated.units, pushed_position) is not None:
                add_event(
                    updated,
                    CombatEventType.SPAWN_BLOCKED,
                    (
                        f"{owner_id} could not spawn {card.id} at {position.row}:{position.col}: "
                        "push target blocked"
                    ),
                    to_position=position,
                    target_kind=CombatTargetKind.CELL,
                )
                continue
            previous_position = occupant.position
            occupant.position = pushed_position
            log_and_event(
                updated,
                CombatEventType.PUSH,
                (
                    f"{occupant.id} was pushed from "
                    f"{previous_position.row}:{previous_position.col} "
                    f"to {pushed_position.row}:{pushed_position.col} by spawn"
                ),
                actor_id=occupant.id,
                from_position=previous_position,
                to_position=pushed_position,
                target_kind=CombatTargetKind.CELL,
            )
        player.mana -= card.cost
        if from_hand:
            updated.player_hand.remove(card_id)
        unit = create_unit(
            unit_id=f"{owner_id}_{updated.turn}_{index}_{len(updated.units)}",
            owner_id=owner_id,
            side=side,
            card=card,
            position=position,
        )
        updated.units.append(unit)
        log_and_event(
            updated,
            CombatEventType.SPAWN,
            f"{owner_id} spawned {card.id} at {position.row}:{position.col}",
            actor_id=unit.id,
            to_position=position,
            target_kind=CombatTargetKind.CELL,
        )
    return updated


def spawn_push_position(side: PlayerSide, position: Position) -> Position | None:
    row = position.row + direction_for_side(side)
    col = position.col
    if not is_on_board_coordinates(row, col):
        return None
    return Position(row=row, col=col)
