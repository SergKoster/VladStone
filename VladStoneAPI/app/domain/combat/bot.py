from app.domain.combat.cards import BRUISER_CARD, RANGER_CARD
from app.domain.combat.helpers import player_by_id
from app.domain.combat.models import MatchState, Position
from app.domain.combat.planning import apply_placements

# Deterministic test pattern: the bot alternates between a bruiser pushed down
# lane (column) 0 and a ranger down lane 1, so head-on collisions are easy to
# reproduce by mirroring its placements. It starts with the bruiser and *saves
# mana* for the card it wants next instead of skipping it in the pattern.
BRUISER_LANE = 0
RANGER_LANE = 1


def apply_simple_bot_turn(match: MatchState) -> MatchState:
    bot = player_by_id(match, "bot")
    wants_bruiser = match.bot_spawn_count % 2 == 0
    card = BRUISER_CARD if wants_bruiser else RANGER_CARD
    lane = BRUISER_LANE if wants_bruiser else RANGER_LANE
    if bot.mana < card.cost:
        return match
    spawn_taken = any(
        unit.position.row == 0 and unit.position.col == lane and unit.side == bot.side
        for unit in match.units
    )
    if spawn_taken:
        return match
    updated = apply_placements(
        match,
        [(card.id, Position(row=0, col=lane))],
        owner_id=bot.id,
        side=bot.side,
    )
    if len(updated.units) > len(match.units):
        updated.bot_spawn_count += 1
    return updated
