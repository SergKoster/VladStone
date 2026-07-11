"""Паттерны клеток: покрытия атак и зоны спавна (COMBAT_REWORK §9.1, §13.2).

Система координат смещений — решение H7: поле НЕ поворачивается, поэтому
лево/право абсолютны и одинаковы для обоих игроков; относительно стороны
юнита — только «вперёд/назад». Смещение (forward, col): forward > 0 — к
врагу, col — абсолютное смещение колонки (минус = левее для ОБОИХ).
Сервер хранит абсолютные координаты; зеркало — чисто клиентский рендер.
"""

from pydantic import BaseModel, Field, field_validator

from app.domain.combat.models import PlayerSide


def forward_direction(side: PlayerSide) -> int:
    """+1 к росту номера ряда для TOP (идёт вниз), −1 для BOTTOM (идёт вверх)."""
    return 1 if side == PlayerSide.TOP else -1


class CellOffset(BaseModel):
    model_config = {"frozen": True}

    forward: int
    col: int


class CellPattern(BaseModel):
    model_config = {"frozen": True}

    offsets: tuple[CellOffset, ...] = ()

    @field_validator("offsets")
    @classmethod
    def _sorted_unique(cls, offsets: tuple[CellOffset, ...]) -> tuple[CellOffset, ...]:
        # Deterministic serialization (I3): canonical order, no duplicates.
        unique = {(offset.forward, offset.col) for offset in offsets}
        return tuple(CellOffset(forward=fwd, col=col) for fwd, col in sorted(unique))

    def resolve(
        self,
        *,
        row: int,
        col: int,
        side: PlayerSide,
        rows: int,
        cols: int,
    ) -> list[tuple[int, int]]:
        """Абсолютные клетки паттерна от позиции юнита; вне поля — отрезаются.

        Ряды −1 и rows — «призрачные» клетки башен (§17): покрытия и зоны
        эффектов до них ДОТЯГИВАЮТСЯ (иначе башни недосягаемы), а правила
        движения/спавна работают по строгим границам поля и не пускают туда
        юнитов. Порядок результата — канонический (по чтению поля: ряд,
        колонка), тот же тайбрейк, что и у всего боя (ARCH §5.1).
        """
        direction = forward_direction(side)
        cells = set()
        for offset in self.offsets:
            target_row = row + offset.forward * direction
            target_col = col + offset.col
            if -1 <= target_row <= rows and 0 <= target_col < cols:
                cells.add((target_row, target_col))
        return sorted(cells)


class SpawnZone(BaseModel):
    """Зона розыгрыша карты (§13.2): ряды, считая от своего края (1 = задний).

    «Ряды 1–2» у обычных карт, «ряды 1–3» у Мегарыцаря и т.п. Спец-зоны вроде
    «на вражеского юнита» (Ассасин) — не зона, а механика карты; появятся
    вместе со словарём эффектов (P2.9).
    """

    model_config = {"frozen": True}

    rows_from_back: tuple[int, ...] = Field(min_length=1)

    @field_validator("rows_from_back")
    @classmethod
    def _sorted_unique(cls, rows: tuple[int, ...]) -> tuple[int, ...]:
        if any(row < 1 for row in rows):
            raise ValueError("Spawn zone rows are 1-based from the owner's back edge")
        return tuple(sorted(set(rows)))

    def resolve(self, *, side: PlayerSide, rows: int) -> list[int]:
        """Абсолютные номера рядов зоны для данной стороны поля."""
        if side == PlayerSide.TOP:
            absolute = [row - 1 for row in self.rows_from_back]
        else:
            absolute = [rows - row for row in self.rows_from_back]
        return sorted(row for row in absolute if 0 <= row < rows)
