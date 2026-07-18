"""Юниты v4: чертёж (данные карты) и рантайм-состояние на поле (ARCH §5.1).

Карта ≠ юнит (§10.7): CardDefinition ссылается на UnitBlueprint по id. Башни —
тоже юниты (D1/§17): blueprint с вечной Защитой, attacks_per_turn и тегами
structure/tower/immovable. abilities у чертежа появятся вместе со словарём
эффектов (P2.9) — сущности не тянут недостроенные куски.
"""

from pydantic import BaseModel, Field, field_validator

from app.domain.combat.engine.abilities import Ability
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


class StatsOverride(BaseModel):
    """Стойко-зависимые статы (§14.1 Эпик Серёга: урон 5 в Защите / 3 в Атаке).

    Частичный оверрайд поверх базовых статов чертежа; None = поле не меняется.
    HP намеренно нет: смена стойки не должна дёргать максимум здоровья.
    """

    model_config = {"frozen": True}

    damage: int | None = Field(default=None, ge=0)
    attacks_per_turn: int | None = Field(default=None, ge=0)
    move_steps: int | None = Field(default=None, ge=0)


class StatBonus(BaseModel):
    """Перманентные бафы юнита (buff_stats): копятся на UnitState."""

    hp: int = Field(default=0, ge=0)
    damage: int = Field(default=0, ge=0)
    attacks_per_turn: int = Field(default=0, ge=0)
    move_steps: int = Field(default=0, ge=0)


class UnitBlueprint(BaseModel):
    model_config = {"frozen": True}

    id: str
    name: str
    stats: UnitStats
    # Оверрайд статов в стойке Защита (базовые статы = стойка Атака);
    # по аналогии с per-stance покрытиями (§10.4).
    stats_defense: StatsOverride | None = None
    stance_program: StanceProgram
    # Покрытие зависит от стойки (§10.4): у снайпера в Защите зона шире.
    # Пустой паттерн легален — «не атакует» (Матеша).
    coverage_defense: CellPattern = CellPattern()
    coverage_attack: CellPattern = CellPattern()
    spawn_zone: SpawnZone
    tags: tuple[str, ...] = ()
    abilities: tuple[Ability, ...] = ()

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
    # Ряд −1 (верх) и rows (низ) — «призрачные» клетки башен за краем поля
    # (§17); обычный юнит туда попасть не может (validate_state следит).
    row: int = Field(ge=-1)
    col: int = Field(ge=0)
    # Потолка HP нет (Q4): лечение может поднять выше базового. Отрицательные
    # значения легальны ВНУТРИ итерации (C3: HP живёт, смерть проверяется
    # только на границе итерации волной C5).
    current_hp: int
    # Q5: казнённый (kill_if) умирает наверняка — волна смертей убивает
    # помеченных независимо от HP, лечение не спасает.
    doomed: bool = False
    # Ходов на поле, включая ход постановки (= 1 в ход спавна, D4).
    turns_on_field: int = Field(ge=1)
    # Бюджеты действий на ход; резолвер сбрасывает их из статов чертежа в
    # начале фазы итераций.
    remaining_steps: int = Field(default=0, ge=0)
    remaining_attacks: int = Field(default=0, ge=0)
    # Наложенная стойка — максимум одна: apply_forced_stance перезаписывает
    # предыдущую (Q2, решение владельца).
    statuses: list[Status] = Field(default_factory=list)
    # Перманентные бафы (buff_stats): учитываются в effective_stats.
    permanent_bonuses: StatBonus = Field(default_factory=StatBonus)
    # Теги, выданные эффектами в бою (grant_tag) — поверх базовых тегов
    # чертежа; итог считает unit_tags().
    granted_tags: tuple[str, ...] = ()

    @field_validator("granted_tags")
    @classmethod
    def _check_granted_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        return validate_tags(tags)


def spawn_unit(
    blueprint: UnitBlueprint,
    *,
    unit_id: str,
    owner_id: str,
    side: PlayerSide,
    row: int,
    col: int,
) -> UnitState:
    unit = UnitState(
        id=unit_id,
        blueprint_id=blueprint.id,
        owner_id=owner_id,
        side=side,
        row=row,
        col=col,
        current_hp=blueprint.stats.hp,
        turns_on_field=1,
    )
    # Бюджеты хода выдаются сразу: юнит действует уже в ход постановки (D4).
    # Резолвер обновляет их в начале каждого следующего хода.
    stats = effective_stats(unit, blueprint)
    unit.remaining_steps = stats.move_steps
    unit.remaining_attacks = stats.attacks_per_turn
    return unit


def unit_tags(unit: UnitState, blueprint: UnitBlueprint) -> frozenset[str]:
    """Итоговые теги юнита: базовые (чертёж) + выданные в бою (grant_tag)."""
    return frozenset(blueprint.tags) | frozenset(unit.granted_tags)


def effective_stats(unit: UnitState, blueprint: UnitBlueprint) -> UnitStats:
    """ЕДИНСТВЕННАЯ точка чтения статов юнита (ARCH §5.1, расширение №3).

    База чертежа → оверрайд текущей стойки (stats_defense) → перманентные
    бафы. Прямое чтение blueprint.stats в резолвере/эффектах — баг: оно
    молча игнорирует стойку и бафы.
    """
    base = blueprint.stats
    damage, attacks, steps = base.damage, base.attacks_per_turn, base.move_steps
    if blueprint.stats_defense is not None and current_stance(unit, blueprint) == Stance.DEFENSE:
        override = blueprint.stats_defense
        damage = override.damage if override.damage is not None else damage
        attacks = (
            override.attacks_per_turn if override.attacks_per_turn is not None else attacks
        )
        steps = override.move_steps if override.move_steps is not None else steps
    bonus = unit.permanent_bonuses
    return UnitStats(
        hp=base.hp + bonus.hp,
        damage=damage + bonus.damage,
        attacks_per_turn=attacks + bonus.attacks_per_turn,
        move_steps=steps + bonus.move_steps,
    )


def stance_turns_left(unit: UnitState, blueprint: UnitBlueprint) -> int | None:
    """V6: ходов (включая текущий) до САМОСТОЯТЕЛЬНОЙ смены текущей стойки.

    None = стойка сама не сменится (вечная фаза программы или наложение без
    срока). Viewer-safe производное для UI: клиент показывает число на иконке
    стойки и не вычисляет его сам (то же правило, что у unit_waited/U1).
    Наложенная стойка маскирует программу — остаток равен её ttl.
    """
    for status in reversed(unit.statuses):
        if status.id == STATUS_FORCED_STANCE:
            return status.ttl  # None = наложена без срока
    remaining = unit.turns_on_field
    for phase in blueprint.stance_program.phases:
        if phase.turns is None:
            return None
        if remaining <= phase.turns:
            return phase.turns - remaining + 1
        remaining -= phase.turns
    raise AssertionError("unreachable: final phase is open-ended")


def current_stance(unit: UnitState, blueprint: UnitBlueprint) -> Stance:
    """Текущая стойка — производное, не хранимое поле (ARCH §5.1, Q3).

    Активное наложение (после Q2-перезаписи оно максимум одно) маскирует
    врождённую программу; нет наложений — то, что программа говорит для
    текущего turns_on_field (F1). Стойка есть всегда: функция тотальна для
    любого живого юнита. Скан с конца — защита на случай состояния, собранного
    мимо apply_forced_stance: побеждает последнее наложение.
    """
    for status in reversed(unit.statuses):
        if status.id == STATUS_FORCED_STANCE:
            assert status.stance is not None  # гарантировано валидатором Status
            return status.stance
    return blueprint.stance_program.stance_at(unit.turns_on_field)
