"""Боевой движок v4 (COMBAT_REWORK §10–§20, ARCH §5.1) — строится рядом с MVP.

Пока резолвер v4 не готов, живой бой обслуживает старый код в
app/domain/combat/*; этот пакет ни во что боевое не включён. Подмена — в конце
P2 вместе с bump'ом RULESET_VERSION.
"""

from app.domain.combat.engine.abilities import (
    Ability,
    SpellAction,
    SpellScript,
    TriggerHook,
)
from app.domain.combat.engine.apply import (
    HAND_CAP,
    EffectContext,
    EngineEvent,
    apply_effect,
    select_targets,
)
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.effects import (
    ApplyStatus,
    ChangeStance,
    DealDamage,
    DrawCard,
    Effect,
    GrantTag,
    Heal,
    KillIf,
    ModifyMana,
    Push,
    SpawnToken,
)
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.patterns import CellOffset, CellPattern, SpawnZone
from app.domain.combat.engine.resolver import resolve_turn_v4, run_death_wave
from app.domain.combat.engine.stances import Stance, StancePhase, StanceProgram
from app.domain.combat.engine.statuses import (
    STATUS_FORCED_STANCE,
    STATUS_POISON,
    Status,
    apply_forced_stance,
    tick_statuses,
)
from app.domain.combat.engine.tags import (
    KNOWN_TAGS,
    TAG_IMMOVABLE,
    TAG_STRUCTURE,
    TAG_TOWER,
)
from app.domain.combat.engine.targeting import TargetSelector, TargetSide
from app.domain.combat.engine.units import (
    UnitBlueprint,
    UnitState,
    UnitStats,
    current_stance,
    spawn_unit,
    unit_tags,
)
from app.domain.combat.engine.validation import (
    validate_blueprint,
    validate_card,
    validate_spell_script,
)

__all__ = [
    "HAND_CAP",
    "KNOWN_TAGS",
    "STATUS_FORCED_STANCE",
    "STATUS_POISON",
    "TAG_IMMOVABLE",
    "TAG_STRUCTURE",
    "TAG_TOWER",
    "Ability",
    "ApplyStatus",
    "CardDefinition",
    "CardType",
    "CellOffset",
    "CellPattern",
    "ChangeStance",
    "DealDamage",
    "DrawCard",
    "Effect",
    "EffectContext",
    "EngineEvent",
    "GrantTag",
    "Heal",
    "KillIf",
    "ModifyMana",
    "PlayerIntents",
    "Push",
    "SpawnIntent",
    "SpawnToken",
    "SpawnZone",
    "SpellAction",
    "SpellIntent",
    "SpellScript",
    "Stance",
    "StancePhase",
    "StanceProgram",
    "Status",
    "TargetSelector",
    "TargetSide",
    "TriggerHook",
    "UnitBlueprint",
    "UnitState",
    "UnitStats",
    "apply_effect",
    "apply_forced_stance",
    "current_stance",
    "resolve_turn_v4",
    "run_death_wave",
    "select_targets",
    "spawn_unit",
    "tick_statuses",
    "unit_tags",
    "validate_blueprint",
    "validate_card",
    "validate_spell_script",
]
