from app.domain.combat.board import reward_for_result
from app.domain.combat.events import log_and_event
from app.domain.combat.helpers import player_by_id
from app.domain.combat.models import (
    CombatEventType,
    CombatTargetKind,
    MatchLifecycleStatus,
    MatchState,
)


def remove_dead_units(match: MatchState) -> None:
    dead_units = [unit for unit in match.units if unit.current_hp <= 0]
    if dead_units:
        for unit in dead_units:
            log_and_event(
                match,
                CombatEventType.DEATH,
                f"{unit.id} died",
                actor_id=unit.id,
                target_kind=CombatTargetKind.UNIT,
                from_position=unit.position,
                before_hp=max(0, unit.current_hp),
                after_hp=0,
            )
        match.units = [unit for unit in match.units if unit.current_hp > 0]


def finish_match_if_needed(match: MatchState) -> bool:
    if match.result.status == "finished":
        return True
    alive_players = [player for player in match.players if player.hero.hp > 0]
    if len(alive_players) == len(match.players):
        return False

    player = player_by_id(match, "player")
    winner = alive_players[0] if len(alive_players) == 1 else None
    reward = reward_for_result(winner is not None and winner.id == player.id)
    match.result.status = "finished"
    match.result.winner_id = winner.id if winner else None
    match.result.reward_coins = reward
    match.status = MatchLifecycleStatus.FINISHED
    log_and_event(
        match,
        CombatEventType.MATCH_FINISHED,
        f"match finished, winner: {match.result.winner_id or 'draw'}",
        target_id=match.result.winner_id,
        target_kind=CombatTargetKind.MATCH,
    )
    return True
