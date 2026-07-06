from app.domain.combat.models import (
    CombatEvent,
    CombatEventType,
    CombatLogEntry,
    CombatTargetKind,
    MatchState,
    Position,
)


def log_and_event(
    match: MatchState,
    event_type: CombatEventType,
    message: str,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    target_kind: CombatTargetKind | None = None,
    damage: int | None = None,
    from_position: Position | None = None,
    to_position: Position | None = None,
    before_hp: int | None = None,
    after_hp: int | None = None,
) -> None:
    match.log.append(CombatLogEntry(message=message))
    add_event(
        match,
        event_type,
        message,
        actor_id=actor_id,
        target_id=target_id,
        target_kind=target_kind,
        damage=damage,
        from_position=from_position,
        to_position=to_position,
        before_hp=before_hp,
        after_hp=after_hp,
    )


def add_event(
    match: MatchState,
    event_type: CombatEventType,
    message: str,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    target_kind: CombatTargetKind | None = None,
    damage: int | None = None,
    from_position: Position | None = None,
    to_position: Position | None = None,
    before_hp: int | None = None,
    after_hp: int | None = None,
) -> None:
    sequence = len(match.events) + 1
    match.events.append(
        CombatEvent(
            type=event_type,
            message=message,
            actor_id=actor_id,
            target_id=target_id,
            target_kind=target_kind,
            damage=damage,
            from_position=from_position,
            to_position=to_position,
            before_hp=before_hp,
            after_hp=after_hp,
            sequence=sequence,
            micro_step=match.current_iteration,
            snapshot=event_snapshot(match),
        )
    )


def event_snapshot(match: MatchState) -> dict:
    return {
        "players": [
            {
                "id": player.id,
                "side": player.side,
                "mana": player.mana,
                "hero": {
                    "owner_id": player.hero.owner_id,
                    "side": player.hero.side,
                    "hp": player.hero.hp,
                },
            }
            for player in match.players
        ],
        "units": [
            {
                "id": unit.id,
                "owner_id": unit.owner_id,
                "side": unit.side,
                "card_id": unit.card_id,
                "position": {
                    "row": unit.position.row,
                    "col": unit.position.col,
                },
                "current_hp": max(0, unit.current_hp),
                "remaining_steps": unit.remaining_steps,
                "remaining_attacks": unit.remaining_attacks,
                "stats": unit.stats.model_dump(mode="json"),
            }
            for unit in match.units
            if unit.current_hp > 0
        ],
    }
