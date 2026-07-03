from collections import defaultdict
from dataclasses import dataclass

from app.domain.combat.events import log_and_event
from app.domain.combat.models import (
    CombatEventType,
    CombatTargetKind,
    HeroState,
    MatchState,
    UnitState,
)
from app.domain.combat.targeting import find_hero_target, find_unit_target


@dataclass(frozen=True)
class AttackIntent:
    unit: UnitState
    target_unit: UnitState | None = None
    target_hero: HeroState | None = None


def attack_intent(match: MatchState, unit: UnitState) -> AttackIntent | None:
    if unit.remaining_attacks <= 0:
        return None
    target = find_unit_target(match.units, unit)
    if target is not None:
        return AttackIntent(unit=unit, target_unit=target)
    hero = find_hero_target(match, unit)
    if hero is not None:
        return AttackIntent(unit=unit, target_hero=hero)
    return None


def apply_attack_intents(match: MatchState, intents: list[AttackIntent]) -> None:
    # Damage allocated to each target so far this micro-step. Used both to report
    # accurate incremental before/after HP and to avoid overkill: a unit will not
    # spend its attack on a target that is already doomed by earlier attackers.
    unit_damage: dict[str, int] = defaultdict(int)
    hero_damage: dict[str, int] = defaultdict(int)
    for intent in intents:
        unit = intent.unit
        if unit.current_hp <= 0 or unit.remaining_attacks <= 0:
            continue
        if intent.target_unit is not None and intent.target_unit.current_hp > 0:
            before_hp = intent.target_unit.current_hp - unit_damage[intent.target_unit.id]
            if before_hp <= 0:
                # Target already lethally allocated — keep this attack for later.
                continue
            unit.remaining_attacks -= 1
            unit_damage[intent.target_unit.id] += unit.stats.damage
            log_and_event(
                match,
                CombatEventType.ATTACK,
                f"{unit.id} attacked {intent.target_unit.id} for {unit.stats.damage}",
                actor_id=unit.id,
                target_id=intent.target_unit.id,
                target_kind=CombatTargetKind.UNIT,
                damage=unit.stats.damage,
                from_position=unit.position,
                to_position=intent.target_unit.position,
                before_hp=before_hp,
                after_hp=max(0, before_hp - unit.stats.damage),
            )
        elif intent.target_hero is not None and intent.target_hero.hp > 0:
            before_hp = intent.target_hero.hp - hero_damage[intent.target_hero.owner_id]
            if before_hp <= 0:
                continue
            unit.remaining_attacks -= 1
            hero_damage[intent.target_hero.owner_id] += unit.stats.damage
            log_and_event(
                match,
                CombatEventType.HERO_HIT,
                f"{unit.id} attacked hero {intent.target_hero.owner_id} for {unit.stats.damage}",
                actor_id=unit.id,
                target_id=intent.target_hero.owner_id,
                target_kind=CombatTargetKind.HERO,
                damage=unit.stats.damage,
                from_position=unit.position,
                before_hp=before_hp,
                after_hp=max(0, before_hp - unit.stats.damage),
            )

    units_by_id = {unit.id: unit for unit in match.units}
    for unit_id, damage in unit_damage.items():
        if unit_id in units_by_id:
            units_by_id[unit_id].current_hp -= damage
    for player in match.players:
        if player.id in hero_damage:
            player.hero.hp = max(0, player.hero.hp - hero_damage[player.id])
