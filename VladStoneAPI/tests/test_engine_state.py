"""validate_state и детерминированная сериализация (P2.11, I3).

Чертежи/карты — тестовые фикстуры, НЕ игровой контент.
"""

import pytest

from app.domain.combat.engine import (
    CellOffset,
    CellPattern,
    EffectContext,
    PlayerIntents,
    SpawnZone,
    Stance,
    StanceProgram,
    StateValidationError,
    Status,
    UnitBlueprint,
    UnitStats,
    canonical_units_json,
    resolve_turn_v4,
    spawn_unit,
    validate_state,
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


def make_player(player_id: str, side: PlayerSide, team: int) -> PlayerState:
    return PlayerState(
        id=player_id,
        side=side,
        team=team,
        mana=5,
        hero=HeroState(owner_id=player_id, side=side),
    )


def make_ctx() -> EffectContext:
    vanilla = make_blueprint()
    return EffectContext(
        rows=ROWS,
        cols=COLS,
        units=[],
        players=[
            make_player("p1", PlayerSide.BOTTOM, 0),
            make_player("p2", PlayerSide.TOP, 1),
        ],
        blueprints={vanilla.id: vanilla},
    )


def add_unit(ctx, *, uid, owner, row, col):
    unit = spawn_unit(
        ctx.blueprints["vanilla"],
        unit_id=uid,
        owner_id=owner,
        side=ctx.player_by_id(owner).side,
        row=row,
        col=col,
    )
    ctx.units.append(unit)
    return unit


# --- validate_state: инварианты ---


def test_validate_state_accepts_a_sane_board() -> None:
    ctx = make_ctx()
    add_unit(ctx, uid="a", owner="p1", row=3, col=1)
    add_unit(ctx, uid="b", owner="p2", row=1, col=1)
    validate_state(ctx)  # не бросает


def test_validate_state_catches_shared_cells_and_off_board() -> None:
    ctx = make_ctx()
    add_unit(ctx, uid="a", owner="p1", row=3, col=1)
    add_unit(ctx, uid="b", owner="p2", row=3, col=1)
    with pytest.raises(StateValidationError, match="share cell"):
        validate_state(ctx)

    ctx2 = make_ctx()
    stray = add_unit(ctx2, uid="stray", owner="p1", row=4, col=4)
    stray.row = 7
    with pytest.raises(StateValidationError, match="off-board"):
        validate_state(ctx2)


def test_validate_state_catches_survivors_of_missed_waves() -> None:
    ctx = make_ctx()
    zombie = add_unit(ctx, uid="zombie", owner="p1", row=3, col=1)
    zombie.current_hp = -2
    with pytest.raises(StateValidationError, match="survived a phase border"):
        validate_state(ctx)

    ctx2 = make_ctx()
    marked = add_unit(ctx2, uid="marked", owner="p1", row=3, col=1)
    marked.doomed = True
    with pytest.raises(StateValidationError, match="doomed"):
        validate_state(ctx2)


def test_validate_state_catches_broken_statuses_and_references() -> None:
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=3, col=1)
    unit.statuses.append(Status(id="forced_stance", stance=Stance.ATTACK, ttl=2))
    # Прямое присваивание обходит валидаторы pydantic — validate_state ловит.
    unit.statuses[0].ttl = 0
    with pytest.raises(StateValidationError, match="ttl 0"):
        validate_state(ctx)

    ctx2 = make_ctx()
    ghost = add_unit(ctx2, uid="ghost", owner="p1", row=3, col=1)
    ghost.blueprint_id = "missing"
    with pytest.raises(StateValidationError, match="unknown blueprint"):
        validate_state(ctx2)


def test_validate_state_checks_players_and_names_the_checkpoint() -> None:
    ctx = make_ctx()
    ctx.player_by_id("p1").mana = 99
    with pytest.raises(StateValidationError, match=r"mana 99.*\[end\]"):
        validate_state(ctx, checkpoint="end")

    ctx2 = make_ctx()
    ctx2.player_by_id("p2").hand = [f"c{i}" for i in range(7)]
    with pytest.raises(StateValidationError, match="over the cap"):
        validate_state(ctx2)


def test_resolver_fails_loudly_on_corrupt_entry_state() -> None:
    ctx = make_ctx()
    add_unit(ctx, uid="a", owner="p1", row=3, col=1)
    add_unit(ctx, uid="b", owner="p2", row=3, col=1)  # два юнита в одной клетке
    with pytest.raises(StateValidationError, match=r"\[entry\]"):
        resolve_turn_v4(ctx, turn=1, spell_coin=0, intents=[], mana_gain=lambda t: 0)


# --- I3: детерминированная сериализация и независимость от порядка ---


def test_canonical_units_json_ignores_list_order() -> None:
    ctx_a, ctx_b = make_ctx(), make_ctx()
    for ctx, order in ((ctx_a, ("a", "b")), (ctx_b, ("b", "a"))):
        for uid in order:
            row = 3 if uid == "a" else 1
            owner = "p1" if uid == "a" else "p2"
            add_unit(ctx, uid=uid, owner=owner, row=row, col=1)
    assert canonical_units_json(ctx_a.units) == canonical_units_json(ctx_b.units)


def test_resolution_is_independent_of_units_list_order() -> None:
    # Один и тот же бой, юниты добавлены в разном порядке: события и итоговое
    # состояние обязаны совпасть бит-в-бит (реплей/дорезолв, ARCH §8.16).
    def build(order: list[tuple[str, str, int, int]]):
        ctx = make_ctx()
        for uid, owner, row, col in order:
            add_unit(ctx, uid=uid, owner=owner, row=row, col=col)
        return ctx

    layout = [
        ("m1", "p1", 3, 0),
        ("m2", "p1", 4, 1),
        ("e1", "p2", 1, 0),
        ("e2", "p2", 0, 1),
    ]
    ctx_a = build(layout)
    ctx_b = build(list(reversed(layout)))
    events_a = resolve_turn_v4(ctx_a, turn=1, spell_coin=0, intents=[], mana_gain=lambda t: 1)
    events_b = resolve_turn_v4(ctx_b, turn=1, spell_coin=0, intents=[], mana_gain=lambda t: 1)
    assert [event.model_dump() for event in events_a] == [
        event.model_dump() for event in events_b
    ]
    assert canonical_units_json(ctx_a.units) == canonical_units_json(ctx_b.units)


def test_ttl_tick_reconstructs_statuses_through_validation() -> None:
    # Тик статусов идёт через полноценное конструирование модели — битые
    # значения не переживают конец хода незамеченными.
    ctx = make_ctx()
    unit = add_unit(ctx, uid="u", owner="p1", row=4, col=0)
    unit.statuses.append(Status(id="forced_stance", stance=Stance.DEFENSE, ttl=3))
    resolve_turn_v4(
        ctx,
        turn=1,
        spell_coin=0,
        intents=[PlayerIntents(player_id="p1")],
        mana_gain=lambda t: 0,
    )
    forced = next(s for s in unit.statuses if s.id == "forced_stance")
    assert forced.ttl == 2  # единый тик I4 прошёл валидацию
