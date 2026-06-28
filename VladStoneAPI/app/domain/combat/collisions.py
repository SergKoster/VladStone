from collections import defaultdict

from app.domain.combat.events import add_event, log_and_event
from app.domain.combat.models import (
    CombatEventType,
    CombatTargetKind,
    MatchState,
    Position,
)


def apply_move_collision(match: MatchState, target: tuple[int, int], contenders: list) -> None:
    collision_damage: dict[str, int] = defaultdict(int)
    target_position = Position(row=target[0], col=target[1])
    for intent in contenders:
        unit = intent.unit
        unit.remaining_steps = max(0, unit.remaining_steps - 1)
        if unit.remaining_attacks <= 0:
            add_event(
                match,
                CombatEventType.COLLISION_STEP,
                f"{unit.id} collided at {target} without attack",
                actor_id=unit.id,
                from_position=unit.position,
                to_position=target_position,
                target_kind=CombatTargetKind.CELL,
            )
            continue
        enemies = [
            enemy_intent.unit
            for enemy_intent in contenders
            if enemy_intent.unit.side != unit.side and enemy_intent.unit.current_hp > 0
        ]
        if not enemies:
            continue
        enemy = enemies[0]
        collision_damage[enemy.id] += unit.stats.damage
        unit.remaining_attacks -= 1
        before_hp = enemy.current_hp
        log_and_event(
            match,
            CombatEventType.COLLISION,
            f"{unit.id} collided at {target} and attacked {enemy.id} for {unit.stats.damage}",
            actor_id=unit.id,
            target_id=enemy.id,
            target_kind=CombatTargetKind.UNIT,
            damage=unit.stats.damage,
            from_position=unit.position,
            to_position=target_position,
            before_hp=before_hp,
            after_hp=max(0, before_hp - unit.stats.damage),
        )

    units_by_id = {unit.id: unit for unit in match.units}
    for unit_id, damage in collision_damage.items():
        if unit_id in units_by_id:
            units_by_id[unit_id].current_hp -= damage
    add_event(
        match,
        CombatEventType.COLLISION,
        f"collision at {target} resolved",
        to_position=target_position,
        target_kind=CombatTargetKind.CELL,
    )
