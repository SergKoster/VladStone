from app.domain.combat.cards import RANGER_CARD
from app.domain.combat.helpers import player_by_id
from app.domain.combat.models import MatchState, Position
from app.domain.combat.planning import apply_placements


def apply_simple_bot_turn(match: MatchState) -> MatchState:
    bot = player_by_id(match, "bot")
    if bot.mana < RANGER_CARD.cost:
        return match
    free_cols = [
        col
        for col in range(match.cols)
        if not any(unit.position.row == 0 and unit.position.col == col for unit in match.units)
    ]
    if not free_cols:
        return match
    return apply_placements(
        match,
        [(RANGER_CARD.id, Position(row=0, col=free_cols[0]))],
        owner_id=bot.id,
        side=bot.side,
    )
