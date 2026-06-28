from app.domain.combat.board import direction_for_side
from app.domain.combat.constants import BOARD_ROWS
from app.domain.combat.models import HeroState, MatchState, PlayerSide, UnitState


def find_unit_target(units: list[UnitState], attacker: UnitState) -> UnitState | None:
    direction = direction_for_side(attacker.side)
    candidates: list[tuple[int, UnitState]] = []
    for target in units:
        if target.side == attacker.side or target.current_hp <= 0:
            continue
        if target.position.col != attacker.position.col:
            continue
        delta = (target.position.row - attacker.position.row) * direction
        if 1 <= delta <= attacker.stats.attack_range:
            candidates.append((delta, target))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def find_hero_target(match: MatchState, attacker: UnitState) -> HeroState | None:
    direction = direction_for_side(attacker.side)
    hero_row = BOARD_ROWS if attacker.side == PlayerSide.TOP else -1
    distance = (hero_row - attacker.position.row) * direction
    if not 1 <= distance <= attacker.stats.attack_range:
        return None

    for player in match.players:
        if player.side != attacker.side and player.hero.hp > 0:
            return player.hero
    return None
