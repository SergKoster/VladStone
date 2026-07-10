from app.domain.combat.constants import BOARD_COLS, BOARD_ROWS, MANA_CAP
from app.domain.combat.models import PlayerSide, Position


def mana_gain_for_turn(turn: int) -> int:
    if turn == 1:
        return 2
    if turn % 10 == 0:
        return 3
    if turn % 3 == 0:
        return 2
    return 1


def add_turn_mana(current_mana: int, turn: int, cap: int = MANA_CAP) -> int:
    return min(cap, current_mana + mana_gain_for_turn(turn))


def side_for_team(team: int) -> PlayerSide:
    """Board side is derived from the team (R12): allies share a side."""
    return PlayerSide.BOTTOM if team == 0 else PlayerSide.TOP


def direction_for_side(side: PlayerSide) -> int:
    return 1 if side == PlayerSide.TOP else -1


def spawn_rows_for_side(side: PlayerSide, rows: int = BOARD_ROWS) -> set[int]:
    return {0} if side == PlayerSide.TOP else {rows - 1}


def is_valid_spawn_position(side: PlayerSide, position: Position, rows: int = BOARD_ROWS) -> bool:
    return position.row in spawn_rows_for_side(side, rows) and 0 <= position.col < BOARD_COLS


def reward_for_result(did_win: bool) -> int:
    return 5 if did_win else 1
