"""Юниты v4: чертёж (данные карты) и рантайм-состояние на поле (ARCH §5.1).

Карта ≠ юнит (§10.7): CardDefinition ссылается на UnitBlueprint по id. Башни —
тоже юниты (D1/§17): blueprint с вечной Защитой, attacks_per_turn и тегами
structure/tower/immovable. abilities у чертежа появятся вместе со словарём
эффектов (P2.9) — сущности не тянут недостроенные куски.
"""

from pydantic import BaseModel, Field, field_validator

from app.domain.combat.engine.patterns import CellPattern, SpawnZone
from app.domain.combat.engine.stances import Stance, StanceProgram
from app.domain.combat.engine.statuses import STATUS_FORCED_STANCE, Status
from app.domain.combat.engine.tags import validate_tags
from app.domain.combat.models import PlayerSide


class UnitStats(BaseModel):
    model_config = {"frozen": True}

    hp: int = Field(gt=0)
    damage: int = Field(ge=0)
    attacks_per_turn: int = Field(ge=0)
    move_steps: int = Field(ge=0)


class UnitBlueprint(BaseModel):
    model_config = {"frozen": True}

    id: str
    name: str
    stats: UnitStats
    stance_program: StanceProgram
    # Покрытие зависит от стойки (§10.4): у снайпера в Защите зона шире.
    # Пустой паттерн легален — «не атакует» (Матеша).
    coverage_defense: CellPattern = CellPattern()
    coverage_attack: CellPattern = CellPattern()
    spawn_zone: SpawnZone
    tags: tuple[str, ...] = ()

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        return validate_tags(tags)

    def coverage(self, stance: Stance) -> CellPattern:
        return self.coverage_defense if stance == Stance.DEFENSE else self.coverage_attack


class UnitState(BaseModel):
    id: str
    blueprint_id: str
    owner_id: str
    side: PlayerSide
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    # Потолка HP нет (Q4): лечение может поднять выше базового. Отрицательные
    # значения легальны ВНУТРИ итерации (C3: HP живёт, смерть проверяется
    # только на границе итерации волной C5).
    current_hp: int
    # Ходов на поле, включая ход постановки (= 1 в ход спавна, D4).
    turns_on_field: int = Field(ge=1)
    # Порядок наложения статусов значим: последняя активная forced_stance
    # побеждает (Q2, LIFO).
    statuses: list[Status] = Field(default_factory=list)


def spawn_unit(
    blueprint: UnitBlueprint,
    *,
    unit_id: str,
    owner_id: str,
    side: PlayerSide,
    row: int,
    col: int,
) -> UnitState:
    return UnitState(
        id=unit_id,
        blueprint_id=blueprint.id,
        owner_id=owner_id,
        side=side,
        row=row,
        col=col,
        current_hp=blueprint.stats.hp,
        turns_on_field=1,
    )


def current_stance(unit: UnitState, blueprint: UnitBlueprint) -> Stance:
    """Текущая стойка — производное, не хранимое поле (ARCH §5.1, Q3).

    Побеждает последняя активная наложенная стойка (Q2, LIFO); нет наложений —
    то, что врождённая программа говорит для текущего turns_on_field. Стойка
    есть всегда: функция тотальна для любого живого юнита.
    """
    for status in reversed(unit.statuses):
        if status.id == STATUS_FORCED_STANCE:
            assert status.stance is not None  # гарантировано валидатором Status
            return status.stance
    return blueprint.stance_program.stance_at(unit.turns_on_field)
