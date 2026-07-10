from app.domain.combat.board import spawn_rows_for_side
from app.domain.combat.cards import BRUISER_CARD, RANGER_CARD
from app.domain.combat.helpers import bot_players, player_by_id
from app.domain.combat.models import MatchState, Position
from app.domain.combat.planning import apply_placements

# Deterministic test pattern: the bot alternates between a bruiser pushed down
# lane (column) 0 and a ranger down lane 1, so head-on collisions are easy to
# reproduce by mirroring its placements. It starts with the bruiser and *saves
# mana* for the card it wants next instead of skipping it in the pattern.
BRUISER_LANE = 0
RANGER_LANE = 1


def apply_simple_bot_turn(match: MatchState) -> MatchState:
    updated = match
    for bot in bot_players(match):
        updated = _apply_bot_placement(updated, bot.id)
    return updated


def _apply_bot_placement(match: MatchState, bot_id: str) -> MatchState:
    bot = player_by_id(match, bot_id)
    wants_bruiser = bot.bot_spawn_count % 2 == 0
    card = BRUISER_CARD if wants_bruiser else RANGER_CARD
    lane = BRUISER_LANE if wants_bruiser else RANGER_LANE
    if bot.mana < card.cost:
        return match
    spawn_row = min(spawn_rows_for_side(bot.side, match.rows))
    spawn_taken = any(
        unit.position.row == spawn_row and unit.position.col == lane and unit.side == bot.side
        for unit in match.units
    )
    if spawn_taken:
        return match
    updated = apply_placements(
        match,
        [(card.id, Position(row=spawn_row, col=lane))],
        owner_id=bot.id,
    )
    if len(updated.units) > len(match.units):
        player_by_id(updated, bot_id).bot_spawn_count += 1
    return updated
