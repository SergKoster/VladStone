"""Селектор целей (ARCH §5.1): зона + фильтры, отбирающие юнитов в ней.

Заклинания и способности таргетят по клетке/зоне (§13.2): игрок выбирает
точку применения, селектор описывает зону вокруг неё и кого в зоне считать
целью. По умолчанию side=ANY — friendly fire (E2): эффекты бьют и своих,
конкретные карты сужают фильтр (enemy/ally/тег).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.domain.combat.engine.patterns import CellPattern
from app.domain.combat.engine.tags import KNOWN_TAGS


class TargetSide(StrEnum):
    ANY = "any"
    ALLY = "ally"
    ENEMY = "enemy"


class TargetSelector(BaseModel):
    model_config = {"frozen": True}

    # cell — только выбранная клетка; pattern — зона вокруг неё (развёртка по
    # стороне кастера, H7); board — всё поле, точка применения не нужна.
    scope: Literal["cell", "pattern", "board"] = "cell"
    pattern: CellPattern | None = None
    side: TargetSide = TargetSide.ANY
    tag: str | None = None

    @field_validator("tag")
    @classmethod
    def _tag_from_registry(cls, tag: str | None) -> str | None:
        if tag is not None and tag not in KNOWN_TAGS:
            raise ValueError(f"Unknown target tag {tag!r}; register it in engine/tags.py")
        return tag

    @model_validator(mode="after")
    def _pattern_matches_scope(self) -> "TargetSelector":
        if self.scope == "pattern" and self.pattern is None:
            raise ValueError("scope='pattern' requires a pattern")
        if self.scope != "pattern" and self.pattern is not None:
            raise ValueError(f"scope={self.scope!r} must not carry a pattern")
        return self
