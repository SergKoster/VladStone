from app.domain.combat.board import reward_for_result
from app.domain.combat.events import log_and_event
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
    # Team-based finish (R12): the match ends once any team is fully wiped
    # (no living heroes); the winner is the sole team still standing, a
    # simultaneous wipe of everyone is a draw.
    all_teams = {player.team for player in match.players}
    alive_teams = {player.team for player in match.players if player.hero.hp > 0}
    if alive_teams == all_teams:
        return False

    winner_team = next(iter(alive_teams)) if len(alive_teams) == 1 else None
    winners = [player for player in match.players if player.team == winner_team]
    # PvE reward semantics: the match-level reward is for the human side.
    # Per-participant rewards (PvP) are a later phase — see claim_combat_reward.
    human_won = any(not player.is_bot for player in winners)
    match.result.status = "finished"
    match.result.winner_team = winner_team
    match.result.winner_id = winners[0].id if len(winners) == 1 else None
    match.result.reward_coins = reward_for_result(winner_team is not None and human_won)
    match.status = MatchLifecycleStatus.FINISHED
    log_and_event(
        match,
        CombatEventType.MATCH_FINISHED,
        f"match finished, winner: {match.result.winner_id or 'draw'}",
        target_id=match.result.winner_id,
        target_kind=CombatTargetKind.MATCH,
    )
    return True
