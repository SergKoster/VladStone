from datetime import datetime

from app.domain.combat.attacks import AttackIntent, apply_attack_intents, attack_intent
from app.domain.combat.board import add_turn_mana
from app.domain.combat.constants import BOARD_ROWS
from app.domain.combat.lifecycle import finish_match_if_needed, remove_dead_units
from app.domain.combat.models import ActionPriority, MatchLifecycleStatus, MatchState
from app.domain.combat.movement import MoveIntent, apply_move_intents, move_intent
from app.domain.combat.timing import (
    clear_planning_timer,
    resolution_buffer_seconds,
    start_planning_timer,
)


def resolve_turn(match: MatchState, *, now: datetime | None = None) -> MatchState:
    resolved = match.model_copy(deep=True)
    if finish_match_if_needed(resolved):
        return resolved
    resolved.status = MatchLifecycleStatus.RESOLVING
    clear_planning_timer(resolved)
    for unit in resolved.units:
        unit.remaining_steps = unit.stats.move_steps
        unit.remaining_attacks = unit.stats.attacks

    for _ in range(BOARD_ROWS * 4):
        if resolved.result.status == "finished":
            break
        acted = resolve_micro_turn(resolved)
        remove_dead_units(resolved)
        finish_match_if_needed(resolved)
        if not acted:
            break

    if resolved.result.status != "finished":
        resolved.turn += 1
        for player in resolved.players:
            player.mana = add_turn_mana(player.mana, resolved.turn, resolved.mana_cap)
        resolved.status = MatchLifecycleStatus.PLANNING
        # Freeze planning until the resolution animation has had time to play.
        buffer = resolution_buffer_seconds(len(resolved.events))
        start_planning_timer(resolved, now=now, resolve_buffer_seconds=buffer)
    return resolved


def resolve_micro_turn(match: MatchState) -> bool:
    attack_intents: list[AttackIntent] = []
    move_intents: list[MoveIntent] = []
    for unit in list(match.units):
        if unit.current_hp <= 0:
            continue
        next_attack = attack_intent(match, unit)
        next_move = move_intent(match, unit)
        if unit.stats.action_priority == ActionPriority.ATTACK_FIRST:
            if next_attack is not None:
                attack_intents.append(next_attack)
            elif next_move is not None:
                move_intents.append(next_move)
        elif next_move is not None:
            move_intents.append(next_move)
        elif next_attack is not None:
            attack_intents.append(next_attack)

    acted = False
    if attack_intents:
        apply_attack_intents(match, attack_intents)
        acted = True
    if apply_move_intents(match, move_intents):
        acted = True
    return acted
