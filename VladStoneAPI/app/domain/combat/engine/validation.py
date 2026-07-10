"""Валидация: контента — при загрузке (I7), состояния боя — после каждой фазы.

Модели уже ловят локальные противоречия (теги вне реестра, формы статусов и
эффектов) на конструировании; здесь — проверки, требующие контекста: границы
поля, целостность ссылок карта → чертёж/скрипт и инварианты состояния между
фазами резолвера (validate_state, ARCH §5.1): противоречие падает сразу у
источника с точным сообщением, а не багует через десять ходов.
"""

import json

from app.domain.combat.engine.abilities import SpellScript
from app.domain.combat.engine.apply import HAND_CAP, EffectContext
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.patterns import CellPattern
from app.domain.combat.engine.statuses import KNOWN_STATUSES, STATUS_FORCED_STANCE
from app.domain.combat.engine.tags import KNOWN_TAGS
from app.domain.combat.engine.units import UnitBlueprint, UnitState


class StateValidationError(ValueError):
    """Инвариант боевого состояния нарушен — баг движка/контента, не игрока."""


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


def validate_state(ctx: EffectContext, *, checkpoint: str = "") -> None:
    """Инварианты состояния на границе фазы (вызывается резолвером).

    Проверки рассчитаны на точки ПОСЛЕ волн смертей: живой юнит имеет hp > 0
    и не doomed (внутри итерации минус легален — там validate_state не
    зовут). checkpoint попадает в сообщение об ошибке — сразу видно, какая
    фаза сломала состояние.
    """
    where = f" [{checkpoint}]" if checkpoint else ""

    def fail(message: str) -> None:
        raise StateValidationError(f"{message}{where}")

    seen_ids: set[str] = set()
    seen_cells: set[tuple[int, int]] = set()
    for unit in ctx.units:
        if unit.id in seen_ids:
            fail(f"Duplicate unit id {unit.id!r}")
        seen_ids.add(unit.id)
        if unit.blueprint_id not in ctx.blueprints:
            fail(f"Unit {unit.id!r} references unknown blueprint {unit.blueprint_id!r}")
        if not (0 <= unit.row < ctx.rows and 0 <= unit.col < ctx.cols):
            fail(f"Unit {unit.id!r} is off-board at ({unit.row}, {unit.col})")
        cell = (unit.row, unit.col)
        if cell in seen_cells:
            fail(f"Two units share cell {cell}")
        seen_cells.add(cell)
        # Q4: верхней границы HP нет; на границе фазы мёртвых уже унесла волна.
        if unit.current_hp <= 0:
            fail(f"Unit {unit.id!r} survived a phase border with hp {unit.current_hp}")
        if unit.doomed:
            fail(f"Unit {unit.id!r} is doomed but survived a death wave")
        if unit.remaining_steps < 0 or unit.remaining_attacks < 0:
            fail(f"Unit {unit.id!r} has a negative action budget")
        if unit.turns_on_field < 1:
            fail(f"Unit {unit.id!r} has turns_on_field {unit.turns_on_field}")
        for tag in unit.granted_tags:
            if tag not in KNOWN_TAGS:
                fail(f"Unit {unit.id!r} carries unknown tag {tag!r}")
        for status in unit.statuses:
            if status.id not in KNOWN_STATUSES:
                fail(f"Unit {unit.id!r} carries unknown status {status.id!r}")
            if status.stacks < 1:
                fail(f"Unit {unit.id!r}: status {status.id!r} has stacks {status.stacks}")
            if status.ttl is not None and status.ttl < 1:
                fail(f"Unit {unit.id!r}: status {status.id!r} has ttl {status.ttl}")
            if (status.stance is None) == (status.id == STATUS_FORCED_STANCE):
                fail(f"Unit {unit.id!r}: status {status.id!r} has a malformed stance payload")

    for player in ctx.players:
        if not 0 <= player.mana <= ctx.mana_cap:
            fail(f"Player {player.id!r} has mana {player.mana} outside [0, {ctx.mana_cap}]")
        if len(player.hand) > HAND_CAP:
            fail(f"Player {player.id!r} holds {len(player.hand)} cards over the cap {HAND_CAP}")


def canonical_units_json(units: list[UnitState]) -> str:
    """Каноническая сериализация юнитов (I3): порядок списка не влияет.

    Резолвер нигде не зависит от порядка ctx.units (обходы сортируются по
    чтению поля), поэтому сохранённое состояние сортируем по id — реплей и
    дорезолв бит-в-бит воспроизводимы.
    """
    payload = [unit.model_dump(mode="json") for unit in sorted(units, key=lambda u: u.id)]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
