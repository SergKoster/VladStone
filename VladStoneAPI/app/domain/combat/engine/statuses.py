"""Статусы юнитов (ARCH §5.1): один механизм для яда, щитов И наложенных стоек.

Наложенная заклинанием стойка — это статус forced_stance с ttl (E4): пока он
активен, он маскирует врождённую программу; истёк — юнит возвращается к тому,
что программа говорит СЕЙЧАС (F1). Id статусов — из реестра (та же логика,
что у тегов F6): неизвестный статус падает на загрузке, не в бою.
"""

from pydantic import BaseModel, Field, model_validator

from app.domain.combat.engine.stances import Stance

STATUS_POISON = "poison"
STATUS_FORCED_STANCE = "forced_stance"

KNOWN_STATUSES: frozenset[str] = frozenset({STATUS_POISON, STATUS_FORCED_STANCE})


class Status(BaseModel):
    id: str
    stacks: int = Field(default=1, ge=1)
    # Остаток ходов действия; декрементится ЕДИНООБРАЗНО в фазе конца хода
    # (I4), поэтому «на 1 ход» значит одно и то же для всех статусов.
    # None = постоянный (не тикает).
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
    """Один тик конца хода (I4): ttl −1, истёкшие статусы уходят.

    Статус с ttl=1 активен весь ход наложения и исчезает на его границе —
    «на 1 ход» = до конца текущего хода.
    """
    survivors: list[Status] = []
    for status in statuses:
        if status.ttl is None:
            survivors.append(status)
            continue
        if status.ttl > 1:
            survivors.append(status.model_copy(update={"ttl": status.ttl - 1}))
    return survivors
