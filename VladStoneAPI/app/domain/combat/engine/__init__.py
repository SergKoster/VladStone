"""Боевой движок v4 (COMBAT_REWORK §10–§20, ARCH §5.1) — строится рядом с MVP.

Пока резолвер v4 не готов, живой бой обслуживает старый код в
app/domain/combat/*; этот пакет ни во что боевое не включён. Подмена — в конце
P2 вместе с bump'ом RULESET_VERSION.
"""

from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.patterns import CellOffset, CellPattern, SpawnZone
from app.domain.combat.engine.stances import Stance, StancePhase, StanceProgram
from app.domain.combat.engine.statuses import (
    STATUS_FORCED_STANCE,
    STATUS_POISON,
    Status,
    tick_statuses,
)
from app.domain.combat.engine.tags import (
    KNOWN_TAGS,
    TAG_IMMOVABLE,
    TAG_STRUCTURE,
    TAG_TOWER,
)
from app.domain.combat.engine.units import (
    UnitBlueprint,
    UnitState,
    UnitStats,
    current_stance,
    spawn_unit,
)
from app.domain.combat.engine.validation import validate_blueprint, validate_card

__all__ = [
    "KNOWN_TAGS",
    "STATUS_FORCED_STANCE",
    "STATUS_POISON",
    "TAG_IMMOVABLE",
    "TAG_STRUCTURE",
    "TAG_TOWER",
    "CardDefinition",
    "CardType",
    "CellOffset",
    "CellPattern",
    "SpawnZone",
    "Stance",
    "StancePhase",
    "StanceProgram",
    "Status",
    "UnitBlueprint",
    "UnitState",
    "UnitStats",
    "current_stance",
    "spawn_unit",
    "tick_statuses",
    "validate_blueprint",
    "validate_card",
]
