"""Расширения движка под батч №1 (ARCH §5.1): пресеты, спеки статусов,
effective_stats, бафы, наблюдатель смерти, квесты.

Чертежи/карты — тестовые фикстуры в духе карт §14.1, НЕ игровой контент.
"""

import pytest
from pydantic import ValidationError

from app.domain.combat.engine import (
    STATUS_ZADANIE_MARK,
    Ability,
    ApplyStatus,
    BuffStats,
    CellOffset,
    CellPattern,
    EffectContext,
    Execute,
    ModifyBudget,
    SpawnZone,
    Stance,
    StanceProgram,
    StatsOverride,
    Status,
    TargetSelector,
    TriggerHook,
    UnitBlueprint,
    UnitStats,
    apply_effect,
    effective_stats,
    resolve_turn_v4,
    spawn_unit,
)
from app.domain.combat.models import HeroState, PlayerSide, PlayerState

ROWS, COLS = 5, 5


def make_blueprint(bp_id: str = "vanilla", **overrides) -> UnitBlueprint:
    fields = {
        "id": bp_id,
        "name": bp_id,
        "stats": UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        "stance_program": StanceProgram.always(Stance.ATTACK),
        "coverage_attack": CellPattern(offsets=(CellOffset(forward=1, col=0),)),
        "spawn_zone": SpawnZone(rows_from_back=(1, 2)),
    }
    fields.update(overrides)
    return UnitBlueprint(**fields)


def make_player(player_id, side, team):
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=10,
        hero=HeroState(owner_id=player_id, side=side),
    )


def make_ctx(*blueprints: UnitBlueprint) -> EffectContext:
    registry = {bp.id: bp for bp in blueprints}
    registry.setdefault("vanilla", make_blueprint())
    return EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("p1", PlayerSide.BOTTOM, 0),
            make_player("p2", PlayerSide.TOP, 1),
        ],
        blueprints=registry,
    )


def add_unit(ctx, *, uid, owner, row, col, bp="vanilla", hp=None):
    unit = spawn_unit(
        ctx.blueprints[bp],
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


def resolve(ctx, turn=1):
    return resolve_turn_v4(ctx, turn=turn, spell_coin=0, intents=[], mana_gain=lambda t: 0)


# --- №1: пресеты паттернов ---


def test_pattern_presets_shapes() -> None:
    assert len(CellPattern.cross().offsets) == 4
    assert len(CellPattern.cross(2).offsets) == 8
    assert len(CellPattern.ring().offsets) == 8
    assert len(CellPattern.square(include_center=True).offsets) == 9
    # Дальник §14.1: кольцо + крест радиуса 2 = 12 клеток (пересечения слиты).
    ranger_defense = CellPattern.union(CellPattern.ring(), CellPattern.cross(2))
    assert len(ranger_defense.offsets) == 12


# --- №3–4: effective_stats и стойко-зависимые статы (Эпик Серёга) ---


def test_stance_dependent_damage_via_effective_stats() -> None:
    serega = make_blueprint(
        "serega",
        stats=UnitStats(hp=5, damage=3, attacks_per_turn=1, move_steps=1),
        stats_defense=StatsOverride(damage=5),
        stance_program=StanceProgram.warmup(1),  # Защита 1 ход → Атака
        coverage_defense=CellPattern.cross(),
        coverage_attack=CellPattern.cross(),
    )
    ctx = make_ctx(serega)
    unit = add_unit(ctx, uid="serega", owner="p1", row=3, col=1, bp="serega")
    victim = add_unit(ctx, uid="victim", owner="p2", row=2, col=1, hp=99)

    assert effective_stats(unit, serega).damage == 5  # ход 1: Защита
    events = resolve(ctx, turn=1)
    hit = next(e for e in events if e.kind == "attack" and e.unit_id == unit.id)
    assert hit.amount == 5  # бьёт в Защите с бонусом
    unit.statuses = []  # снять возможные наложения (нет их) — для ясности
    assert unit.turns_on_field == 2
    assert effective_stats(unit, serega).damage == 3  # со 2-го хода: Атака
    assert victim.current_hp == 99 - 5


def test_permanent_buffs_stack_and_heal_on_hp_buff() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=3, col=1)
    apply_effect(BuffStats(hp=3, attacks_per_turn=1), ctx, caster_id="p1", targets=[unit])
    assert unit.current_hp == 4 + 3  # HP-бафф лечит на ту же величину
    stats = effective_stats(unit, ctx.blueprint_of(unit))
    assert stats.hp == 7 and stats.attacks_per_turn == 2

    with pytest.raises(ValidationError):
        BuffStats()  # пустой бафф — ошибка формы


def test_modify_budget_applies_clamps_and_dies_with_the_turn() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=4, col=0)
    apply_effect(ModifyBudget(steps=2), ctx, caster_id="p1", targets=[unit])
    assert unit.remaining_steps == 1 + 2
    apply_effect(ModifyBudget(steps=-99), ctx, caster_id="p1", targets=[unit])
    assert unit.remaining_steps == 0  # минус легален, кламп в ноль

    # Бафф бюджета живёт только внутри хода: сброс в НАЧАЛЕ resolve выдаёт
    # свежий бюджет по статам — «внешний» бафф не переживает границу хода
    # (источник бафов — эффекты самого хода, см. тест самурая).
    apply_effect(ModifyBudget(steps=5), ctx, caster_id="p1", targets=[unit])
    resolve(ctx)
    assert unit.row == 3  # прошёл ровно 1 шаг — базовый бюджет


# --- №5.1: U1 — серверное объяснение бездействия ---


def test_unit_waited_marks_defender_without_target_once_and_preserves_state() -> None:
    defender_bp = make_blueprint(
        "defender",
        stance_program=StanceProgram.always(Stance.DEFENSE),
        coverage_defense=CellPattern(),
    )
    ctx = make_ctx(defender_bp)
    defender = add_unit(ctx, uid="defender", owner="p1", row=4, col=1, bp="defender")

    events = resolve(ctx)

    waited = [event for event in events if event.kind == "unit_waited"]
    assert [(event.unit_id, event.wait_reason) for event in waited] == [
        ("defender", "defense_no_target")
    ]
    assert waited[0].phase == "iterations" and waited[0].iteration == 1
    assert waited[0].snapshot["units"][0]["id"] == "defender"
    assert (defender.row, defender.col) == (4, 1)
    assert defender.remaining_steps == 1 and defender.remaining_attacks == 1


def test_unit_waited_reports_blocked_attack_path_without_changing_rules() -> None:
    attacker_bp = make_blueprint(
        "attacker",
        stats=UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        coverage_attack=CellPattern(),
    )
    ctx = make_ctx(attacker_bp)
    attacker = add_unit(ctx, uid="attacker", owner="p1", row=0, col=1, bp="attacker")

    events = resolve(ctx)

    waited = [event for event in events if event.kind == "unit_waited"]
    assert [(event.unit_id, event.wait_reason) for event in waited] == [
        ("attacker", "path_blocked")
    ]
    assert (attacker.row, attacker.col) == (0, 1)
    assert attacker.remaining_steps == 1 and attacker.remaining_attacks == 1


# --- №6: наблюдатель смерти (СамурайKoster) ---


def test_enemy_death_in_coverage_grants_extra_step() -> None:
    samurai_bp = make_blueprint(
        "samurai",
        stats=UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        abilities=(
            Ability(
                trigger=TriggerHook.ON_ENEMY_DEATH_IN_COVERAGE,
                effect=ModifyBudget(steps=1),
                target=TargetSelector(scope="self"),
            ),
        ),
    )
    ctx = make_ctx(samurai_bp)
    samurai = add_unit(ctx, uid="samurai", owner="p1", row=2, col=1, bp="samurai")
    add_unit(ctx, uid="prey", owner="p2", row=1, col=1, hp=2)  # умрёт от 2 урона

    events = resolve(ctx)
    # Итерация 1: самурай бьёт жертву (2 урона = смерть на границе итерации);
    # волна: враг умер в его покрытии → +1 шаг → в итерации 2 самурай шагает
    # в освободившуюся клетку, в итерации 3 — ещё раз (базовый шаг цел).
    triggered = [e for e in events if e.kind == "ability_triggered" and e.unit_id == samurai.id]
    assert any(e.trigger == "on_enemy_death_in_coverage" for e in triggered)
    assert samurai.row == 0  # 2 шага за ход вместо 1


def test_own_death_does_not_feed_the_observer() -> None:
    from app.domain.combat.engine.statuses import STATUS_POISON

    samurai_bp = make_blueprint(
        "samurai",
        abilities=(
            Ability(
                trigger=TriggerHook.ON_ENEMY_DEATH_IN_COVERAGE,
                effect=ModifyBudget(steps=1),
                target=TargetSelector(scope="self"),
            ),
        ),
    )
    bystander_bp = make_blueprint(
        "bystander",
        stats=UnitStats(hp=1, damage=0, attacks_per_turn=0, move_steps=0),
        stance_program=StanceProgram.always(Stance.DEFENSE),
    )
    ctx = make_ctx(samurai_bp, bystander_bp)
    samurai = add_unit(ctx, uid="samurai", owner="p1", row=2, col=1, bp="samurai")
    ally = add_unit(ctx, uid="ally", owner="p1", row=1, col=1, bp="bystander")
    ally.statuses.append(Status(id=STATUS_POISON, stacks=1))  # умрёт в конце хода

    events = resolve(ctx)
    assert ally.id not in {u.id for u in ctx.units}  # свой погиб в его покрытии
    triggered = [e for e in events if e.kind == "ability_triggered" and e.unit_id == samurai.id]
    assert not triggered  # смерть СВОЕГО не кормит наблюдателя


# --- №7: квест-статусы (Задание) ---


def test_zadanie_quest_success_buffs_permanently() -> None:
    ctx = make_ctx()
    hunter = add_unit(ctx, uid="hunter", owner="p1", row=2, col=1)
    add_unit(ctx, uid="prey", owner="p2", row=1, col=1, hp=1)  # умрёт от атаки
    apply_effect(
        ApplyStatus(status_id=STATUS_ZADANIE_MARK, ttl=1), ctx, caster_id="p2", targets=[hunter]
    )

    events = resolve(ctx)
    quest = [e for e in events if e.kind == "ability_triggered" and "quest" in (e.trigger or "")]
    assert quest and quest[0].trigger == "quest:zadanie_mark:success"
    assert hunter.id in {u.id for u in ctx.units}  # выжил
    stats = effective_stats(hunter, ctx.blueprint_of(hunter))
    assert stats.hp == 4 + 3 and stats.attacks_per_turn == 2  # награда навсегда
    assert all(s.id != STATUS_ZADANIE_MARK for s in hunter.statuses)  # клеймо снято


def test_zadanie_quest_failure_executes_the_bearer() -> None:
    ctx = make_ctx()
    slacker = add_unit(ctx, uid="slacker", owner="p1", row=4, col=0)
    apply_effect(
        ApplyStatus(status_id=STATUS_ZADANIE_MARK, ttl=1), ctx, caster_id="p2", targets=[slacker]
    )
    events = resolve(ctx)  # некого убивать — задание провалено
    quest = [e for e in events if e.kind == "ability_triggered" and "quest" in (e.trigger or "")]
    assert quest and quest[0].trigger == "quest:zadanie_mark:fail"
    assert slacker.id not in {u.id for u in ctx.units}  # кара: казнён волной


def test_execute_dooms_but_spares_structures() -> None:
    from app.domain.combat.engine import add_towers, towers_of

    ctx = make_ctx()
    add_towers(ctx, ctx.player_by_id("p2"))
    unit = add_unit(ctx, uid="u", owner="p2", row=1, col=1)
    tower = towers_of(ctx, "p2")[0]
    apply_effect(Execute(), ctx, caster_id="p1", targets=[unit, tower])
    assert unit.doomed and not tower.doomed  # F4: структуры казни не поддаются
