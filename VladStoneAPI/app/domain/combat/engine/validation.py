"""Валидация контента при загрузке (I7): падать на сиде, не в бою.

Модели уже ловят локальные противоречия (теги вне реестра, формы статусов и
эффектов) на конструировании; здесь — проверки, требующие контекста: границы
поля и целостность ссылок карта → чертёж/скрипт.
"""

from app.domain.combat.engine.abilities import SpellScript
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.patterns import CellPattern
from app.domain.combat.engine.units import UnitBlueprint


def _check_pattern_bounds(pattern: CellPattern, *, owner: str, name: str, rows: int, cols: int):
    for offset in pattern.offsets:
        if abs(offset.forward) >= rows or abs(offset.col) >= cols:
            raise ValueError(
                f"{owner}: {name} offset ({offset.forward}, {offset.col}) "
                f"can never land on a {rows}x{cols} board"
            )


def validate_blueprint(blueprint: UnitBlueprint, *, rows: int, cols: int) -> None:
    """Чертёж обязан помещаться в конкретную конфигурацию поля."""
    for row in blueprint.spawn_zone.rows_from_back:
        if row > rows:
            raise ValueError(
                f"Blueprint {blueprint.id!r}: spawn row {row} is outside a {rows}-row board"
            )
    owner = f"Blueprint {blueprint.id!r}"
    _check_pattern_bounds(
        blueprint.coverage_defense, owner=owner, name="coverage_defense", rows=rows, cols=cols
    )
    _check_pattern_bounds(
        blueprint.coverage_attack, owner=owner, name="coverage_attack", rows=rows, cols=cols
    )
    for index, ability in enumerate(blueprint.abilities):
        if ability.target.pattern is not None:
            _check_pattern_bounds(
                ability.target.pattern,
                owner=owner,
                name=f"abilities[{index}].target",
                rows=rows,
                cols=cols,
            )


def validate_spell_script(script: SpellScript, *, rows: int, cols: int) -> None:
    for index, action in enumerate(script.actions):
        if action.target.pattern is not None:
            _check_pattern_bounds(
                action.target.pattern,
                owner=f"Spell {script.id!r}",
                name=f"actions[{index}].target",
                rows=rows,
                cols=cols,
            )


def validate_card(
    card: CardDefinition,
    *,
    blueprints: dict[str, UnitBlueprint],
    spells: dict[str, SpellScript] | None = None,
) -> None:
    """Ссылочная целостность карты: чертёж/скрипт существуют."""
    if card.card_type == CardType.UNIT and card.blueprint_id not in blueprints:
        raise ValueError(f"Card {card.id!r} references unknown blueprint {card.blueprint_id!r}")
    if card.card_type == CardType.SPELL and card.spell_id not in (spells or {}):
        raise ValueError(f"Card {card.id!r} references unknown spell {card.spell_id!r}")
