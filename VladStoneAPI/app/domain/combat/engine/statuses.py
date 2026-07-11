"""Статусы юнитов (ARCH §5.1): один механизм для яда, клейм И наложенных стоек.

Каждый статус описан строкой-спецификацией StatusSpec (ARCH §5.1 «Расширения
под батч №1» п.2): способ затухания (по ходам / по стакам / вечный), тик
конца хода (урон/лечение) и опциональный квест-блок «условие → награда/кара»
(п.7). Новый статус = строка таблицы, не код. Наложенная заклинанием стойка —
статус forced_stance с ttl (E4): пока активен, маскирует врождённую программу
(F1). Неизвестный статус падает на конструировании, не в бою (F6-логика).
"""

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from app.domain.combat.engine.stances import Stance

if TYPE_CHECKING:  # только для аннотаций: словарь эффектов импортирует статусы
    from app.domain.combat.engine.effects import Effect

STATUS_POISON = "poison"
STATUS_FORCED_STANCE = "forced_stance"
STATUS_ZADANIE_MARK = "zadanie_mark"


class StatusDecay(StrEnum):
    # Затухает по ttl: −1 в фазе конца хода, 0 — снятие (клеймо, стойка).
    TTL = "ttl"
    # Затухает по стакам: тик снимает 1 стак (новый канон яда §14.1).
    STACKS = "stacks"
    # Не затухает (вечная наложенная стойка).
    PERMANENT = "permanent"


class QuestCondition(StrEnum):
    """Словарь квест-условий — фиксированный, как словарь эффектов."""

    ATTACKED_UNIT_THAT_DIED_THIS_TURN = "attacked_unit_that_died_this_turn"


class QuestSpec(BaseModel):
    """Квест-блок статуса (§14.1 «Задание»): проверяется в фазе конца хода.

    Выполнил условие в любой ход, пока клеймо висит, — награда и клеймо
    снимается; клеймо истекло без выполнения — кара.
    """

    model_config = {"frozen": True}

    condition: QuestCondition
    on_success: tuple["Effect", ...] = ()
    on_fail: tuple["Effect", ...] = ()


class StatusSpec(BaseModel):
    model_config = {"frozen": True}

    id: str
    decay: StatusDecay
    # Тик конца хода (фаза 5): урон/лечение носителю. Яд = tick_damage 1.
    tick_damage: int = Field(default=0, ge=0)
    tick_heal: int = Field(default=0, ge=0)
    quest: QuestSpec | None = None


def _build_specs() -> dict[str, StatusSpec]:
    # Импорт эффектов внутри: словарь эффектов сам импортирует реестр статусов.
    from app.domain.combat.engine import effects

    QuestSpec.model_rebuild(_types_namespace={"Effect": effects.Effect}, force=True)
    BuffStats, Execute = effects.BuffStats, effects.Execute

    specs = {
        spec.id: spec
        for spec in (
            # Новый канон яда (§14.1): в конце хода −1 HP И −1 стак;
            # Яд N = N ходов по 1 урона. Стаки складываются.
            StatusSpec(id=STATUS_POISON, decay=StatusDecay.STACKS, tick_damage=1),
            StatusSpec(id=STATUS_FORCED_STANCE, decay=StatusDecay.TTL),
            # «Задание» (§14.1): клеймо на 1 ход; убил цель своей атакой в
            # этот ход — +3 HP и +1 атака навсегда; нет — казнь.
            StatusSpec(
                id=STATUS_ZADANIE_MARK,
                decay=StatusDecay.TTL,
                quest=QuestSpec(
                    condition=QuestCondition.ATTACKED_UNIT_THAT_DIED_THIS_TURN,
                    on_success=(BuffStats(hp=3, attacks_per_turn=1),),
                    on_fail=(Execute(),),
                ),
            ),
        )
    }
    # Плоский реестр и таблица спек обязаны совпадать — рассинхрон = баг.
    assert set(specs) == set(KNOWN_STATUSES), "KNOWN_STATUSES != status spec table"
    return specs


_STATUS_SPECS: dict[str, StatusSpec] | None = None


def status_spec(status_id: str) -> StatusSpec:
    global _STATUS_SPECS
    if _STATUS_SPECS is None:
        _STATUS_SPECS = _build_specs()
    return _STATUS_SPECS[status_id]


def known_statuses() -> frozenset[str]:
    global _STATUS_SPECS
    if _STATUS_SPECS is None:
        _STATUS_SPECS = _build_specs()
    return frozenset(_STATUS_SPECS)


# Плоский реестр для валидаторов, которым не нужны спеки.
KNOWN_STATUSES: frozenset[str] = frozenset(
    {STATUS_POISON, STATUS_FORCED_STANCE, STATUS_ZADANIE_MARK}
)


class Status(BaseModel):
    id: str
    stacks: int = Field(default=1, ge=1)
    # Остаток ходов действия; декрементится ЕДИНООБРАЗНО в фазе конца хода
    # (I4), поэтому «на 1 ход» значит одно и то же для всех статусов.
    # None = постоянный (не тикает). Только для статусов с decay=ttl.
    ttl: int | None = Field(default=None, ge=1)
    # Полезная нагрузка forced_stance: в какую стойку переведён юнит.
    stance: Stance | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "Status":
        if self.id not in KNOWN_STATUSES:
            raise ValueError(f"Unknown status {self.id!r}; register it in engine/statuses.py")
        if self.id == STATUS_FORCED_STANCE and self.stance is None:
            raise ValueError("forced_stance status requires a stance payload")
        if self.id != STATUS_FORCED_STANCE and self.stance is not None:
            raise ValueError(f"Status {self.id!r} must not carry a stance payload")
        if self.ttl is not None and status_spec(self.id).decay != StatusDecay.TTL:
            raise ValueError(f"Status {self.id!r} decays by {status_spec(self.id).decay}, not ttl")
        return self


def apply_forced_stance(
    statuses: list[Status],
    *,
    stance: Stance,
    ttl: int | None,
) -> list[Status]:
    """Наложить стойку с перезаписью (Q2, решение владельца июль 2026).

    Новое наложение СТИРАЕТ предыдущее — стека нет, активно максимум одно;
    истекло — юнит сразу возвращается к врождённой программе. «Воскресающих»
    старых наложений не бывает, исход считается в уме (A3).
    """
    survivors = [status for status in statuses if status.id != STATUS_FORCED_STANCE]
    survivors.append(Status(id=STATUS_FORCED_STANCE, ttl=ttl, stance=stance))
    return survivors


def tick_statuses(statuses: list[Status]) -> list[Status]:
    """Один тик конца хода (I4): затухание по спеке статуса.

    decay=ttl: −1, истёкшие уходят («на 1 ход» = до конца текущего хода);
    decay=stacks: −1 стак, 0 — снятие (яд §14.1); permanent: не тикает.
    Тиковый урон/лечение применяет резолвер ДО затухания (фаза 5) — эта
    функция чистая, только структура списка. Полноценное конструирование
    (не model_copy) прогоняет валидаторы — битый статус тик не переживёт.
    """
    survivors: list[Status] = []
    for status in statuses:
        spec = status_spec(status.id)
        if spec.decay == StatusDecay.PERMANENT:
            survivors.append(status)
        elif spec.decay == StatusDecay.STACKS:
            if status.stacks > 1:
                survivors.append(
                    Status(id=status.id, stacks=status.stacks - 1, stance=status.stance)
                )
        elif status.ttl is None:
            survivors.append(status)  # ttl-статус без срока = постоянный
        elif status.ttl > 1:
            survivors.append(
                Status(id=status.id, stacks=status.stacks, ttl=status.ttl - 1, stance=status.stance)
            )
    return survivors
