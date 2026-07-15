"""Перевод фактов движка (EngineEvent) в combat-события клиента (P2.12).

Анимации строятся по серверным событиям (незыблемый принцип) — этот модуль
единственная точка, где факты v4 становятся контрактом клиента (ARCH §2.1).
Маппинг ТОТАЛЕН: каждый вид факта обязан переводиться — непереведённый вид
падает здесь громко, а не теряется молча (тест перебирает все виды).
"""

from app.domain.combat.engine.apply import EngineEvent
from app.domain.combat.models import (
    CombatEvent,
    CombatEventType,
    CombatTargetKind,
    EventPosition,
    Position,
)

# Вид факта → тип клиентского события. Дополняется вместе с EngineEvent.kind.
_KIND_TO_TYPE: dict[str, CombatEventType] = {
    "attack": CombatEventType.ATTACK,
    "damage": CombatEventType.DAMAGE,
    "heal": CombatEventType.HEAL,
    "moved": CombatEventType.MOVE,
    "pushed": CombatEventType.PUSH,
    "collision": CombatEventType.COLLISION,
    "unit_died": CombatEventType.DEATH,
    "spawned": CombatEventType.SPAWN,
    "token_spawned": CombatEventType.SPAWN,
    "spell_cast": CombatEventType.SPELL_CAST,
    "stance_changed": CombatEventType.STANCE_CHANGED,
    "status_applied": CombatEventType.STATUS_APPLIED,
    "status_expired": CombatEventType.STATUS_EXPIRED,
    "ability_triggered": CombatEventType.ABILITY_TRIGGERED,
    "tag_granted": CombatEventType.TAG_GRANTED,
    "killed": CombatEventType.EXECUTED,
    "card_drawn": CombatEventType.CARD_DRAWN,
    "mana_changed": CombatEventType.MANA_CHANGED,
    "fizzled": CombatEventType.FIZZLED,
    "stat_buffed": CombatEventType.STAT_BUFFED,
    "budget_modified": CombatEventType.BUDGET_MODIFIED,
}


def translate_engine_events(
    engine_events: list[EngineEvent],
    *,
    sequence_start: int = 1,
) -> list[CombatEvent]:
    """Факты хода → события клиента, с нумерацией и метками фазы/итерации."""
    events: list[CombatEvent] = []
    for offset, fact in enumerate(engine_events):
        event_type = _KIND_TO_TYPE.get(fact.kind)
        if event_type is None:
            raise ValueError(f"Engine fact kind {fact.kind!r} has no client mapping")
        events.append(
            CombatEvent(
                type=event_type,
                message=_message(fact),
                actor_id=_actor_id(fact),
                target_id=_target_id(fact),
                target_kind=_target_kind(fact),
                damage=fact.amount if fact.kind in ("attack", "damage") else None,
                from_position=_position(fact.from_cell),
                to_position=_position(fact.to_cell),
                before_hp=fact.before if fact.kind in _HP_KINDS else None,
                after_hp=fact.after if fact.kind in _HP_KINDS else None,
                sequence=sequence_start + offset,
                # micro_step хранит номер итерации фазы 4 (спавны/спеллы = 0,
                # как в MVP-контракте); фаза уходит отдельным полем.
                micro_step=fact.iteration or 0,
                phase=fact.phase,
                ability_trigger=fact.trigger if fact.kind == "ability_triggered" else None,
                effect_kind=fact.effect_kind if fact.kind == "ability_triggered" else None,
                affected_cells=[Position(row=row, col=col) for row, col in fact.affected_cells],
                snapshot=fact.snapshot,
            )
        )
    return events


_HP_KINDS = frozenset({"attack", "damage", "heal", "killed", "unit_died"})

# Факты, где unit_id — «пострадавший», а не действующее лицо.
_TARGET_UNIT_KINDS = frozenset(
    {"damage", "heal", "status_applied", "status_expired", "stance_changed", "tag_granted",
     "killed", "stat_buffed", "budget_modified"}
)


def _actor_id(fact: EngineEvent) -> str | None:
    if fact.kind in _TARGET_UNIT_KINDS:
        return None
    if fact.kind in ("spell_cast", "card_drawn", "mana_changed"):
        return fact.player_id
    return fact.unit_id


def _target_id(fact: EngineEvent) -> str | None:
    if fact.kind in _TARGET_UNIT_KINDS:
        return fact.unit_id
    return fact.target_id


def _target_kind(fact: EngineEvent) -> CombatTargetKind | None:
    if fact.kind in _TARGET_UNIT_KINDS or fact.kind in ("attack", "collision"):
        return CombatTargetKind.UNIT
    if fact.kind == "fizzled":
        return CombatTargetKind.CELL
    return None


def _position(cell: tuple[int, int] | None) -> EventPosition | None:
    if cell is None:
        return None
    return EventPosition(row=cell[0], col=cell[1])


def _message(fact: EngineEvent) -> str:
    match fact.kind:
        case "attack":
            return f"{fact.unit_id} attacked {fact.target_id} for {fact.amount}"
        case "damage":
            return f"{fact.unit_id} took {fact.amount} damage"
        case "heal":
            return f"{fact.unit_id} healed {fact.amount} hp"
        case "moved":
            return f"{fact.unit_id} moved to {_cell_text(fact.to_cell)}"
        case "pushed":
            return f"{fact.unit_id} was pushed to {_cell_text(fact.to_cell)}"
        case "collision":
            return f"{fact.unit_id} collided with {fact.target_id}"
        case "unit_died":
            return f"{fact.unit_id} died"
        case "spawned" | "token_spawned":
            return f"{fact.player_id} spawned {fact.card_id} at {_cell_text(fact.to_cell)}"
        case "spell_cast":
            return f"{fact.player_id} cast {fact.card_id}"
        case "stance_changed":
            return f"{fact.unit_id} switched stance to {fact.stance}"
        case "status_applied":
            return f"{fact.unit_id} gained {fact.status_id} x{fact.amount}"
        case "status_expired":
            return f"{fact.status_id} expired on {fact.unit_id}"
        case "ability_triggered":
            return f"{fact.unit_id} triggered {fact.trigger}"
        case "tag_granted":
            return f"{fact.unit_id} gained tag {fact.tag}"
        case "killed":
            return f"{fact.unit_id} was executed"
        case "card_drawn":
            return f"{fact.player_id} drew a card"
        case "mana_changed":
            return f"{fact.player_id} mana {fact.before} -> {fact.after}"
        case "fizzled":
            return f"effect fizzled ({fact.card_id or fact.unit_id or fact.player_id})"
        case "stat_buffed":
            return f"{fact.unit_id} gained a permanent buff"
        case "budget_modified":
            return f"{fact.unit_id} action budget changed by {fact.amount}"
    raise ValueError(f"Engine fact kind {fact.kind!r} has no message")  # недостижимо


def _cell_text(cell: tuple[int, int] | None) -> str:
    return f"{cell[0]}:{cell[1]}" if cell else "?"
