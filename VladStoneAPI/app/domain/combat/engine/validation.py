"""Валидация контента при загрузке (I7): падать на сиде, не в бою.

Модели уже ловят локальные противоречия (теги вне реестра, формы статусов) на
конструировании; здесь — проверки, требующие контекста: границы поля и
целостность ссылок карта → чертёж/скрипт.
"""

from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.units import UnitBlueprint


def validate_blueprint(blueprint: UnitBlueprint, *, rows: int, cols: int) -> None:
    """Чертёж обязан помещаться в конкретную конфигурацию поля."""
    for row in blueprint.spawn_zone.rows_from_back:
        if row > rows:
            raise ValueError(
                f"Blueprint {blueprint.id!r}: spawn row {row} is outside a {rows}-row board"
            )
    for pattern_name in ("coverage_defense", "coverage_attack"):
        for offset in getattr(blueprint, pattern_name).offsets:
            if abs(offset.forward) >= rows or abs(offset.col) >= cols:
                raise ValueError(
                    f"Blueprint {blueprint.id!r}: {pattern_name} offset "
                    f"({offset.forward}, {offset.col}) can never land on a "
                    f"{rows}x{cols} board"
                )


def validate_card(
    card: CardDefinition,
    *,
    blueprints: dict[str, UnitBlueprint],
    spells: set[str] | None = None,
) -> None:
    """Ссылочная целостность карты: чертёж/скрипт существуют."""
    if card.card_type == CardType.UNIT and card.blueprint_id not in blueprints:
        raise ValueError(f"Card {card.id!r} references unknown blueprint {card.blueprint_id!r}")
    if card.card_type == CardType.SPELL and card.spell_id not in (spells or set()):
        raise ValueError(f"Card {card.id!r} references unknown spell {card.spell_id!r}")
