"""Намерения игроков на ход (v4): что каст, что ставим и куда.

Порядок в кортежах — submission-порядок игрока: внутри его спелл-подфазы
заклинания отыгрываются именно в нём (C1). Сервер валидирует намерения против
руки/маны при резолве — невалидные детерминированно физзлятся, не падают.
"""

from pydantic import BaseModel, Field, model_validator


class SpellIntent(BaseModel):
    model_config = {"frozen": True}

    card_id: str
    # Точка применения; None — для скриптов, которым она не нужна
    # (все селекторы scope="board").
    row: int | None = Field(default=None, ge=0)
    col: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _cell_is_whole(self) -> "SpellIntent":
        if (self.row is None) != (self.col is None):
            raise ValueError("Spell target cell needs both row and col (or neither)")
        return self


class SpawnIntent(BaseModel):
    model_config = {"frozen": True}

    card_id: str
    row: int = Field(ge=0)
    col: int = Field(ge=0)


class PlayerIntents(BaseModel):
    model_config = {"frozen": True}

    player_id: str
    spells: tuple[SpellIntent, ...] = ()
    spawns: tuple[SpawnIntent, ...] = ()
