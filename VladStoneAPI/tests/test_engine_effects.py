"""Словарь эффектов v4 (P2.9): примитивы, селекторы, иммунитеты F3/F4.

Чертежи и карты здесь — тестовые фикстуры, НЕ игровой контент.
"""

import pytest
from pydantic import ValidationError

from app.domain.combat.engine import (
    HAND_CAP,
    Ability,
    ApplyStatus,
    CardDefinition,
    CardType,
    CellOffset,
    CellPattern,
    ChangeStance,
    DealDamage,
    DrawCard,
    EffectContext,
    GrantTag,
    Heal,
    KillIf,
    ModifyMana,
    Push,
    SpawnToken,
    SpawnZone,
    SpellAction,
    SpellScript,
    Stance,
    StanceProgram,
    TargetSelector,
    TargetSide,
    TriggerHook,
    UnitBlueprint,
    UnitStats,
    apply_effect,
    current_stance,
    select_targets,
    spawn_unit,
    validate_spell_script,
)
from app.domain.combat.engine.statuses import STATUS_POISON
from app.domain.combat.models import HeroState, PlayerSide, PlayerState

ROWS, COLS = 5, 5


def make_blueprint(bp_id: str = "fixture_unit", **overrides) -> UnitBlueprint:
    fields = {
        "id": bp_id,
        "name": "Фикстура",
        "stats": UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        "stance_program": StanceProgram.always(Stance.ATTACK),
        "spawn_zone": SpawnZone(rows_from_back=(1, 2)),
    }
    fields.update(overrides)
    return UnitBlueprint(**fields)


def make_player(player_id: str, side: PlayerSide, team: int) -> PlayerState:
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=5,
        hero=HeroState(owner_id=player_id, side=side),
        deck=["card_a", "card_b"],
        hand=["card_c"],
    )


def make_ctx(*blueprints: UnitBlueprint, cards: dict | None = None) -> EffectContext:
    registry = {bp.id: bp for bp in blueprints} if blueprints else {}
    default = make_blueprint()
    registry.setdefault(default.id, default)
    return EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("p1", PlayerSide.BOTTOM, team=0),
            make_player("p2", PlayerSide.TOP, team=1),
        ],
        blueprints=registry,
        cards=cards or {},
    )


def add_unit(
    ctx: EffectContext, *, uid: str, owner: str, row: int, col: int, bp: str | None = None
):
    blueprint = ctx.blueprints[bp or "fixture_unit"]
    side = ctx.player_by_id(owner).side
    unit = spawn_unit(blueprint, unit_id=uid, owner_id=owner, side=side, row=row, col=col)
    ctx.units.append(unit)
    return unit


def tower_blueprint() -> UnitBlueprint:
    return make_blueprint(
        "fixture_tower",
        stats=UnitStats(hp=10, damage=1, attacks_per_turn=1, move_steps=0),
        stance_program=StanceProgram.always(Stance.DEFENSE),
        spawn_zone=SpawnZone(rows_from_back=(1,)),
        tags=("structure", "tower", "immovable"),
    )


# --- Селектор целей ---


def test_select_targets_default_hits_both_sides_in_field_order() -> None:
    ctx = make_ctx()
    mine = add_unit(ctx, uid="mine", owner="p1", row=3, col=1)
    theirs = add_unit(ctx, uid="theirs", owner="p2", row=1, col=1)
    # E2: friendly fire по дефолту — заклинание по всему полю видит и своих.
    selector = TargetSelector(scope="board")
    targets = select_targets(selector, ctx, caster_side=PlayerSide.BOTTOM)
    assert [unit.id for unit in targets] == [theirs.id, mine.id]  # (ряд, колонка)


def test_select_targets_side_and_tag_filters() -> None:
    ctx = make_ctx(tower_blueprint())
    add_unit(ctx, uid="mine", owner="p1", row=3, col=1)
    theirs = add_unit(ctx, uid="theirs", owner="p2", row=1, col=1)
    tower = add_unit(ctx, uid="tower", owner="p2", row=0, col=2, bp="fixture_tower")

    enemies = select_targets(
        TargetSelector(scope="board", side=TargetSide.ENEMY), ctx, caster_side=PlayerSide.BOTTOM
    )
    assert [unit.id for unit in enemies] == [tower.id, theirs.id]

    towers_only = select_targets(
        TargetSelector(scope="board", tag="tower"), ctx, caster_side=PlayerSide.BOTTOM
    )
    assert [unit.id for unit in towers_only] == [tower.id]


def test_select_targets_pattern_unfolds_by_caster_side() -> None:
    ctx = make_ctx()
    hit = add_unit(ctx, uid="hit", owner="p2", row=1, col=2)
    add_unit(ctx, uid="missed", owner="p2", row=3, col=2)
    # «Цель + клетка вперёд» от кастера снизу: вперёд = вверх (H7).
    selector = TargetSelector(
        scope="pattern",
        pattern=CellPattern(offsets=(CellOffset(forward=0, col=0), CellOffset(forward=1, col=0))),
    )
    targets = select_targets(selector, ctx, caster_side=PlayerSide.BOTTOM, origin=(2, 2))
    assert [unit.id for unit in targets] == [hit.id]


def test_selector_tag_must_be_registered() -> None:
    with pytest.raises(ValidationError):
        TargetSelector(scope="board", tag="strukture")


# --- Урон/лечение: F4, C3, Q4 ---


def test_deal_damage_goes_negative_and_spares_structures_by_default() -> None:
    ctx = make_ctx(tower_blueprint())
    unit = add_unit(ctx, uid="u", owner="p2", row=1, col=1)
    tower = add_unit(ctx, uid="t", owner="p2", row=0, col=0, bp="fixture_tower")

    events = apply_effect(
        DealDamage(amount=6), ctx, caster_id="p1", targets=[unit, tower]
    )
    # Юнит ушёл в минус (C3), башня не тронута (F4) и события по ней нет.
    assert unit.current_hp == -2
    assert tower.current_hp == 10
    assert [event.kind for event in events] == ["damage"]
    assert events[0].before == 4 and events[0].after == -2
    assert events[0].snapshot["players"]
    assert unit.id not in {item["id"] for item in events[0].snapshot["units"]}

    piercing = apply_effect(
        DealDamage(amount=3, affects_structures=True), ctx, caster_id="p1", targets=[tower]
    )
    assert tower.current_hp == 7
    assert piercing[0].unit_id == tower.id


def test_heal_has_no_cap() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=3, col=1)
    apply_effect(Heal(amount=100), ctx, caster_id="p1", targets=[unit])
    assert unit.current_hp == 104  # Q4: оверхил легален


# --- Статусы и стойки ---


def test_apply_status_stacks_fold_and_forced_stance_is_rejected() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p2", row=1, col=1)
    poison2 = ApplyStatus(status_id=STATUS_POISON, stacks=2)
    poison1 = ApplyStatus(status_id=STATUS_POISON, stacks=1)
    apply_effect(poison2, ctx, caster_id="p1", targets=[unit])
    apply_effect(poison1, ctx, caster_id="p1", targets=[unit])
    poison = next(s for s in unit.statuses if s.id == STATUS_POISON)
    assert poison.stacks == 3  # яд складывается (§5)

    with pytest.raises(ValidationError):
        ApplyStatus(status_id="forced_stance")  # только через change_stance


def test_change_stance_respects_immovable_and_overrides_q2() -> None:
    ctx = make_ctx(tower_blueprint())
    unit = add_unit(ctx, uid="u", owner="p2", row=1, col=1)
    tower = add_unit(ctx, uid="t", owner="p2", row=0, col=0, bp="fixture_tower")

    events = apply_effect(
        ChangeStance(stance=Stance.DEFENSE, ttl=2), ctx, caster_id="p1", targets=[unit, tower]
    )
    assert [event.unit_id for event in events] == [unit.id]  # башня иммунна (F3)
    assert current_stance(unit, ctx.blueprint_of(unit)) == Stance.DEFENSE
    assert current_stance(tower, ctx.blueprint_of(tower)) == Stance.DEFENSE  # своя вечная

    # Q2-перезапись: второе наложение стирает первое, а не копится.
    apply_effect(ChangeStance(stance=Stance.ATTACK, ttl=1), ctx, caster_id="p1", targets=[unit])
    forced = [s for s in unit.statuses if s.id == "forced_stance"]
    assert len(forced) == 1 and forced[0].stance == Stance.ATTACK


def test_grant_tag_enables_tag_targeting() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=3, col=1)
    assert apply_effect(GrantTag(tag="immovable"), ctx, caster_id="p1", targets=[unit])
    # Повторная выдача — идемпотентна, без события.
    assert apply_effect(GrantTag(tag="immovable"), ctx, caster_id="p1", targets=[unit]) == []
    found = select_targets(
        TargetSelector(scope="board", tag="immovable"), ctx, caster_side=PlayerSide.BOTTOM
    )
    assert [u.id for u in found] == [unit.id]
    # И теперь юнит неподвижен для пуша (F3 читает итоговые теги).
    assert apply_effect(Push(), ctx, caster_id="p1", targets=[unit]) == []


# --- Пуш ---


def test_push_moves_forward_by_target_side_and_stops_at_obstacles() -> None:
    ctx = make_ctx()
    mine = add_unit(ctx, uid="mine", owner="p1", row=3, col=1)  # BOTTOM: вперёд = вверх
    blocker = add_unit(ctx, uid="blocker", owner="p2", row=1, col=1)

    events = apply_effect(Push(cells=3), ctx, caster_id="p1", targets=[mine])
    # 3 клетки вперёд, но на ряду 1 стоит юнит: доехал до ряда 2 и встал.
    assert mine.row == 2
    assert events[0].kind == "pushed"
    assert events[0].from_cell == (3, 1) and events[0].to_cell == (2, 1)

    # Заблокирован вплотную — эффект детерминированно фейлится.
    fizzle = apply_effect(Push(), ctx, caster_id="p1", targets=[mine])
    assert [event.kind for event in fizzle] == ["fizzled"]
    assert blocker.row == 1


# --- Казнь по условию (Жнец, «добей если 1 HP») ---


def test_kill_if_reaper_executes_poisoned_of_both_sides() -> None:
    ctx = make_ctx()
    poisoned_mine = add_unit(ctx, uid="pm", owner="p1", row=3, col=0)
    poisoned_theirs = add_unit(ctx, uid="pt", owner="p2", row=1, col=0)
    clean = add_unit(ctx, uid="clean", owner="p2", row=1, col=1)
    lightly = add_unit(ctx, uid="light", owner="p2", row=1, col=2)
    for unit, stacks in ((poisoned_mine, 2), (poisoned_theirs, 3), (lightly, 1)):
        apply_effect(
            ApplyStatus(status_id=STATUS_POISON, stacks=stacks), ctx, caster_id="p1", targets=[unit]
        )

    reaper = KillIf(status_id=STATUS_POISON, min_stacks=2)
    targets = select_targets(TargetSelector(scope="board"), ctx, caster_side=PlayerSide.BOTTOM)
    events = apply_effect(reaper, ctx, caster_id="p1", targets=targets)

    # Обе стороны (E2!), только Яд 2+: свой и чужой казнены, чистый и Яд 1 — нет.
    # Q5: казнь = пометка «обречён» (не HP), волна убьёт независимо от хиллов.
    assert {event.unit_id for event in events} == {poisoned_mine.id, poisoned_theirs.id}
    assert poisoned_mine.doomed and poisoned_theirs.doomed
    assert not clean.doomed and not lightly.doomed


def test_kill_if_requires_a_condition_and_checks_max_hp() -> None:
    with pytest.raises(ValidationError):
        KillIf()
    ctx = make_ctx()
    weak = add_unit(ctx, uid="weak", owner="p2", row=1, col=1)
    weak.current_hp = 1
    strong = add_unit(ctx, uid="strong", owner="p2", row=1, col=2)
    events = apply_effect(KillIf(max_hp=1), ctx, caster_id="p1", targets=[weak, strong])
    assert [event.unit_id for event in events] == [weak.id]
    assert strong.current_hp == 4


# --- Токены ---


def test_spawn_token_places_unit_or_fizzles_on_occupied_cell() -> None:
    token_card = CardDefinition(
        id="skeleton_token",
        name="Скелетик",
        cost=1,
        card_type=CardType.UNIT,
        blueprint_id="fixture_unit",
        collectible=False,
    )
    ctx = make_ctx(cards={token_card.id: token_card})
    effect = SpawnToken(card_id=token_card.id)

    events = apply_effect(effect, ctx, caster_id="p1", cell=(3, 3))
    assert events[0].kind == "token_spawned"
    token = ctx.unit_at(3, 3)
    assert token is not None and token.owner_id == "p1" and token.side == PlayerSide.BOTTOM

    # I5: занятая клетка — детерминированный фейл, второй токен не появился.
    fizzle = apply_effect(effect, ctx, caster_id="p1", cell=(3, 3))
    assert [event.kind for event in fizzle] == ["fizzled"]
    assert len(ctx.units) == 1

    with pytest.raises(ValueError, match="invalid card"):
        apply_effect(SpawnToken(card_id="missing"), ctx, caster_id="p1", cell=(2, 2))


# --- Игрокоскопные примитивы ---


def test_draw_card_respects_hand_cap() -> None:
    ctx = make_ctx()
    p1 = ctx.player_by_id("p1")
    events = apply_effect(DrawCard(count=2), ctx, caster_id="p1")
    assert len(p1.hand) == 3 and len(events) == 2

    p1.hand = [f"c{i}" for i in range(HAND_CAP)]
    assert apply_effect(DrawCard(), ctx, caster_id="p1") == []  # E3: рука полна


def test_modify_mana_clamps_and_supports_mana_theft() -> None:
    ctx = make_ctx()
    p1, p2 = ctx.player_by_id("p1"), ctx.player_by_id("p2")
    # «Кража маны» (R13): отнять у врага, добавить себе — два примитива.
    apply_effect(ModifyMana(amount=-2, who="opponent"), ctx, caster_id="p1")
    apply_effect(ModifyMana(amount=2), ctx, caster_id="p1")
    assert p2.mana == 3 and p1.mana == 7

    apply_effect(ModifyMana(amount=-99, who="opponent"), ctx, caster_id="p1")
    assert p2.mana == 0  # не ниже нуля
    apply_effect(ModifyMana(amount=99), ctx, caster_id="p1")
    assert p1.mana == ctx.mana_cap  # не выше кэпа


# --- Ability и SpellScript — «карта = примитивы + селектор» (Q1) ---


def test_q1_card_expressed_as_data_only() -> None:
    # Пример владельца из §18.7: «при спавне +1 HP всем союзникам вокруг и
    # приказ в Атаку» — два примитива, ноль кода.
    aura = CellPattern(
        offsets=tuple(
            CellOffset(forward=f, col=c) for f in (-1, 0, 1) for c in (-1, 0, 1) if (f, c) != (0, 0)
        )
    )
    blueprint = make_blueprint(
        "fixture_banner",
        abilities=(
            Ability(
                trigger=TriggerHook.ON_SPAWN,
                effect=Heal(amount=1),
                target=TargetSelector(scope="pattern", pattern=aura, side=TargetSide.ALLY),
            ),
            Ability(
                trigger=TriggerHook.ON_SPAWN,
                effect=ChangeStance(stance=Stance.ATTACK, ttl=1),
                target=TargetSelector(scope="pattern", pattern=aura, side=TargetSide.ALLY),
            ),
        ),
    )
    assert len(blueprint.abilities) == 2  # сериализуемые данные, без кода

    # «Банка с ядом»: Яд 2 в цель, Яд 1 соседям — скрипт из двух действий.
    poison_jar = SpellScript(
        id="fixture_poison_jar",
        actions=(
            SpellAction(
                effect=ApplyStatus(status_id=STATUS_POISON, stacks=2),
                target=TargetSelector(scope="cell"),
            ),
            SpellAction(
                effect=ApplyStatus(status_id=STATUS_POISON, stacks=1),
                target=TargetSelector(
                    scope="pattern",
                    pattern=CellPattern(
                        offsets=(
                            CellOffset(forward=1, col=0),
                            CellOffset(forward=-1, col=0),
                            CellOffset(forward=0, col=-1),
                            CellOffset(forward=0, col=1),
                        )
                    ),
                ),
            ),
        ),
    )
    validate_spell_script(poison_jar, rows=ROWS, cols=COLS)

    ctx = make_ctx()
    center = add_unit(ctx, uid="center", owner="p2", row=1, col=1)
    neighbor = add_unit(ctx, uid="side", owner="p2", row=1, col=2)
    for action in poison_jar.actions:
        targets = select_targets(
            action.target, ctx, caster_side=PlayerSide.BOTTOM, origin=(1, 1)
        )
        apply_effect(action.effect, ctx, caster_id="p1", targets=targets)
    assert next(s for s in center.statuses if s.id == STATUS_POISON).stacks == 2
    assert next(s for s in neighbor.statuses if s.id == STATUS_POISON).stacks == 1
