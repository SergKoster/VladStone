"""Башни v4 (P2.14, §17): призрачные клетки, урон, тай-брейк C2, винкон, суд.

Чертежи/карты — тестовые фикстуры, НЕ игровой контент (кроме дефолтной башни).
"""

from app.domain.combat.engine import (
    TOWER_HP,
    CellOffset,
    CellPattern,
    EffectContext,
    SpawnZone,
    Stance,
    StanceProgram,
    UnitBlueprint,
    UnitStats,
    add_towers,
    plan_bot_intents,
    resolve_turn_v4,
    run_judgement,
    spawn_unit,
    towers_of,
    validate_state,
    winner_team_by_towers,
)
from app.domain.combat.engine.abilities import SpellAction, SpellScript
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.effects import DealDamage
from app.domain.combat.engine.targeting import TargetSelector
from app.domain.combat.models import HeroState, PlayerSide, PlayerState

ROWS, COLS = 5, 5

# Манекен: стоит и терпит (Защита, ничего не делает).
DUMMY = UnitBlueprint(
    id="dummy",
    name="Манекен",
    stats=UnitStats(hp=9, damage=0, attacks_per_turn=0, move_steps=0),
    stance_program=StanceProgram.always(Stance.DEFENSE),
    spawn_zone=SpawnZone(rows_from_back=(1, 2)),
)
# Штурмовик: идёт вперёд и бьёт (в т.ч. башню).
RAIDER = UnitBlueprint(
    id="raider",
    name="Штурмовик",
    stats=UnitStats(hp=9, damage=2, attacks_per_turn=1, move_steps=1),
    stance_program=StanceProgram.always(Stance.ATTACK),
    coverage_attack=CellPattern(offsets=(CellOffset(forward=1, col=0),)),
    spawn_zone=SpawnZone(rows_from_back=(1, 2)),
)

BOLT = SpellScript(
    id="bolt",
    actions=(SpellAction(effect=DealDamage(amount=3), target=TargetSelector(scope="cell")),),
)
BOLT_CARD = CardDefinition(
    id="bolt_card", name="Молния", cost=1, card_type=CardType.SPELL, spell_id="bolt"
)


def make_player(player_id, side, team):
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=10,
        hero=HeroState(owner_id=player_id, side=side),
        deck=["filler"],
        hand=[],
    )


def make_ctx(*, with_towers: bool = True) -> EffectContext:
    ctx = EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("human", PlayerSide.BOTTOM, 0),
            make_player("bot", PlayerSide.TOP, 1),
        ],
        blueprints={DUMMY.id: DUMMY, RAIDER.id: RAIDER},
        cards={BOLT_CARD.id: BOLT_CARD},
        spells={"bolt": BOLT},
    )
    if with_towers:
        for player in ctx.players:
            add_towers(ctx, player)
    return ctx


def add_unit(ctx, *, uid, owner, row, col, bp):
    unit = spawn_unit(
        ctx.blueprints[bp],
        unit_id=uid,
        owner_id=owner,
        side=ctx.player_by_id(owner).side,
        row=row,
        col=col,
    )
    ctx.units.append(unit)
    return unit


def resolve(ctx, *intents, turn=1):
    return resolve_turn_v4(
        ctx, turn=turn, spell_coin=0, intents=list(intents), mana_gain=lambda t: 0
    )


def test_towers_stand_on_ghost_rows_and_pass_validation() -> None:
    ctx = make_ctx()
    assert [(t.row, t.col) for t in towers_of(ctx, "bot")] == [(-1, c) for c in range(5)]
    assert [(t.row, t.col) for t in towers_of(ctx, "human")] == [(5, c) for c in range(5)]
    validate_state(ctx)  # призрачные ряды легальны только для башен


def test_tower_damage_matches_canon_17() -> None:
    # §17: ОДИНОКИЙ юнит на ряду 1 центральной линии — 3 урона за ход
    # (единственная цель всех трёх достающих башен); крайней — 2; ряд 2 — 1.
    # Толпа урон «разбавляет» (C2) — поэтому каждый кейс в своём бою.
    def damage_after_one_turn(row: int, col: int) -> int:
        ctx = make_ctx()
        lone = add_unit(ctx, uid="lone", owner="human", row=row, col=col, bp="dummy")
        resolve(ctx)
        return 9 - lone.current_hp

    assert damage_after_one_turn(0, 2) == 3  # центр: своя башня + две соседние
    assert damage_after_one_turn(0, 0) == 2  # край: своя + одна соседняя
    assert damage_after_one_turn(1, 4) == 1  # ряд 2: только своя, вглубь


def test_tower_tiebreak_own_lane_first_then_leftmost() -> None:
    ctx = make_ctx()
    own_lane = add_unit(ctx, uid="own_lane", owner="human", row=0, col=2, bp="dummy")
    add_unit(ctx, uid="left_nb", owner="human", row=0, col=1, bp="dummy")
    events = resolve(ctx)
    tower2_attacks = [
        e for e in events if e.kind == "attack" and e.unit_id == "bot_tower_2"
    ]
    # Своя линия приоритетнее соседней, даже более левой (C2).
    assert [e.target_id for e in tower2_attacks] == [own_lane.id]

    ctx2 = make_ctx()
    add_unit(ctx2, uid="right_nb", owner="human", row=0, col=3, bp="dummy")
    add_unit(ctx2, uid="left_nb", owner="human", row=0, col=1, bp="dummy")
    events2 = resolve(ctx2)
    tower2_attacks2 = [
        e for e in events2 if e.kind == "attack" and e.unit_id == "bot_tower_2"
    ]
    # Своя линия пуста: из соседних — самая левая.
    assert [e.target_id for e in tower2_attacks2] == ["left_nb"]


def test_unit_attacks_tower_but_never_enters_ghost_row() -> None:
    ctx = make_ctx()
    raider = add_unit(ctx, uid="raider", owner="human", row=1, col=0, bp="raider")
    events = resolve(ctx)
    tower = next(t for t in towers_of(ctx, "bot") if t.col == 0)
    # Штурмовик дошёл до ряда 0, встал (на призрачный ряд хода нет) и бьёт
    # башню обычной атакой.
    assert raider.row == 0
    hits = [e for e in events if e.kind == "attack" and e.target_id == tower.id]
    assert hits and tower.current_hp == TOWER_HP - 2
    moves = [e for e in events if e.kind == "moved" and e.unit_id == raider.id]
    assert moves
    # Ни одно движение не завело юнита на призрачный ряд.
    assert all(e.to_cell is not None and e.to_cell[0] >= 0 for e in moves)


def test_win_condition_all_towers_down() -> None:
    ctx = make_ctx()
    assert winner_team_by_towers(ctx) is None  # обе команды с башнями
    ctx.units = [u for u in ctx.units if u.owner_id != "bot"]  # снесли все у бота
    assert winner_team_by_towers(ctx) == 0  # команда человека победила


def test_judgement_ladder() -> None:
    # (1) Количество башен — первично. Контрпример владельца: пять по 19
    # обязаны бить одну с 20 (старый «итеративный снос» давал обратное).
    assert run_judgement({0: [19, 19, 19, 19, 19], 1: [20]}) == 0
    assert run_judgement({0: [20, 5], 1: [5]}) == 0
    assert run_judgement({0: [5, 5, 8], 1: [5, 9]}) == 0
    # (2) Поровну башен — решает крепость СЛАБЕЙШЕЙ (даже против большей суммы).
    assert run_judgement({0: [2, 20], 1: [5, 9]}) == 1
    # (3) И слабейшие равны — решает сумма HP.
    assert run_judgement({0: [3, 7], 1: [3, 9]}) == 1
    # (4) Полное равенство — ничья (= поражение обоим, H4).
    assert run_judgement({0: [10, 10], 1: [10, 10]}) is None


def test_towers_are_immune_to_spell_statuses_and_executions() -> None:
    # Дыры blindspot pass: яд тикает мимо F4, казнь сносит винкон — закрыты.
    from app.domain.combat.engine import ApplyStatus, KillIf, apply_effect
    from app.domain.combat.engine.statuses import STATUS_POISON

    ctx = make_ctx()
    tower = towers_of(ctx, "bot")[0]
    poison = ApplyStatus(status_id=STATUS_POISON, stacks=5)
    assert apply_effect(poison, ctx, caster_id="human", targets=[tower]) == []
    assert tower.statuses == []  # яд не прилип — тик конца хода не тронет HP

    execute = KillIf(max_hp=999)
    assert apply_effect(execute, ctx, caster_id="human", targets=[tower]) == []
    assert not tower.doomed  # казнь заклинанием башню не берёт (F4)


def test_bot_does_not_waste_pointed_spells_on_towers() -> None:
    ctx = make_ctx()
    ctx.player_by_id("bot").hand = ["bolt_card"]
    # На поле пусто — только башни человека; молния в башню ушла бы в молоко
    # (F4), бот её не кастует.
    assert plan_bot_intents(ctx, "bot").spells == ()
    # Появился полевой враг — молния летит в него, а не в «ближнюю» башню.
    target = add_unit(ctx, uid="field_enemy", owner="human", row=3, col=1, bp="dummy")
    spells = plan_bot_intents(ctx, "bot").spells
    assert [(s.row, s.col) for s in spells] == [(target.row, target.col)]