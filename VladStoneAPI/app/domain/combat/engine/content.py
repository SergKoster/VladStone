"""Стартовый контент v4: 12 карт по решениям владельца (COMBAT_REWORK §14.1).

Единственный источник игровых чисел карт — этот файл (доки на него ссылаются,
числа не дублируют). Все карты — ОБЫЧНОЙ редкости (выдаются сразу; редкость =
сложность получения, DESIGN §4.2). id карт вечны (DESIGN §4.5) — менять можно
имена и числа, но не id. Все юниты — 1×1 (мультиклеточные — задел на будущее).
"""

from app.domain.combat.engine.abilities import (
    Ability,
    SpellAction,
    SpellScript,
    TriggerHook,
)
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.effects import (
    ApplyStatus,
    DealDamage,
    Heal,
    ModifyBudget,
)
from app.domain.combat.engine.patterns import CellOffset, CellPattern, SpawnZone
from app.domain.combat.engine.stances import Stance, StanceProgram
from app.domain.combat.engine.statuses import STATUS_POISON, STATUS_ZADANIE_MARK
from app.domain.combat.engine.targeting import TargetSelector
from app.domain.combat.engine.towers import TOWER_BLUEPRINT
from app.domain.combat.engine.units import StatsOverride, UnitBlueprint, UnitStats
from app.domain.combat.models import Rarity

# Поле v4 (решение владельца §10.5).
V4_ROWS = 5
V4_COLS = 5

FORWARD_1 = CellPattern(offsets=(CellOffset(forward=1, col=0),))
FORWARD_2 = CellPattern(offsets=(CellOffset(forward=1, col=0), CellOffset(forward=2, col=0)))
NO_COVERAGE = CellPattern()
DEFAULT_SPAWN = SpawnZone(rows_from_back=(1, 2))


def _unit(bp_id: str, name: str, **fields) -> UnitBlueprint:
    return UnitBlueprint(id=bp_id, name=name, **fields)


BLUEPRINTS: dict[str, UnitBlueprint] = {
    bp.id: bp
    for bp in (
        _unit(
            "test_bruiser",
            "Толстяк",
            stats=UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
            stance_program=StanceProgram.always(Stance.ATTACK),
            coverage_attack=FORWARD_1,
            coverage_defense=CellPattern.cross(),
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "red_skull",
            "Красный череп",
            stats=UnitStats(hp=1, damage=0, attacks_per_turn=0, move_steps=1),
            stance_program=StanceProgram.always(Stance.ATTACK),
            # Покрытий нет принципиально: даже с баффом урона атаковать нечем.
            coverage_attack=NO_COVERAGE,
            coverage_defense=NO_COVERAGE,
            spawn_zone=DEFAULT_SPAWN,
            abilities=(
                Ability(
                    trigger=TriggerHook.ON_DEATH,
                    effect=DealDamage(amount=2),
                    target=TargetSelector(
                        scope="pattern", pattern=CellPattern.square(include_center=True)
                    ),
                ),
            ),
        ),
        _unit(
            "test_ranger",
            "Дальник",
            stats=UnitStats(hp=2, damage=1, attacks_per_turn=2, move_steps=1),
            stance_program=StanceProgram.warmup(2),
            coverage_attack=FORWARD_2,
            coverage_defense=CellPattern.union(CellPattern.ring(), CellPattern.cross(2)),
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "dolbiki",
            "Долбики",
            stats=UnitStats(hp=3, damage=1, attacks_per_turn=2, move_steps=2),
            stance_program=StanceProgram.always(Stance.ATTACK),
            coverage_attack=FORWARD_1,
            coverage_defense=CellPattern.cross(),
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "matesha",
            "Матеша",
            stats=UnitStats(hp=4, damage=1, attacks_per_turn=1, move_steps=1),
            stance_program=StanceProgram.warmup(3),
            coverage_attack=FORWARD_1,
            coverage_defense=NO_COVERAGE,  # в защите не атакует
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "evil_dolbiki",
            "Злые Долбики",
            stats=UnitStats(hp=5, damage=1, attacks_per_turn=3, move_steps=2),
            stance_program=StanceProgram.always(Stance.ATTACK),
            coverage_attack=FORWARD_1,
            coverage_defense=CellPattern.ring(),
            spawn_zone=SpawnZone(rows_from_back=(1, 2, 3)),
            abilities=(
                # При спавне: 1 урон ВСЕМ юнитам в кольце — и своим тоже
                # («Да будет френдли фаер!», E2).
                Ability(
                    trigger=TriggerHook.ON_SPAWN,
                    effect=DealDamage(amount=1),
                    target=TargetSelector(scope="pattern", pattern=CellPattern.ring()),
                ),
            ),
        ),
        _unit(
            "matesha_plus",
            "Матеша+",
            stats=UnitStats(hp=8, damage=1, attacks_per_turn=1, move_steps=1),
            stance_program=StanceProgram.warmup(4),
            coverage_attack=FORWARD_2,
            coverage_defense=NO_COVERAGE,
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "epic_serega",
            "Эпик Серёга",
            stats=UnitStats(hp=5, damage=3, attacks_per_turn=1, move_steps=1),
            # +2 урона в стойке Защита (стойко-зависимый стат).
            stats_defense=StatsOverride(damage=5),
            stance_program=StanceProgram.warmup(1),
            coverage_attack=CellPattern.cross(),
            coverage_defense=CellPattern.ring(),
            spawn_zone=DEFAULT_SPAWN,
        ),
        _unit(
            "samurai_koster",
            "СамурайKoster",
            stats=UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
            stance_program=StanceProgram.always(Stance.ATTACK),
            coverage_attack=FORWARD_1,
            coverage_defense=CellPattern.cross(),
            spawn_zone=DEFAULT_SPAWN,
            abilities=(
                # После смерти врага в радиусе атаки: +1 шаг в этом ходу
                # (за каждую подходящую смерть).
                Ability(
                    trigger=TriggerHook.ON_ENEMY_DEATH_IN_COVERAGE,
                    effect=ModifyBudget(steps=1),
                    target=TargetSelector(scope="self"),
                ),
            ),
        ),
        TOWER_BLUEPRINT,
    )
}

SPELLS: dict[str, SpellScript] = {
    script.id: script
    for script in (
        SpellScript(
            id="banka",
            actions=(
                # Яд 3 в цель; тик: −1 HP и −1 стак (канон §14.1).
                SpellAction(
                    effect=ApplyStatus(status_id=STATUS_POISON, stacks=3),
                    target=TargetSelector(scope="cell"),
                ),
            ),
        ),
        SpellScript(
            id="mushrooms",
            actions=(
                # Лечит юнита в клетке на 2; соседи крестом получают 2 урона.
                SpellAction(effect=Heal(amount=2), target=TargetSelector(scope="cell")),
                SpellAction(
                    effect=DealDamage(amount=2),
                    target=TargetSelector(scope="pattern", pattern=CellPattern.cross()),
                ),
            ),
        ),
        SpellScript(
            id="zadanie",
            actions=(
                # Клеймо на 1 ход: убил цель своей атакой — +3 HP и +1 атака
                # навсегда; провалил — казнь. Можно и на врага (E2).
                SpellAction(
                    effect=ApplyStatus(status_id=STATUS_ZADANIE_MARK, ttl=1),
                    target=TargetSelector(scope="cell"),
                ),
            ),
        ),
    )
}


def _card(
    card_id: str, name: str, cost: int, rules_text: str, *, spell: bool = False
) -> CardDefinition:
    return CardDefinition(
        id=card_id,
        name=name,
        cost=cost,
        rarity=Rarity.COMMON,  # стартовые выдаются сразу (DESIGN §4.2)
        card_type=CardType.SPELL if spell else CardType.UNIT,
        rules_text=rules_text,
        blueprint_id=None if spell else card_id,
        spell_id=card_id if spell else None,
    )


CARDS: dict[str, CardDefinition] = {
    card.id: card
    for card in (
        _card("test_bruiser", "Толстяк", 3, "Обычный боец без особой способности."),
        _card(
            "banka",
            "Банка",
            2,
            (
                "Накладывает на выбранного юнита Яд 3: в конце хода он получает 1 урон "
                "и теряет 1 стак."
            ),
            spell=True,
        ),
        _card(
            "red_skull",
            "Красный череп",
            1,
            "После смерти наносит 2 урона всем юнитам в области 3×3, включая союзников.",
        ),
        _card(
            "test_ranger",
            "Дальник",
            3,
            "Первые 2 хода стоит в Защите, затем переходит в Атаку.",
        ),
        _card("dolbiki", "Долбики", 3, "Совершает 2 атаки и делает 2 шага за ход."),
        _card(
            "mushrooms",
            "Грибной лес",
            3,
            "Лечит юнита в выбранной клетке на 2, а юнитам по кресту вокруг наносит 2 урона.",
            spell=True,
        ),
        _card(
            "matesha",
            "Матеша",
            2,
            "Первые 3 хода стоит в Защите и не атакует, затем переходит в Атаку.",
        ),
        _card(
            "evil_dolbiki",
            "Злые Долбики",
            5,
            "При появлении наносят 1 урон всем юнитам в кольце, включая союзников.",
        ),
        _card(
            "matesha_plus",
            "Матеша+",
            6,
            "Первые 4 хода стоит в Защите и не атакует, затем переходит в Атаку.",
        ),
        _card(
            "epic_serega",
            "Эпик Серёга",
            5,
            "Первый ход стоит в Защите; в Защите наносит 5 урона, в Атаке — 3.",
        ),
        _card(
            "zadanie",
            "Задание",
            4,
            (
                "Клеймо на 1 ход: убей юнита своей атакой и получи +3 здоровья и +1 "
                "атаку навсегда; иначе носитель погибнет."
            ),
            spell=True,
        ),
        _card(
            "samurai_koster",
            "СамурайKoster",
            4,
            "Когда враг погибает в его покрытии, получает +1 шаг до конца текущего хода.",
        ),
    )
}

# Стартовая колода: каждая карта ровно один раз (без дублей, DESIGN §4.3).
DECK_CARD_IDS_V4: list[str] = list(CARDS)


def v4_mana_gain(turn: int) -> int:
    """Мана-кривая v4 (решение владельца §17): +2 за ход, каждый 4-й — +3."""
    return 3 if turn % 4 == 0 else 2
