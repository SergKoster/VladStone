from collections import defaultdict
from dataclasses import dataclass

from app.domain.combat.board import direction_for_side
from app.domain.combat.collisions import apply_move_collision
from app.domain.combat.constants import BOARD_COLS, BOARD_ROWS
from app.domain.combat.events import add_event, log_and_event
from app.domain.combat.models import (
    CombatEventType,
    CombatTargetKind,
    MatchState,
    Position,
    UnitState,
)


@dataclass(frozen=True)
class MoveIntent:
    unit: UnitState
    target: Position


def move_intent(match: MatchState, unit: UnitState) -> MoveIntent | None:
    if unit.remaining_steps <= 0:
        return None
    target = next_position(unit)
    if target is None:
        return None
    occupied = {
        (other.position.row, other.position.col)
        for other in match.units
        if other.id != unit.id and other.current_hp > 0
    }
    if (target.row, target.col) in occupied:
        return None
    return MoveIntent(unit=unit, target=target)


def apply_move_intents(match: MatchState, intents: list[MoveIntent]) -> bool:
    if not intents:
        return False

    acted = False
    grouped: dict[tuple[int, int], list[MoveIntent]] = defaultdict(list)
    for intent in intents:
        grouped[(intent.target.row, intent.target.col)].append(intent)

    for target, contenders in grouped.items():
        alive_contenders = [intent for intent in contenders if intent.unit.current_hp > 0]
        if not alive_contenders:
            continue
        sides = {intent.unit.side for intent in alive_contenders}
        if len(alive_contenders) > 1 and len(sides) > 1:
            apply_move_collision(match, target, alive_contenders)
            acted = True
            continue
        if len(alive_contenders) > 1:
            target_position = Position(row=target[0], col=target[1])
            for intent in alive_contenders:
                intent.unit.remaining_steps = max(0, intent.unit.remaining_steps - 1)
                add_event(
                    match,
                    CombatEventType.MOVE_BLOCKED,
                    f"{intent.unit.id} could not move to {target}",
                    actor_id=intent.unit.id,
                    from_position=intent.unit.position,
                    to_position=target_position,
                    target_kind=CombatTargetKind.CELL,
                )
            acted = True
            continue

        intent = alive_contenders[0]
        occupied = {
            (other.position.row, other.position.col)
            for other in match.units
            if other.id != intent.unit.id and other.current_hp > 0
        }
        if target in occupied:
            continue
        previous_position = intent.unit.position
        intent.unit.position = intent.target
        intent.unit.remaining_steps -= 1
        log_and_event(
            match,
            CombatEventType.MOVE,
            (
                f"{intent.unit.id} moved from {previous_position.row}:{previous_position.col} "
                f"to {intent.target.row}:{intent.target.col}"
            ),
            actor_id=intent.unit.id,
            from_position=previous_position,
            to_position=intent.target,
            target_kind=CombatTargetKind.CELL,
        )
        acted = True

    return acted


def next_position(unit: UnitState) -> Position | None:
    row = unit.position.row + direction_for_side(unit.side)
    col = unit.position.col
    if not is_on_board_coordinates(row, col):
        return None
    return Position(row=row, col=col)


def is_on_board_coordinates(row: int, col: int) -> bool:
    return 0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS
