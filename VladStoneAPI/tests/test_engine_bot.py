"""Бот v4 (P2.13, I2): легальные детерминированные намерения.

Чертежи/карты — тестовые фикстуры, НЕ игровой контент.
"""

from app.domain.combat.engine import (
    CardDefinition,
    CardType,
    CellOffset,
    CellPattern,
    DealDamage,
    EffectContext,
    Heal,
    SpawnZone,
    SpellAction,
    SpellScript,
    Stance,
    StanceProgram,
    TargetSelector,
    UnitBlueprint,
    UnitStats,
    plan_bot_intents,
    resolve_turn_v4,
    spawn_unit,
)
from app.domain.combat.models import HeroState, PlayerSide, PlayerState

ROWS, COLS = 5, 5

VANILLA = UnitBlueprint(
    id="vanilla",
    name="Ванилла",
    stats=UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
    stance_program=StanceProgram.always(Stance.ATTACK),
    coverage_attack=CellPattern(offsets=(CellOffset(forward=1, col=0),)),
    spawn_zone=SpawnZone(rows_from_back=(1, 2)),
)
BOLT = SpellScript(
    id="bolt",
    actions=(SpellAction(effect=DealDamage(amount=3), target=TargetSelector(scope="cell")),),
)
MEND = SpellScript(
    id="mend",
    actions=(SpellAction(effect=Heal(amount=2), target=TargetSelector(scope="cell")),),
)
NUKE = SpellScript(
    id="nuke",
    actions=(SpellAction(effect=DealDamage(amount=1), target=TargetSelector(scope="board")),),
)

CARDS = {
    "warrior": CardDefinition(
        id="warrior", name="Воин", cost=2, card_type=CardType.UNIT, blueprint_id="vanilla"
    ),
    "bolt_card": CardDefinition(
        id="bolt_card", name="Молния", cost=1, card_type=CardType.SPELL, spell_id="bolt"
    ),
    "mend_card": CardDefinition(
        id="mend_card", name="Хилл", cost=1, card_type=CardType.SPELL, spell_id="mend"
    ),
    "nuke_card": CardDefinition(
        id="nuke_card", name="Волна", cost=1, card_type=CardType.SPELL, spell_id="nuke"
    ),
}


def make_player(player_id, side, team, hand, mana=10):
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=mana,
        hero=HeroState(owner_id=player_id, side=side),
        deck=["filler_a", "filler_b", "filler_c"],
        hand=hand,
    )


def make_ctx(*, bot_hand: list[str], bot_mana: int = 10, human_hand: list[str] | None = None):
    return EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("human", PlayerSide.BOTTOM, 0, human_hand or []),
            make_player("bot", PlayerSide.TOP, 1, bot_hand, mana=bot_mana),
        ],
        blueprints={VANILLA.id: VANILLA},
        cards=CARDS,
        spells={"bolt": BOLT, "mend": MEND, "nuke": NUKE},
    )


def add_unit(ctx, *, uid, owner, row, col):
    unit = spawn_unit(
        VANILLA,
        unit_id=uid,
        owner_id=owner,
        side=ctx.player_by_id(owner).side,
        row=row,
        col=col,
    )
    ctx.units.append(unit)
    return unit


def test_bot_spawns_toward_the_enemy_and_respects_mana() -> None:
    # Мана 5: два воина по 2 влезают, третий — нет.
    ctx = make_ctx(bot_hand=["warrior", "warrior", "warrior"], bot_mana=5)
    intents = plan_bot_intents(ctx, "bot")
    assert len(intents.spawns) == 2
    # TOP: ближний к врагу ряд зоны 1–2 — это ряд 1; колонки слева направо.
    assert [(spawn.row, spawn.col) for spawn in intents.spawns] == [(1, 0), (1, 1)]


def test_bot_avoids_occupied_cells() -> None:
    ctx = make_ctx(bot_hand=["warrior"])
    add_unit(ctx, uid="blocker", owner="bot", row=1, col=0)
    intents = plan_bot_intents(ctx, "bot")
    assert [(spawn.row, spawn.col) for spawn in intents.spawns] == [(1, 1)]


def test_bot_aims_damage_at_enemies_and_heals_allies() -> None:
    ctx = make_ctx(bot_hand=["bolt_card", "mend_card", "nuke_card"])
    ally = add_unit(ctx, uid="ally", owner="bot", row=1, col=2)
    enemy = add_unit(ctx, uid="enemy", owner="human", row=3, col=1)
    intents = plan_bot_intents(ctx, "bot")
    by_card = {spell.card_id: spell for spell in intents.spells}
    assert (by_card["bolt_card"].row, by_card["bolt_card"].col) == (enemy.row, enemy.col)
    assert (by_card["mend_card"].row, by_card["mend_card"].col) == (ally.row, ally.col)
    # Зональный скрипт (board) — без точки применения.
    assert by_card["nuke_card"].row is None and by_card["nuke_card"].col is None


def test_bot_skips_pointed_spells_without_a_valid_target() -> None:
    # Пустое поле: точечным молнии/хиллу некуда — бот их не кастует.
    ctx = make_ctx(bot_hand=["bolt_card", "mend_card", "nuke_card"])
    intents = plan_bot_intents(ctx, "bot")
    assert [spell.card_id for spell in intents.spells] == ["nuke_card"]


def test_bot_plan_is_deterministic_and_read_only() -> None:
    ctx = make_ctx(bot_hand=["warrior", "bolt_card"])
    add_unit(ctx, uid="enemy", owner="human", row=3, col=1)
    snapshot = [unit.model_dump() for unit in ctx.units]
    first = plan_bot_intents(ctx, "bot")
    second = plan_bot_intents(ctx, "bot")
    assert first == second  # чистая функция от контекста
    assert [unit.model_dump() for unit in ctx.units] == snapshot  # план не мутирует бой


def test_bot_intents_resolve_without_fizzles() -> None:
    ctx = make_ctx(bot_hand=["warrior", "warrior", "bolt_card"], human_hand=["warrior"])
    add_unit(ctx, uid="enemy", owner="human", row=3, col=1)
    intents = plan_bot_intents(ctx, "bot")
    events = resolve_turn_v4(
        ctx, turn=1, spell_coin=0, intents=[intents], mana_gain=lambda t: 1
    )
    bot_fizzles = [
        event for event in events if event.kind == "fizzled" and event.player_id == "bot"
    ]
    assert bot_fizzles == []
    assert len([u for u in ctx.units if u.owner_id == "bot"]) == 2


def test_bot_vs_bot_match_survives_many_turns() -> None:
    # Дымовой прогон: оба игрока — боты, десять ходов, validate_state внутри
    # резолвера следит за инвариантами на каждой границе.
    ctx = make_ctx(bot_hand=["warrior", "bolt_card"], human_hand=["warrior", "warrior"])
    for turn in range(1, 11):
        intents = [
            plan_bot_intents(ctx, "human"),
            plan_bot_intents(ctx, "bot"),
        ]
        resolve_turn_v4(ctx, turn=turn, spell_coin=0, intents=intents, mana_gain=lambda t: 2)
    # Бой шёл: юниты появлялись и сражались (какие-то могли умереть).
    assert any(unit for unit in ctx.units)
