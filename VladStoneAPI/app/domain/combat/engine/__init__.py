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
from app.domain.combat.engine.bot import plan_bot_intents
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
from app.domain.combat.engine.towers import (
    TOWER_BLUEPRINT,
    TOWER_HP,
    add_towers,
    all_teams_eliminated,
    ghost_row,
    run_judgement,
    towers_of,
    winner_team_by_towers,
)
from app.domain.combat.engine.translate import translate_engine_events
from app.domain.combat.engine.units import (
    UnitBlueprint,
    UnitState,
    UnitStats,
    current_stance,
    spawn_unit,
    unit_tags,
)
from app.domain.combat.engine.validation import (
    StateValidationError,
    canonical_units_json,
    validate_blueprint,
    validate_card,
    validate_spell_script,
    validate_state,
)

__all__ = [
    "HAND_CAP",
    "KNOWN_TAGS",
    "STATUS_FORCED_STANCE",
    "STATUS_POISON",
    "TAG_IMMOVABLE",
    "TAG_STRUCTURE",
    "TAG_TOWER",
    "TOWER_BLUEPRINT",
    "TOWER_HP",
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
    "StateValidationError",
    "Status",
    "TargetSelector",
    "TargetSide",
    "TriggerHook",
    "UnitBlueprint",
    "UnitState",
    "UnitStats",
    "add_towers",
    "all_teams_eliminated",
    "apply_effect",
    "apply_forced_stance",
    "canonical_units_json",
    "current_stance",
    "ghost_row",
    "plan_bot_intents",
    "resolve_turn_v4",
    "run_death_wave",
    "run_judgement",
    "select_targets",
    "spawn_unit",
    "tick_statuses",
    "towers_of",
    "winner_team_by_towers",
    "translate_engine_events",
    "unit_tags",
    "validate_blueprint",
    "validate_card",
    "validate_spell_script",
    "validate_state",
]
