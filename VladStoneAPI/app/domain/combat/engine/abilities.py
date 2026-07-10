"""Способности юнитов и скрипты заклинаний — данные (ARCH §5.1).

Ability вешается на UnitBlueprint и срабатывает на хуке конвейера резолвера;
SpellScript — то же самое для карты-заклинания (последовательность
«эффект + цели», отыгрывается в спелл-фазе в submission-порядке, C1).
Подписка хуков на фазы (I4) — в резолвере (P2.10); здесь только формы.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.combat.engine.effects import Effect
from app.domain.combat.engine.targeting import TargetSelector


class TriggerHook(StrEnum):
    """Хуки конвейера (ARCH §5.1); маппинг на фазы хода — I4 (P2.10)."""

    ON_SPAWN = "on_spawn"
    ON_TURN_START = "on_turn_start"
    ON_ATTACK = "on_attack"
    ON_DAMAGED = "on_damaged"
    ON_DEATH = "on_death"
    ON_TURN_END = "on_turn_end"
    ON_STANCE_CHANGE = "on_stance_change"


class Ability(BaseModel):
    model_config = {"frozen": True}

    trigger: TriggerHook
    effect: Effect
    # Зона способности считается от клетки юнита-носителя.
    target: TargetSelector


class SpellAction(BaseModel):
    model_config = {"frozen": True}

    effect: Effect
    # Зона действия считается от клетки, выбранной игроком при касте
    # (для scope="board" точка применения не нужна).
    target: TargetSelector


class SpellScript(BaseModel):
    model_config = {"frozen": True}

    id: str
    actions: tuple[SpellAction, ...] = Field(min_length=1)
