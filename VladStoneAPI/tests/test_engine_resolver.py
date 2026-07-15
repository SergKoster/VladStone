"""Резолвер v4 (P2.10): 7 фаз, чередование C1, снапшот-намерения C4, волны C5.

Чертежи/карты — тестовые фикстуры, НЕ игровой контент.
"""

from app.domain.combat.engine import (
    Ability,
    CardDefinition,
    CardType,
    CellOffset,
    CellPattern,
    DealDamage,
    EffectContext,
    Heal,
    KillIf,
    PlayerIntents,
    SpawnIntent,
    SpawnZone,
    SpellAction,
    SpellIntent,
    SpellScript,
    Stance,
    StanceProgram,
    TargetSelector,
    TriggerHook,
    UnitBlueprint,
    UnitStats,
    resolve_turn_v4,
    spawn_unit,
    translate_engine_events,
)
from app.domain.combat.engine.apply import board_snapshot
from app.domain.combat.engine.content import BLUEPRINTS
from app.domain.combat.engine.statuses import STATUS_POISON, Status
from app.domain.combat.models import HeroState, PlayerSide, PlayerState

ROWS, COLS = 5, 5
FORWARD_1 = CellPattern(offsets=(CellOffset(forward=1, col=0),))


def make_blueprint(bp_id: str, **overrides) -> UnitBlueprint:
    fields = {
        "id": bp_id,
        "name": bp_id,
        "stats": UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        "stance_program": StanceProgram.always(Stance.ATTACK),
        "coverage_attack": FORWARD_1,
        "spawn_zone": SpawnZone(rows_from_back=(1, 2)),
    }
    fields.update(overrides)
    return UnitBlueprint(**fields)


BOLT = SpellScript(
    id="bolt",
    actions=(
        SpellAction(
            effect=DealDamage(amount=99),
            target=TargetSelector(scope="cell"),
        ),
    ),
)
EXECUTE = SpellScript(
    id="execute",
    actions=(SpellAction(effect=KillIf(max_hp=999), target=TargetSelector(scope="cell")),),
)
MEND = SpellScript(
    id="mend",
    actions=(SpellAction(effect=Heal(amount=10), target=TargetSelector(scope="cell")),),
)

SPELL_CARDS = {
    "bolt_card": CardDefinition(
        id="bolt_card", name="Молния", cost=1, card_type=CardType.SPELL, spell_id="bolt"
    ),
    "execute_card": CardDefinition(
        id="execute_card", name="Казнь", cost=1, card_type=CardType.SPELL, spell_id="execute"
    ),
    "mend_card": CardDefinition(
        id="mend_card", name="Хилл", cost=1, card_type=CardType.SPELL, spell_id="mend"
    ),
}


def make_player(player_id: str, side: PlayerSide, team: int, hand: list[str]) -> PlayerState:
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=10,
        hero=HeroState(owner_id=player_id, side=side),
        deck=["deck_filler"],
        hand=hand,
    )


def make_ctx(
    *blueprints: UnitBlueprint,
    p1_hand: list[str] | None = None,
    p2_hand: list[str] | None = None,
    cards: dict[str, CardDefinition] | None = None,
) -> EffectContext:
    registry = {bp.id: bp for bp in blueprints}
    vanilla = make_blueprint("vanilla")
    registry.setdefault(vanilla.id, vanilla)
    all_cards = dict(SPELL_CARDS)
    all_cards.update(cards or {})
    return EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("p1", PlayerSide.BOTTOM, 0, p1_hand or []),
            make_player("p2", PlayerSide.TOP, 1, p2_hand or []),
        ],
        blueprints=registry,
        cards=all_cards,
        spells={"bolt": BOLT, "execute": EXECUTE, "mend": MEND},
    )


def add_unit(ctx, *, uid, owner, row, col, bp="vanilla", hp=None):
    blueprint = ctx.blueprints[bp]
    unit = spawn_unit(
        blueprint,
        unit_id=uid,
        owner_id=owner,
        side=ctx.player_by_id(owner).side,
        row=row,
        col=col,
    )
    if hp is not None:
        unit.current_hp = hp
    ctx.units.append(unit)
    return unit


def resolve(ctx, *intents, turn=1, coin=0, mana_gain=lambda turn: 0):
    return resolve_turn_v4(
        ctx, turn=turn, spell_coin=coin, intents=list(intents), mana_gain=mana_gain
    )


def unit_ids(ctx) -> set[str]:
    return {unit.id for unit in ctx.units}


# --- A1: снапшоты доски на каждом событии ---


def test_board_snapshot_contract_and_unit_order_are_deterministic() -> None:
    ctx = make_ctx(BLUEPRINTS["test_bruiser"], BLUEPRINTS["tower_default"])
    tower = add_unit(
        ctx,
        uid="z_tower",
        owner="p1",
        row=ROWS,
        col=0,
        bp="tower_default",
    )
    bruiser = add_unit(
        ctx,
        uid="a_bruiser",
        owner="p1",
        row=4,
        col=1,
        bp="test_bruiser",
    )

    snapshot = board_snapshot(ctx)

    assert [unit["id"] for unit in snapshot["units"]] == [bruiser.id, tower.id]
    assert snapshot["units"][0] == {
        "id": bruiser.id,
        "card_id": "test_bruiser",
        "side": "bottom",
        "row": 4,
        "col": 1,
        "current_hp": 4,
        "max_hp": 4,
        "stance": "attack",
        "is_tower": False,
        "remaining_steps": 1,
        "remaining_attacks": 1,
    }
    assert snapshot["units"][1]["card_id"] is None
    assert snapshot["units"][1]["is_tower"] is True
    assert snapshot["players"] == [{"id": "p1", "mana": 10}, {"id": "p2", "mana": 10}]


def test_event_snapshots_capture_new_move_cell_and_exclude_dead_units() -> None:
    mover_blueprint = make_blueprint(
        "mover",
        stats=UnitStats(hp=4, damage=0, attacks_per_turn=0, move_steps=1),
    )
    move_ctx = make_ctx(mover_blueprint)
    mover = add_unit(move_ctx, uid="mover", owner="p1", row=3, col=2, bp="mover")
    move_events = resolve(move_ctx, turn=1)
    moved = next(event for event in move_events if event.kind == "moved")
    moved_unit = next(unit for unit in moved.snapshot["units"] if unit["id"] == mover.id)

    assert all(event.snapshot for event in move_events)
    assert (moved_unit["row"], moved_unit["col"]) == moved.to_cell
    assert moved_unit["remaining_steps"] == 0

    attacker_blueprint = make_blueprint(
        "attacker_snapshot",
        stats=UnitStats(hp=4, damage=1, attacks_per_turn=2, move_steps=0),
    )
    target_blueprint = make_blueprint(
        "target_snapshot",
        stats=UnitStats(hp=4, damage=0, attacks_per_turn=0, move_steps=0),
    )
    attack_ctx = make_ctx(attacker_blueprint, target_blueprint)
    attacker = add_unit(
        attack_ctx,
        uid="attacker",
        owner="p1",
        row=2,
        col=1,
        bp="attacker_snapshot",
    )
    add_unit(attack_ctx, uid="target", owner="p2", row=1, col=1, bp="target_snapshot")
    attack_events = resolve(attack_ctx, turn=1)
    attacked = next(event for event in attack_events if event.kind == "attack")
    attacked_unit = next(
        unit for unit in attacked.snapshot["units"] if unit["id"] == attacker.id
    )
    assert attacked_unit["remaining_attacks"] == 1

    duelist = make_blueprint(
        "duelist_snapshot",
        stats=UnitStats(hp=2, damage=2, attacks_per_turn=1, move_steps=0),
    )
    death_ctx = make_ctx(duelist)
    mine = add_unit(
        death_ctx,
        uid="mine",
        owner="p1",
        row=2,
        col=1,
        bp="duelist_snapshot",
    )
    theirs = add_unit(
        death_ctx,
        uid="theirs",
        owner="p2",
        row=1,
        col=1,
        bp="duelist_snapshot",
    )
    death_events = resolve(death_ctx, turn=1)
    deaths = [event for event in death_events if event.kind == "unit_died"]

    assert all(event.snapshot for event in death_events)
    assert {event.unit_id for event in deaths} == {mine.id, theirs.id}
    assert all(
        event.unit_id not in {unit["id"] for unit in event.snapshot["units"]}
        for event in deaths
    )


# --- C1: чередование спелл-фазы + волна между игроками ---


def test_c1_spell_order_alternates_by_turn() -> None:
    for turn, expected in ((1, ["p1", "p2"]), (2, ["p2", "p1"]), (3, ["p1", "p2"])):
        ctx = make_ctx(p1_hand=["bolt_card"], p2_hand=["bolt_card"])
        events = resolve(
            ctx,
            PlayerIntents(player_id="p1", spells=(SpellIntent(card_id="bolt_card", row=2, col=2),)),
            PlayerIntents(player_id="p2", spells=(SpellIntent(card_id="bolt_card", row=2, col=2),)),
            turn=turn,
        )
        casts = [event.player_id for event in events if event.kind == "spell_cast"]
        assert casts == expected, f"turn {turn}"
        assert all(
            event.affected_cells == [(2, 2)]
            for event in events
            if event.kind == "spell_cast"
        )


def test_c1_death_wave_runs_between_players_subphases() -> None:
    # p1 первым убивает юнита болтом; болт p2 в ту же клетку бьёт пустоту:
    # цель умерла волной МЕЖДУ под-фазами, а не в конце фазы.
    ctx = make_ctx(p1_hand=["bolt_card"], p2_hand=["bolt_card"])
    victim = add_unit(ctx, uid="victim", owner="p2", row=2, col=2)
    events = resolve(
        ctx,
        PlayerIntents(player_id="p1", spells=(SpellIntent(card_id="bolt_card", row=2, col=2),)),
        PlayerIntents(player_id="p2", spells=(SpellIntent(card_id="bolt_card", row=2, col=2),)),
        turn=1,
    )
    died = [event for event in events if event.kind == "unit_died"]
    assert [event.unit_id for event in died] == [victim.id]
    p2_damage = [
        event for event in events if event.kind == "damage" and event.unit_id == victim.id
    ]
    assert len(p2_damage) == 1  # только болт p1 нанёс урон


# --- Q5: казнь неотменяема хиллом ---


def test_q5_execution_survives_healing_but_not_the_wave() -> None:
    ctx = make_ctx(p1_hand=["execute_card", "mend_card"])
    victim = add_unit(ctx, uid="victim", owner="p2", row=2, col=2)
    events = resolve(
        ctx,
        PlayerIntents(
            player_id="p1",
            spells=(
                SpellIntent(card_id="execute_card", row=2, col=2),
                SpellIntent(card_id="mend_card", row=2, col=2),
            ),
        ),
        turn=1,
    )
    heals = [event for event in events if event.kind == "heal"]
    assert heals and heals[0].after > 4  # хилл прошёл и поднял HP
    assert victim.id not in unit_ids(ctx)  # но казнённый всё равно умер (doomed)


# --- Фаза 3: спавны, зоны, толчки ---


def test_spawn_pays_mana_consumes_card_and_respects_zone() -> None:
    unit_card = CardDefinition(
        id="uc", name="Юнит", cost=3, card_type=CardType.UNIT, blueprint_id="vanilla"
    )
    ctx = make_ctx(p1_hand=["uc", "uc2"], cards={"uc": unit_card})
    p1 = ctx.player_by_id("p1")
    events = resolve(
        ctx,
        PlayerIntents(
            player_id="p1",
            spawns=(
                SpawnIntent(card_id="uc", row=4, col=1),  # ряд 1 от края BOTTOM — ок
                SpawnIntent(card_id="uc2", row=4, col=2),  # нет такой карты
            ),
        ),
        turn=1,
    )
    spawned = [event for event in events if event.kind == "spawned"]
    fizzled = [event for event in events if event.kind == "fizzled"]
    assert len(spawned) == 1 and spawned[0].to_cell == (4, 1)
    assert len(fizzled) == 1 and fizzled[0].card_id == "uc2"
    assert p1.mana == 10 - 3 and "uc" not in p1.hand

    # Вне зоны спавна (ряд 3 от края при зоне 1–2) — физзл.
    p1.hand.append("uc")
    before_units = len(ctx.units)
    events = resolve(
        ctx,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="uc", row=2, col=0),)),
        turn=2,
    )
    assert [event.kind for event in events if event.kind in ("spawned", "fizzled")] == ["fizzled"]
    assert len(ctx.units) == before_units


def test_spawn_push_chain_of_allies_and_single_enemy() -> None:
    unit_card = CardDefinition(
        id="uc", name="Юнит", cost=1, card_type=CardType.UNIT, blueprint_id="vanilla"
    )
    # Цепочка своих: юниты на рядах 4 и 3, спавн в ряд 4 — оба сдвигаются.
    ctx = make_ctx(p1_hand=["uc"], cards={"uc": unit_card})
    front = add_unit(ctx, uid="front", owner="p1", row=3, col=0)
    back = add_unit(ctx, uid="back", owner="p1", row=4, col=0)
    events = resolve(
        ctx,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="uc", row=4, col=0),)),
        turn=1,
    )
    assert any(event.kind == "spawned" for event in events)
    # Цепочка ехала вперёд (для BOTTOM — вверх), новый юнит занял ряд 4.
    assert back.row < 4 and front.row < 3

    # Цепочка упирается во врага — ставить нельзя.
    ctx2 = make_ctx(p1_hand=["uc"], cards={"uc": unit_card})
    add_unit(ctx2, uid="ally", owner="p1", row=4, col=1)
    add_unit(ctx2, uid="enemy", owner="p2", row=3, col=1)
    events = resolve(
        ctx2,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="uc", row=4, col=1),)),
        turn=1,
    )
    assert any(event.kind == "fizzled" for event in events)
    assert len([u for u in ctx2.units if u.owner_id == "p1"]) == 1

    # Одиночный враг на спавн-клетке — толкается дальше (S1/MVP).
    ctx3 = make_ctx(p1_hand=["uc"], cards={"uc": unit_card})
    intruder = add_unit(ctx3, uid="intruder", owner="p2", row=4, col=2)
    # Замораживаем его, чтобы итерации не двигали (для чистоты проверки).
    intruder.doomed = False
    events = resolve(
        ctx3,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="uc", row=4, col=2),)),
        turn=1,
    )
    pushes = [event for event in events if event.kind == "pushed"]
    assert pushes and pushes[0].unit_id == intruder.id and pushes[0].to_cell == (3, 2)


def test_on_spawn_ability_fires_and_e1_mini_wave_collects_deaths() -> None:
    boomer = make_blueprint(
        "boomer",
        abilities=(
            Ability(
                trigger=TriggerHook.ON_SPAWN,
                effect=DealDamage(amount=99),
                target=TargetSelector(scope="pattern", pattern=FORWARD_1),
            ),
        ),
    )
    card = CardDefinition(
        id="boom", name="Бумер", cost=1, card_type=CardType.UNIT, blueprint_id="boomer"
    )
    ctx = make_ctx(boomer, p1_hand=["boom"], cards={"boom": card})
    victim = add_unit(ctx, uid="victim", owner="p2", row=3, col=0)
    events = resolve(
        ctx,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="boom", row=4, col=0),)),
        turn=1,
    )
    died = [event for event in events if event.kind == "unit_died"]
    assert [event.unit_id for event in died] == [victim.id]
    assert died[0].phase == "spawn"  # мини-волна E1 — ещё в фазе спавна


# --- Фаза 4: снапшот-намерения (C4), коллизии, стойки ---


def test_c4_accordion_column_advances_one_per_iteration() -> None:
    ctx = make_ctx()
    front = add_unit(ctx, uid="front", owner="p1", row=2, col=0)
    back = add_unit(ctx, uid="back", owner="p1", row=3, col=0)
    events = resolve(ctx, turn=1)
    moved = [event for event in events if event.kind == "moved"]
    # Гармошка: передний шагает в итерации 1; задний видит клетку занятой
    # (снапшот) и догоняет только в итерации 2.
    assert [(event.unit_id, event.iteration) for event in moved] == [
        (front.id, 1),
        (back.id, 2),
    ]
    assert front.row == 1 and back.row == 2


def test_c4_head_on_swap_is_blocked() -> None:
    # Встречные юниты вплотную: клетка визави занята по снапшоту у обоих —
    # никто не идёт и коллизии нет. Атак нет (attacks_per_turn=0).
    pacifist = make_blueprint(
        "pacifist", stats=UnitStats(hp=4, damage=2, attacks_per_turn=0, move_steps=1)
    )
    ctx = make_ctx(pacifist)
    mine = add_unit(ctx, uid="mine", owner="p1", row=2, col=1, bp="pacifist")
    theirs = add_unit(ctx, uid="theirs", owner="p2", row=1, col=1, bp="pacifist")
    events = resolve(ctx, turn=1)
    assert not [event for event in events if event.kind in ("moved", "collision")]
    assert (mine.row, theirs.row) == (2, 1)


def test_collision_only_into_an_empty_cell_trades_damage() -> None:
    pacifist = make_blueprint(
        "pacifist", stats=UnitStats(hp=5, damage=2, attacks_per_turn=0, move_steps=1)
    )
    ctx = make_ctx(pacifist)
    mine = add_unit(ctx, uid="mine", owner="p1", row=3, col=1, bp="pacifist")
    theirs = add_unit(ctx, uid="theirs", owner="p2", row=1, col=1, bp="pacifist")
    events = resolve(ctx, turn=1)
    collisions = [event for event in events if event.kind == "collision"]
    assert len(collisions) == 1 and collisions[0].to_cell == (2, 1)
    # Размен ударами, оба остались на местах.
    assert mine.current_hp == 3 and theirs.current_hp == 3
    assert (mine.row, theirs.row) == (3, 1)


def test_attack_first_priority_and_defense_never_moves() -> None:
    sniper = make_blueprint(
        "sniper",
        stance_program=StanceProgram.always(Stance.DEFENSE),
        coverage_defense=CellPattern(
            offsets=(CellOffset(forward=1, col=0), CellOffset(forward=2, col=0))
        ),
        stats=UnitStats(hp=3, damage=1, attacks_per_turn=1, move_steps=1),
    )
    ctx = make_ctx(sniper)
    shooter = add_unit(ctx, uid="shooter", owner="p1", row=3, col=0, bp="sniper")
    brawler = add_unit(ctx, uid="brawler", owner="p2", row=1, col=0)  # Атака, цель впереди
    events = resolve(ctx, turn=1)
    attacks = [event for event in events if event.kind == "attack"]
    # Снайпер в Защите стреляет (цель в 2 клетках) и не двигается; штурмовик
    # шагнул (итерация 1), попал под обстрел... порядок неважен — важно:
    assert any(event.unit_id == shooter.id for event in attacks)
    assert shooter.row == 3  # Защита не двигается
    # Штурмовик: сначала атака, если цель в покрытии; вплотную — бьёт, не идёт.
    assert brawler.row >= 1


def test_target_tiebreak_closest_to_owner_then_leftmost() -> None:
    wide = make_blueprint(
        "wide",
        stance_program=StanceProgram.always(Stance.DEFENSE),
        coverage_defense=CellPattern(
            offsets=tuple(CellOffset(forward=f, col=c) for f in (1, 2) for c in (-1, 0, 1))
        ),
        stats=UnitStats(hp=9, damage=1, attacks_per_turn=1, move_steps=0),
    )
    pacifist = make_blueprint(
        "pacifist", stats=UnitStats(hp=9, damage=0, attacks_per_turn=0, move_steps=0)
    )
    ctx = make_ctx(wide, pacifist)
    shooter = add_unit(ctx, uid="shooter", owner="p1", row=3, col=1, bp="wide")
    far = add_unit(ctx, uid="far", owner="p2", row=1, col=1, bp="pacifist")
    near_right = add_unit(ctx, uid="near_right", owner="p2", row=2, col=2, bp="pacifist")
    near_left = add_unit(ctx, uid="near_left", owner="p2", row=2, col=0, bp="pacifist")
    events = resolve(ctx, turn=1)
    first_attack = next(event for event in events if event.kind == "attack")
    # Ближе к герою владельца (низ для BOTTOM) — ряд 2; из двух равных — левый.
    assert first_attack.unit_id == shooter.id
    assert first_attack.target_id == near_left.id
    assert far.current_hp == 9 and near_right.current_hp == 9


def test_simultaneous_lethal_attacks_die_together_on_iteration_border() -> None:
    duelist = make_blueprint(
        "duelist", stats=UnitStats(hp=2, damage=2, attacks_per_turn=1, move_steps=1)
    )
    ctx = make_ctx(duelist)
    mine = add_unit(ctx, uid="mine", owner="p1", row=2, col=1, bp="duelist")
    theirs = add_unit(ctx, uid="theirs", owner="p2", row=1, col=1, bp="duelist")
    events = resolve(ctx, turn=1)
    died = [event for event in events if event.kind == "unit_died"]
    # Оба ударили по снапшоту, оба умерли одной волной на границе итерации 1.
    assert {event.unit_id for event in died} == {mine.id, theirs.id}
    assert all(event.iteration == 1 for event in died)
    assert unit_ids(ctx) == set()


def test_c5_death_wave_cascades_through_on_death_bombs() -> None:
    bomb = make_blueprint(
        "bomb",
        stats=UnitStats(hp=1, damage=0, attacks_per_turn=0, move_steps=0),
        stance_program=StanceProgram.always(Stance.DEFENSE),
        abilities=(
            Ability(
                trigger=TriggerHook.ON_DEATH,
                effect=DealDamage(amount=99),
                target=TargetSelector(
                    scope="pattern",
                    pattern=CellPattern(
                        offsets=(CellOffset(forward=1, col=0), CellOffset(forward=-1, col=0))
                    ),
                ),
            ),
        ),
    )
    ctx = make_ctx(bomb, p1_hand=["bolt_card"])
    a = add_unit(ctx, uid="a", owner="p2", row=1, col=1, bp="bomb")
    b = add_unit(ctx, uid="b", owner="p2", row=2, col=1, bp="bomb")
    c = add_unit(ctx, uid="c", owner="p2", row=3, col=1, bp="bomb")
    events = resolve(
        ctx,
        PlayerIntents(player_id="p1", spells=(SpellIntent(card_id="bolt_card", row=1, col=1),)),
        turn=1,
    )
    died = [event.unit_id for event in events if event.kind == "unit_died"]
    # Болт убил A; волна 1: A взрывается → B в минусе; волна 2: B взрывается →
    # C в минусе; волна 3: C. Каскад в одной спелл-под-фазе.
    assert died == [a.id, b.id, c.id]
    triggered = [event for event in events if event.kind == "ability_triggered"]
    assert triggered[0].affected_cells == [(0, 1), (2, 1)]
    assert unit_ids(ctx) == set()


def test_red_skull_death_is_typed_and_precedes_its_area_damage() -> None:
    ctx = make_ctx(BLUEPRINTS["red_skull"], p1_hand=["bolt_card"])
    skull = add_unit(ctx, uid="skull", owner="p2", row=2, col=2, bp="red_skull")
    victim = add_unit(ctx, uid="victim", owner="p1", row=2, col=3)

    facts = resolve(
        ctx,
        PlayerIntents(
            player_id="p1",
            spells=(SpellIntent(card_id="bolt_card", row=2, col=2),),
        ),
        turn=1,
    )
    death_index = next(
        index
        for index, fact in enumerate(facts)
        if fact.kind == "unit_died" and fact.unit_id == skull.id
    )
    trigger_index, trigger = next(
        (index, fact)
        for index, fact in enumerate(facts)
        if fact.kind == "ability_triggered" and fact.unit_id == skull.id
    )
    area_damage_index = next(
        index
        for index, fact in enumerate(facts)
        if fact.kind == "damage" and fact.unit_id == victim.id
    )
    assert death_index < trigger_index < area_damage_index
    assert trigger.trigger == "on_death" and trigger.effect_kind == "deal_damage"
    assert skull.id not in unit_ids(ctx)

    events = translate_engine_events(facts)
    skull_trigger = next(
        event
        for event in events
        if event.actor_id == skull.id and event.type.value == "ability_triggered"
    )
    assert skull_trigger.ability_trigger == "on_death"
    assert skull_trigger.effect_kind == "deal_damage"


# --- Фазы 5–7: яд, разогрев/ttl, добор и мана ---


def test_poison_ticks_one_damage_one_stack_and_kills_via_end_wave() -> None:
    # Новый канон яда (§14.1): тик конца хода = −1 HP И −1 стак.
    ctx = make_ctx()
    sturdy = add_unit(ctx, uid="sturdy", owner="p2", row=0, col=0, hp=5)
    sturdy.statuses.append(Status(id=STATUS_POISON, stacks=2))
    events = resolve(ctx, turn=1)
    tick = next(event for event in events if event.kind == "damage")
    assert tick.status_id == STATUS_POISON and tick.amount == 1 and tick.phase == "end"
    assert sturdy.current_hp == 4
    poison = next(s for s in sturdy.statuses if s.id == STATUS_POISON)
    assert poison.stacks == 1  # Яд 2 = ещё один ход по 1 урона

    ctx2 = make_ctx()
    frail = add_unit(ctx2, uid="frail", owner="p2", row=0, col=0, hp=1)
    frail.statuses.append(Status(id=STATUS_POISON, stacks=3))
    events2 = resolve(ctx2, turn=1)
    death = next(event for event in events2 if event.kind == "unit_died")
    assert death.unit_id == frail.id and death.phase == "end"


def test_warmup_and_ttl_tick_in_end_phase() -> None:
    warm = make_blueprint(
        "warm",
        stance_program=StanceProgram.warmup(2),
        stats=UnitStats(hp=4, damage=1, attacks_per_turn=1, move_steps=1),
    )
    card = CardDefinition(
        id="wc", name="Разогрев", cost=1, card_type=CardType.UNIT, blueprint_id="warm"
    )
    ctx = make_ctx(warm, p1_hand=["wc"], cards={"wc": card})
    resolve(
        ctx,
        PlayerIntents(player_id="p1", spawns=(SpawnIntent(card_id="wc", row=4, col=0),)),
        turn=1,
    )
    unit = next(unit for unit in ctx.units)
    # Ход постановки был первым ходом разогрева (D4); после тика конца хода
    # юнит вступает во второй.
    assert unit.turns_on_field == 2


def test_draw_respects_cap_and_mana_schedule_is_parameterized() -> None:
    ctx = make_ctx(p1_hand=["a", "b"])
    p1, p2 = ctx.players[0], ctx.players[1]
    p1.deck = ["x", "y"]
    p2.deck, p2.hand = [], []  # скриптовый бот MVP: без добора
    p1.mana = p2.mana = 0
    events = resolve(ctx, turn=3, mana_gain=lambda turn: turn)  # параметр R13
    drawn = [event for event in events if event.kind == "card_drawn"]
    assert [event.player_id for event in drawn] == [p1.id]
    assert len(p1.hand) == 3
    # Мана следующего хода по переданному расписанию: gain(4) = 4.
    assert p1.mana == 4 and p2.mana == 4
