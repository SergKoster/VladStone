"""Бот v4 (I2): детерминированный планировщик легальных намерений.

Цель этапа — «хотя бы легально играющий» PvE-соперник под новые правила:
он не разбирается в комбо, но каждое его намерение проходит проверки
резолвера (мана, рука, зона спавна, занятость) и не физзлится. Тактика —
осознанная заглушка; ум наращивается после первого батча карт (P3),
когда будет что оценивать.

Детерминизм: чистая функция от контекста — одинаковый бой даёт одинаковый
план (реплей и дорезолв по таймеру совпадают бит-в-бит, I3).
"""

from app.domain.combat.engine.apply import EffectContext
from app.domain.combat.engine.cards import CardType
from app.domain.combat.engine.effects import Heal
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.tags import TAG_STRUCTURE
from app.domain.combat.engine.units import unit_tags
from app.domain.combat.models import PlayerSide


def plan_bot_intents(ctx: EffectContext, player_id: str) -> PlayerIntents:
    """Собрать намерения бота на ход: жадно, в стабильном порядке руки.

    Юнит-карты ставятся на ПУСТЫЕ клетки своей зоны спавна (толчки бот не
    планирует — проще гарантировать легальность), ряды — ближние к врагу
    первыми, колонки слева направо. Заклинания: лечащие — в своего юнита,
    остальные точечные — в клетку первого врага (по чтению поля); зональные
    (scope=board у всех действий) кастуются без точки.
    """
    player = ctx.player_by_id(player_id)
    mana_left = player.mana
    taken_cells = {(unit.row, unit.col) for unit in ctx.units}
    spawns: list[SpawnIntent] = []
    spells: list[SpellIntent] = []

    for card_id in player.hand:
        card = ctx.cards.get(card_id)
        if card is None or card.cost > mana_left:
            continue
        if card.card_type == CardType.UNIT:
            if not card.collectible or card.blueprint_id not in ctx.blueprints:
                continue
            blueprint = ctx.blueprints[card.blueprint_id]
            cell = _first_free_spawn_cell(ctx, player.side, blueprint, taken_cells)
            if cell is None:
                continue
            taken_cells.add(cell)
            spawns.append(SpawnIntent(card_id=card_id, row=cell[0], col=cell[1]))
            mana_left -= card.cost
        else:
            intent = _plan_spell(ctx, player.side, card_id, card.spell_id)
            if intent is None:
                continue
            spells.append(intent)
            mana_left -= card.cost

    return PlayerIntents(player_id=player_id, spells=tuple(spells), spawns=tuple(spawns))


def _first_free_spawn_cell(
    ctx: EffectContext,
    side: PlayerSide,
    blueprint,
    taken_cells: set[tuple[int, int]],
) -> tuple[int, int] | None:
    rows = blueprint.spawn_zone.resolve(side=side, rows=ctx.rows)
    # Ближний к врагу ряд — первым: для TOP это больший номер, для BOTTOM —
    # меньший (юнит быстрее вступает в бой).
    ordered_rows = sorted(rows, reverse=(side == PlayerSide.TOP))
    for row in ordered_rows:
        for col in range(ctx.cols):
            if (row, col) not in taken_cells:
                return (row, col)
    return None


def _plan_spell(
    ctx: EffectContext,
    side: PlayerSide,
    card_id: str,
    spell_id: str | None,
) -> SpellIntent | None:
    script = ctx.spells.get(spell_id or "")
    if script is None:
        return None
    if all(action.target.scope == "board" for action in script.actions):
        return SpellIntent(card_id=card_id)
    # Точечный скрипт: лечащий — в своего, прочие — во врага. Классификация
    # по первому действию — заглушка уровня «легально и не в молоко».
    # Структуры (башни) исключаем: они иммунны к урону эффектов (F4) —
    # молния в башню ушла бы в молоко.
    prefers_ally = isinstance(script.actions[0].effect, Heal)
    candidates = [
        unit
        for unit in ctx.units
        if (unit.side == side) == prefers_ally
        and TAG_STRUCTURE not in unit_tags(unit, ctx.blueprint_of(unit))
    ]
    if not candidates:
        return None
    target = min(candidates, key=lambda unit: (unit.row, unit.col))
    return SpellIntent(card_id=card_id, row=target.row, col=target.col)
