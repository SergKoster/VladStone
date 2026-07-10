"""Стойки и врождённая программа стойки (COMBAT_REWORK §10, §18.1, §18.6).

Стоек ровно две (решение v3): Защита (стоит и бьёт по своему покрытию) и
Атака (идёт вперёд). Программа стойки — публичное расписание карты:
«Защита N ходов → Атака» (разогрев, анти-стена H5) или «Атака 2 → Защита»
(катапульта). Текущая стойка юнита НЕ хранится как поле-истина — она
выводится чистой функцией (см. units.current_stance), чтобы «застрявшая
стойка» была невозможна by design (ARCH §5.1).
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Stance(StrEnum):
    DEFENSE = "defense"
    ATTACK = "attack"


class StancePhase(BaseModel):
    model_config = {"frozen": True}

    stance: Stance
    # None = фаза длится до конца боя; допустима только у последней фазы.
    turns: int | None = Field(default=None, ge=1)


class StanceProgram(BaseModel):
    model_config = {"frozen": True}

    phases: tuple[StancePhase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _last_phase_is_infinite(self) -> "StanceProgram":
        for phase in self.phases[:-1]:
            if phase.turns is None:
                raise ValueError("Only the final stance phase may be open-ended (turns=None)")
        if self.phases[-1].turns is not None:
            raise ValueError("The final stance phase must be open-ended (turns=None)")
        return self

    @classmethod
    def always(cls, stance: Stance) -> "StanceProgram":
        return cls(phases=(StancePhase(stance=stance),))

    @classmethod
    def warmup(cls, defense_turns: int) -> "StanceProgram":
        """«Разогрев» §18.1: Защита N ходов, затем Атака до конца боя."""
        return cls(
            phases=(
                StancePhase(stance=Stance.DEFENSE, turns=defense_turns),
                StancePhase(stance=Stance.ATTACK),
            )
        )

    def stance_at(self, turns_on_field: int) -> Stance:
        """Врождённая стойка на N-м ходу на поле.

        Ход постановки считается первым ходом программы (D4, §18.5): юнит с
        разогревом «Защита 2» стоит в Защите в ход спавна и следующий, с
        третьего хода — Атака. Расписание фиксировано от спавна; наложенные
        стойки его лишь маскируют (F1), сам счётчик не сдвигают.
        """
        if turns_on_field < 1:
            raise ValueError("turns_on_field counts from 1 (the spawn turn, D4)")
        remaining = turns_on_field
        for phase in self.phases:
            if phase.turns is None or remaining <= phase.turns:
                return phase.stance
            remaining -= phase.turns
        raise AssertionError("unreachable: final phase is open-ended")
