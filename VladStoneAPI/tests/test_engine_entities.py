"""Сущности движка v4 (P2.8): стойки, статусы, паттерны, чертежи, карты.

Чертежи здесь — тестовые фикстуры, НЕ игровой контент: реальные карты
обсуждаются с владельцем по одной (COMBAT_REWORK §14).
"""

import pytest
from pydantic import ValidationError

from app.domain.combat.engine import (
    CardDefinition,
    CardType,
    CellOffset,
    CellPattern,
    SpawnZone,
    Stance,
    StancePhase,
    StanceProgram,
    Status,
    UnitBlueprint,
    UnitStats,
    current_stance,
    spawn_unit,
    tick_statuses,
    validate_blueprint,
    validate_card,
)
from app.domain.combat.engine.statuses import STATUS_FORCED_STANCE, STATUS_POISON
from app.domain.combat.models import PlayerSide

BOARD_ROWS = 5
BOARD_COLS = 5


def make_blueprint(**overrides) -> UnitBlueprint:
    """Ванильный тестовый чертёж: разогрев «Защита 2 → Атака», спавн в рядах 1–2."""
    fields = {
        "id": "fixture_warrior",
        "name": "Фикстурный воин",
        "stats": UnitStats(hp=4, damage=2, attacks_per_turn=1, move_steps=1),
        "stance_program": StanceProgram.warmup(2),
        "coverage_defense": CellPattern(
            offsets=(CellOffset(forward=1, col=0), CellOffset(forward=2, col=0))
        ),
        "coverage_attack": CellPattern(offsets=(CellOffset(forward=1, col=0),)),
        "spawn_zone": SpawnZone(rows_from_back=(1, 2)),
    }
    fields.update(overrides)
    return UnitBlueprint(**fields)


def make_unit(blueprint: UnitBlueprint, **overrides):
    unit = spawn_unit(
        blueprint,
        unit_id="u1",
        owner_id="p1",
        side=PlayerSide.BOTTOM,
        row=4,
        col=2,
    )
    return unit.model_copy(update=overrides) if overrides else unit


# --- Стойки: врождённая программа (D4: ход постановки = первый ход) ---


def test_warmup_program_counts_spawn_turn_as_first() -> None:
    program = StanceProgram.warmup(2)
    assert program.stance_at(1) == Stance.DEFENSE  # ход постановки
    assert program.stance_at(2) == Stance.DEFENSE
    assert program.stance_at(3) == Stance.ATTACK
    assert program.stance_at(99) == Stance.ATTACK


def test_catapult_program_attacks_then_camps() -> None:
    catapult = StanceProgram(
        phases=(
            StancePhase(stance=Stance.ATTACK, turns=2),
            StancePhase(stance=Stance.DEFENSE),
        )
    )
    assert catapult.stance_at(2) == Stance.ATTACK
    assert catapult.stance_at(3) == Stance.DEFENSE


def test_program_requires_open_ended_final_phase() -> None:
    with pytest.raises(ValidationError):
        StanceProgram(phases=(StancePhase(stance=Stance.ATTACK, turns=2),))
    with pytest.raises(ValidationError):
        StanceProgram(
            phases=(StancePhase(stance=Stance.ATTACK), StancePhase(stance=Stance.DEFENSE))
        )


# --- Стойка как производное + наложения (Q2 LIFO, F1 маскировка) ---


def test_forced_stance_masks_program_and_last_active_wins() -> None:
    blueprint = make_blueprint()
    unit = make_unit(blueprint)
    assert current_stance(unit, blueprint) == Stance.DEFENSE  # разогрев

    unit.statuses.append(Status(id=STATUS_FORCED_STANCE, ttl=2, stance=Stance.ATTACK))
    assert current_stance(unit, blueprint) == Stance.ATTACK

    # Второе наложение поверх — побеждает последнее активное (Q2, LIFO).
    unit.statuses.append(Status(id=STATUS_FORCED_STANCE, ttl=1, stance=Stance.DEFENSE))
    assert current_stance(unit, blueprint) == Stance.DEFENSE

    # Верхний истёк (ttl 1 — «на 1 ход») → вступает предыдущий ещё активный.
    unit.statuses = tick_statuses(unit.statuses)
    assert current_stance(unit, blueprint) == Stance.ATTACK

    # Истекли все → врождённая программа «говорит сейчас» (F1: маска, не пауза
    # расписания): юнит уже 3-й ход на поле — программа даёт Атаку.
    unit.statuses = tick_statuses(unit.statuses)
    unit.turns_on_field = 3
    assert unit.statuses == []
    assert current_stance(unit, blueprint) == Stance.ATTACK


def test_status_registry_and_shapes_are_enforced() -> None:
    with pytest.raises(ValidationError):
        Status(id="typo_status")
    with pytest.raises(ValidationError):
        Status(id=STATUS_FORCED_STANCE)  # без stance-пейлоада
    with pytest.raises(ValidationError):
        Status(id=STATUS_POISON, stance=Stance.ATTACK)  # лишний пейлоад


def test_tick_decrements_ttl_and_keeps_permanent_statuses() -> None:
    statuses = [
        Status(id=STATUS_POISON, stacks=2, ttl=2),
        Status(id=STATUS_FORCED_STANCE, stance=Stance.ATTACK),  # постоянный
    ]
    ticked = tick_statuses(statuses)
    assert [(s.id, s.ttl) for s in ticked] == [(STATUS_POISON, 1), (STATUS_FORCED_STANCE, None)]
    ticked = tick_statuses(ticked)
    assert [(s.id, s.ttl) for s in ticked] == [(STATUS_FORCED_STANCE, None)]


# --- Паттерны: H7 (вперёд — от стороны, лево/право — абсолютны) ---


def test_coverage_forward_flips_by_side_columns_stay_absolute() -> None:
    pattern = CellPattern(offsets=(CellOffset(forward=1, col=-1),))
    top = pattern.resolve(row=1, col=2, side=PlayerSide.TOP, rows=BOARD_ROWS, cols=BOARD_COLS)
    bottom = pattern.resolve(row=3, col=2, side=PlayerSide.BOTTOM, rows=BOARD_ROWS, cols=BOARD_COLS)
    # TOP идёт вниз (ряд +1), BOTTOM — вверх (ряд −1); колонка −1 у обоих левее.
    assert top == [(2, 1)]
    assert bottom == [(2, 1)]


def test_coverage_clips_cells_outside_the_board() -> None:
    pattern = CellPattern(offsets=(CellOffset(forward=2, col=0), CellOffset(forward=1, col=-1)))
    cells = pattern.resolve(row=1, col=0, side=PlayerSide.BOTTOM, rows=BOARD_ROWS, cols=BOARD_COLS)
    # forward=2 от ряда 1 вверх — за полем; col −1 от колонки 0 — за полем.
    assert cells == []


def test_spawn_zone_rows_resolve_per_side() -> None:
    zone = SpawnZone(rows_from_back=(1, 2))
    assert zone.resolve(side=PlayerSide.TOP, rows=BOARD_ROWS) == [0, 1]
    assert zone.resolve(side=PlayerSide.BOTTOM, rows=BOARD_ROWS) == [3, 4]


# --- Детерминированная сериализация (I3) ---


def test_tags_and_patterns_serialize_canonically() -> None:
    a = make_blueprint(
        tags=("tower", "structure", "tower"),
        coverage_attack=CellPattern(
            offsets=(CellOffset(forward=2, col=1), CellOffset(forward=1, col=0))
        ),
    )
    b = make_blueprint(
        tags=("structure", "tower"),
        coverage_attack=CellPattern(
            offsets=(CellOffset(forward=1, col=0), CellOffset(forward=2, col=1))
        ),
    )
    assert a.tags == ("structure", "tower")
    assert a.model_dump_json() == b.model_dump_json()


def test_unknown_tag_fails_at_construction() -> None:
    with pytest.raises(ValidationError):
        make_blueprint(tags=("strukture",))  # опечатка не должна пройти молча


# --- Юниты: потолок HP снят (Q4), минус легален внутри итерации (C3) ---


def test_unit_hp_may_exceed_base_and_go_negative() -> None:
    blueprint = make_blueprint()
    unit = make_unit(blueprint)
    assert unit.current_hp == blueprint.stats.hp
    unit.current_hp = 1000  # оверхил — легальная комба
    unit.current_hp = -3  # внутри итерации: смерть проверит граница (C5)


def test_tower_is_a_unit_blueprint_with_structure_tags() -> None:
    tower = make_blueprint(
        id="fixture_tower",
        name="Фикстурная башня",
        stats=UnitStats(hp=10, damage=1, attacks_per_turn=1, move_steps=0),
        stance_program=StanceProgram.always(Stance.DEFENSE),
        coverage_defense=CellPattern(
            offsets=(
                CellOffset(forward=1, col=0),
                CellOffset(forward=2, col=0),
                CellOffset(forward=1, col=-1),
                CellOffset(forward=1, col=1),
            )
        ),
        coverage_attack=CellPattern(),
        spawn_zone=SpawnZone(rows_from_back=(1,)),
        tags=("structure", "tower", "immovable"),
    )
    unit = spawn_unit(
        tower, unit_id="t1", owner_id="p1", side=PlayerSide.BOTTOM, row=4, col=2
    )
    assert current_stance(unit, tower) == Stance.DEFENSE
    assert unit.current_hp == 10


# --- Карты: Card ≠ Unit, токены (§10.7) ---


def test_card_payload_must_match_type() -> None:
    with pytest.raises(ValidationError):
        CardDefinition(id="c1", name="Пусто", cost=1, card_type=CardType.UNIT)
    with pytest.raises(ValidationError):
        CardDefinition(
            id="c2", name="Оба", cost=1, card_type=CardType.SPELL,
            blueprint_id="b", spell_id="s",
        )


def test_tokens_are_not_collectible() -> None:
    from app.domain.combat.engine.cards import collectible_cards

    mother = CardDefinition(
        id="necromancer", name="Некромантка", cost=7,
        card_type=CardType.UNIT, blueprint_id="fixture_warrior",
    )
    token = CardDefinition(
        id="skeleton_token", name="Скелетик", cost=1,
        card_type=CardType.UNIT, blueprint_id="fixture_warrior", collectible=False,
    )
    assert collectible_cards([mother, token]) == [mother]


def test_validation_catches_broken_references_and_bounds() -> None:
    blueprint = make_blueprint()
    validate_blueprint(blueprint, rows=BOARD_ROWS, cols=BOARD_COLS)

    with pytest.raises(ValueError, match="spawn row"):
        validate_blueprint(
            make_blueprint(spawn_zone=SpawnZone(rows_from_back=(6,))),
            rows=BOARD_ROWS,
            cols=BOARD_COLS,
        )
    with pytest.raises(ValueError, match="can never land"):
        validate_blueprint(
            make_blueprint(
                coverage_attack=CellPattern(offsets=(CellOffset(forward=5, col=0),))
            ),
            rows=BOARD_ROWS,
            cols=BOARD_COLS,
        )

    card = CardDefinition(
        id="c3", name="Ссылка в никуда", cost=1,
        card_type=CardType.UNIT, blueprint_id="missing",
    )
    with pytest.raises(ValueError, match="unknown blueprint"):
        validate_card(card, blueprints={blueprint.id: blueprint})
    spell = CardDefinition(
        id="c4", name="Спелл без скрипта", cost=1,
        card_type=CardType.SPELL, spell_id="missing",
    )
    with pytest.raises(ValueError, match="unknown spell"):
        validate_card(spell, blueprints={})
