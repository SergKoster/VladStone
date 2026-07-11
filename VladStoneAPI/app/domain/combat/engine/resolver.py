"""Семифазный резолвер хода v4 (COMBAT_REWORK §18.5, C1–C5).

Канонический порядок хода:
1. Заклинания — последовательно по игрокам с чередованием порядка (C1):
   монетка матча + номер хода задают первого; после заклинаний КАЖДОГО
   игрока — волна смертей.
2. (волны — внутри фазы 1, после каждого игрока)
3. Спавн юнитов + эффекты «при спавне», затем мини-волна (E1).
4. Итерации юнитов: намерения по снапшоту начала итерации (C4), атаки →
   движения → коллизии; HP живёт, в минус — легально (C3); граница каждой
   итерации — волна смертей (C5).
5. Эффекты конца хода: яд → (слот отложенных заклинаний) → тик разогрева и
   ttl всех статусов (I4, D3).
6. Волна смертей конца хода.
7. Добор карт (кэп руки) + мана следующего хода (расписание — параметр, R13).

Волновая модель (C5 + Q5): на границе под-фазы все с hp≤0 ИЛИ doomed гибнут
одновременно; их on_death отыгрывают в порядке чтения поля по текущему
состоянию; новые hp≤0 — следующая волна; каждый юнит гибнет и триггерит ровно
один раз; воскрешений нет.
"""

from collections.abc import Callable

from app.domain.combat.board import mana_gain_for_turn
from app.domain.combat.deck import draw_card
from app.domain.combat.engine.abilities import TriggerHook
from app.domain.combat.engine.apply import (
    HAND_CAP,
    EffectContext,
    EngineEvent,
    apply_effect,
    select_targets,
)
from app.domain.combat.engine.cards import CardType
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.patterns import forward_direction
from app.domain.combat.engine.stances import Stance
from app.domain.combat.engine.statuses import STATUS_POISON, tick_statuses
from app.domain.combat.engine.tags import TAG_TOWER
from app.domain.combat.engine.units import UnitState, current_stance, spawn_unit
from app.domain.combat.engine.validation import validate_state
from app.domain.combat.models import PlayerSide, PlayerState

# Страховка от бесконечной фазы итераций (аналог MVP): юнит с 1 шагом
# физически не может действовать дольше, чем «высота поля × запас».
ITERATION_SAFETY_FACTOR = 4


def resolve_turn_v4(
    ctx: EffectContext,
    *,
    turn: int,
    spell_coin: int,
    intents: list[PlayerIntents],
    mana_gain: Callable[[int], int] = mana_gain_for_turn,
) -> list[EngineEvent]:
    """Разыграть один ход над контекстом (мутирует ctx), вернуть факты.

    spell_coin — результат монетки 1-го хода (индекс игрока в ctx.players,
    кастующего первым на ходу 1); дальше порядок чередуется по номеру хода.
    Инкремент номера хода и победа по башням — вне резолвера (интеграция).
    """
    intents_by_player = {entry.player_id: entry for entry in intents}
    order = _player_order(ctx, turn=turn, spell_coin=spell_coin)
    events: list[EngineEvent] = []
    # Инварианты проверяются на входе и после каждой фазы/итерации: битое
    # состояние падает у источника с именем контрольной точки (ARCH §5.1).
    validate_state(ctx, checkpoint="entry")

    # Фазы 1–2: заклинания с чередованием; волна после каждого игрока (C1).
    for player in order:
        entry = intents_by_player.get(player.id)
        if entry is not None:
            for spell in entry.spells:
                events += _stamp(_cast_spell(ctx, player, spell), "spells")
        events += _stamp(run_death_wave(ctx), "spells")
        validate_state(ctx, checkpoint=f"spells:{player.id}")

    # Фаза 3: спавны (тот же порядок игроков, что у заклинаний) + on_spawn,
    # затем мини-волна (E1).
    for player in order:
        entry = intents_by_player.get(player.id)
        if entry is not None:
            for spawn in entry.spawns:
                events += _stamp(_spawn_from_hand(ctx, player, spawn), "spawn")
    events += _stamp(run_death_wave(ctx), "spawn")
    validate_state(ctx, checkpoint="spawn")

    # Фаза 4: итерации юнитов по снапшот-намерениям (C4), волна на границе
    # каждой итерации (C5).
    events += _run_iterations(ctx)

    # Фазы 5–6: эффекты конца хода в фикс-порядке (D3), затем волна.
    events += _stamp(_end_of_turn_effects(ctx), "end")
    events += _stamp(run_death_wave(ctx), "end")
    validate_state(ctx, checkpoint="end")

    # Фаза 7: добор + мана следующего хода.
    events += _stamp(_draw_and_mana(ctx, turn=turn, mana_gain=mana_gain), "draw")
    validate_state(ctx, checkpoint="draw")
    return events


def _player_order(ctx: EffectContext, *, turn: int, spell_coin: int) -> list[PlayerState]:
    """Порядок игроцких под-фаз этого хода (C1): монетка + чередование.

    Для 1v1 — буквально канон; для будущих N участников — та же ротация
    списка (engine-обобщение, уточнить при коопе).
    """
    first = (spell_coin + turn - 1) % len(ctx.players)
    return list(ctx.players[first:]) + list(ctx.players[:first])


def _stamp(events: list[EngineEvent], phase: str, iteration: int | None = None):
    for event in events:
        event.phase = phase
        if iteration is not None and event.iteration is None:
            event.iteration = iteration
    return events


# --- Фаза 1: заклинания ---


def _cast_spell(ctx: EffectContext, player: PlayerState, intent: SpellIntent):
    card = ctx.cards.get(intent.card_id)
    if card is None or card.card_type != CardType.SPELL or card.spell_id not in ctx.spells:
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    if intent.card_id not in player.hand or player.mana < card.cost:
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    origin = (intent.row, intent.col) if intent.row is not None and intent.col is not None else None
    script = ctx.spells[card.spell_id]
    if origin is None and any(action.target.scope != "board" for action in script.actions):
        # Точечному скрипту нужна точка применения — намерение битое.
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]

    player.hand.remove(intent.card_id)
    player.mana -= card.cost
    events = [EngineEvent(kind="spell_cast", player_id=player.id, card_id=card.id)]
    for action in script.actions:
        targets = select_targets(action.target, ctx, caster_side=player.side, origin=origin)
        events += apply_effect(
            action.effect, ctx, caster_id=player.id, targets=targets, cell=origin
        )
    return events


# --- Фаза 3: спавны из руки ---


def _spawn_from_hand(ctx: EffectContext, player: PlayerState, intent: SpawnIntent):
    card = ctx.cards.get(intent.card_id)
    if (
        card is None
        or card.card_type != CardType.UNIT
        or not card.collectible
        or card.blueprint_id not in ctx.blueprints
    ):
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    if intent.card_id not in player.hand or player.mana < card.cost:
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    blueprint = ctx.blueprints[card.blueprint_id]
    allowed_rows = blueprint.spawn_zone.resolve(side=player.side, rows=ctx.rows)
    if intent.row not in allowed_rows or not 0 <= intent.col < ctx.cols:
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]

    push_events = _resolve_spawn_push(ctx, player.side, intent.row, intent.col)
    if push_events is None:
        return [EngineEvent(kind="fizzled", player_id=player.id, card_id=intent.card_id)]

    player.hand.remove(intent.card_id)
    player.mana -= card.cost
    ctx.token_seq += 1
    unit = spawn_unit(
        blueprint,
        unit_id=f"{player.id}_{card.id}_{ctx.token_seq}",
        owner_id=player.id,
        side=player.side,
        row=intent.row,
        col=intent.col,
    )
    ctx.units.append(unit)
    events = push_events + [
        EngineEvent(
            kind="spawned",
            unit_id=unit.id,
            player_id=player.id,
            card_id=card.id,
            to_cell=(unit.row, unit.col),
        )
    ]
    # Эффекты «при спавне» — сразу; их смерти соберёт мини-волна фазы (E1).
    events += _fire_abilities(ctx, unit, TriggerHook.ON_SPAWN)
    return events


def _fire_abilities(ctx: EffectContext, unit: UnitState, trigger: TriggerHook):
    """Отыграть способности юнита на хуке; факт ability_triggered — перед
    эффектами, чтобы клиент мог подсветить источник до последствий."""
    blueprint = ctx.blueprint_of(unit)
    events: list[EngineEvent] = []
    for ability in blueprint.abilities:
        if ability.trigger != trigger:
            continue
        events.append(
            EngineEvent(
                kind="ability_triggered",
                unit_id=unit.id,
                trigger=trigger.value,
                from_cell=(unit.row, unit.col),
            )
        )
        targets = select_targets(
            ability.target, ctx, caster_side=unit.side, origin=(unit.row, unit.col)
        )
        events += apply_effect(
            ability.effect,
            ctx,
            caster_id=unit.owner_id,
            targets=targets,
            cell=(unit.row, unit.col),
        )
    return events


def _resolve_spawn_push(
    ctx: EffectContext, side: PlayerSide, row: int, col: int
) -> list[EngineEvent] | None:
    """Освободить спавн-клетку толчками; None — поставить нельзя.

    Свои толкаются цепочкой вперёд (§13.5, H9: упёрлась в край или во
    врага — нельзя). Одиночный враг толкается на клетку дальше (S1/MVP);
    за ним занято — нельзя.
    """
    occupant = ctx.unit_at(row, col)
    if occupant is None:
        return []
    forward = forward_direction(side)
    if occupant.side != side:
        behind_row = row + forward
        if not (0 <= behind_row < ctx.rows) or ctx.unit_at(behind_row, col) is not None:
            return None
        occupant.row = behind_row
        return [
            EngineEvent(
                kind="pushed",
                unit_id=occupant.id,
                from_cell=(row, col),
                to_cell=(behind_row, col),
            )
        ]
    # Цепочка своих: от спавн-клетки вперёд до первой пустой.
    chain: list[UnitState] = []
    cursor = row
    while True:
        unit = ctx.unit_at(cursor, col)
        if unit is None:
            break
        if unit.side != side:
            return None  # цепочка упёрлась во врага (H9)
        chain.append(unit)
        cursor += forward
        if not 0 <= cursor < ctx.rows:
            return None  # упёрлась в край (H9)
    events = []
    # Двигаем с дальнего конца, чтобы не затирать клетки друг друга.
    for unit in reversed(chain):
        before = unit.row
        unit.row += forward
        events.append(
            EngineEvent(
                kind="pushed",
                unit_id=unit.id,
                from_cell=(before, col),
                to_cell=(unit.row, col),
            )
        )
    return events


# --- Фаза 4: итерации юнитов ---


def _run_iterations(ctx: EffectContext) -> list[EngineEvent]:
    for unit in ctx.units:
        blueprint = ctx.blueprint_of(unit)
        unit.remaining_steps = blueprint.stats.move_steps
        unit.remaining_attacks = blueprint.stats.attacks_per_turn

    events: list[EngineEvent] = []
    for iteration in range(1, ctx.rows * ITERATION_SAFETY_FACTOR + 1):
        acted, iteration_events = _run_single_iteration(ctx)
        events += _stamp(iteration_events, "iterations", iteration)
        if not acted:
            break
        # Граница итерации — волна смертей (C5); внутри итерации никто не
        # умирал (C3), волна собирает всех ушедших в минус разом.
        events += _stamp(run_death_wave(ctx), "iterations", iteration)
        validate_state(ctx, checkpoint=f"iteration:{iteration}")
    return events


def _run_single_iteration(ctx: EffectContext) -> tuple[bool, list[EngineEvent]]:
    """Одна итерация: намерения по снапшоту (C4) → атаки → движения."""
    # Снапшот занятости: клетка, занятая в начале итерации, считается занятой
    # всю итерацию (гармошка; встречный swap блокируется сам собой).
    occupied = {(unit.row, unit.col) for unit in ctx.units}
    attack_intents: list[tuple[UnitState, UnitState]] = []
    move_claims: dict[tuple[int, int], list[UnitState]] = {}

    for unit in sorted(ctx.units, key=lambda u: (u.row, u.col)):
        blueprint = ctx.blueprint_of(unit)
        stance = current_stance(unit, blueprint)
        target = None
        if unit.remaining_attacks > 0:
            target = _pick_attack_target(ctx, unit, stance)
        if target is not None:
            # Приоритет «сначала атака» (H1, решение владельца) — и в Атаке,
            # и в Защите; одно действие за итерацию.
            attack_intents.append((unit, target))
            continue
        if stance == Stance.ATTACK and unit.remaining_steps > 0:
            ahead = (unit.row + forward_direction(unit.side), unit.col)
            if 0 <= ahead[0] < ctx.rows and ahead not in occupied:
                move_claims.setdefault(ahead, []).append(unit)

    events: list[EngineEvent] = []
    acted = False
    for attacker, target in attack_intents:
        attacker.remaining_attacks -= 1
        before = target.current_hp
        target.current_hp -= ctx.blueprint_of(attacker).stats.damage  # минус легален (C3)
        events.append(
            EngineEvent(
                kind="attack",
                unit_id=attacker.id,
                target_id=target.id,
                amount=ctx.blueprint_of(attacker).stats.damage,
                before=before,
                after=target.current_hp,
                from_cell=(attacker.row, attacker.col),
                to_cell=(target.row, target.col),
            )
        )
        acted = True

    for cell, claimants in sorted(move_claims.items()):
        if len(claimants) == 1:
            unit = claimants[0]
            unit.remaining_steps -= 1
            before = unit.row
            unit.row, unit.col = cell
            events.append(
                EngineEvent(
                    kind="moved",
                    unit_id=unit.id,
                    from_cell=(before, unit.col),
                    to_cell=cell,
                )
            )
            acted = True
            continue
        # Коллизия: двое в одну пустую клетку (C4 гарантирует, что это
        # единственный вид коллизии). Встречные — враги: размен ударами;
        # оба остаются, шаг потрачен.
        first, second = sorted(claimants, key=lambda u: (u.row, u.col))
        for unit in (first, second):
            unit.remaining_steps -= 1
        events.append(
            EngineEvent(
                kind="collision",
                unit_id=first.id,
                target_id=second.id,
                to_cell=cell,
            )
        )
        for unit, other in ((first, second), (second, first)):
            damage = ctx.blueprint_of(other).stats.damage
            before = unit.current_hp
            unit.current_hp -= damage
            events.append(
                EngineEvent(
                    kind="damage",
                    unit_id=unit.id,
                    amount=damage,
                    before=before,
                    after=unit.current_hp,
                )
            )
        acted = True
    return acted, events


def _pick_attack_target(ctx: EffectContext, unit: UnitState, stance: Stance) -> UnitState | None:
    """Цель атаки по покрытию стойки; базовая атака бьёт только врагов (F5).

    Тай-брейк §13.6 (владелец): самая ближняя к герою владельца юнита →
    при равенстве самая крайняя левая (лево абсолютно, H7).
    """
    blueprint = ctx.blueprint_of(unit)
    cells = set(
        blueprint.coverage(stance).resolve(
            row=unit.row, col=unit.col, side=unit.side, rows=ctx.rows, cols=ctx.cols
        )
    )
    enemies = [
        candidate
        for candidate in ctx.units
        if candidate.side != unit.side and (candidate.row, candidate.col) in cells
    ]
    if not enemies:
        return None
    if TAG_TOWER in blueprint.tags:
        # Тай-брейк башни (C2): своя линия — ближняя к башне раньше; иначе
        # самая левая цель на соседних линиях.
        return min(
            enemies,
            key=lambda enemy: (
                enemy.col != unit.col,
                abs(enemy.row - unit.row),
                enemy.col,
            ),
        )
    # «Ближе к герою владельца» = ближе к краю поля владельца юнита:
    # для BOTTOM — большие ряды, для TOP — меньшие. Башня на призрачном ряду
    # автоматически самая дальняя цель: юнит бьёт её, когда некого больше.
    towards_owner = -1 if unit.side == PlayerSide.BOTTOM else 1
    return min(enemies, key=lambda enemy: (towards_owner * enemy.row, enemy.col))


# --- Фазы 5–7: конец хода, добор, мана ---


def _end_of_turn_effects(ctx: EffectContext) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    # 1) Яд: −stacks HP каждому носителю (порядок чтения поля).
    for unit in sorted(ctx.units, key=lambda u: (u.row, u.col)):
        poison = next((s for s in unit.statuses if s.id == STATUS_POISON), None)
        if poison is None:
            continue
        before = unit.current_hp
        unit.current_hp -= poison.stacks
        events.append(
            EngineEvent(
                kind="damage",
                unit_id=unit.id,
                amount=poison.stacks,
                before=before,
                after=unit.current_hp,
                status_id=STATUS_POISON,
            )
        )
    # 2) Слот отложенных заклинаний («добей, если 1 HP») — контента пока нет.
    # 3) Способности «в конце хода» (I4: on_turn_end — фаза 5), порядок чтения
    # поля. Прочие хуки (on_turn_start/on_attack/on_damaged/on_stance_change)
    # подключаются, когда появится первая карта с ними.
    for unit in sorted(list(ctx.units), key=lambda u: (u.row, u.col)):
        events += _fire_abilities(ctx, unit, TriggerHook.ON_TURN_END)
    # 4) Тик разогрева (D4: +1 к ходам на поле) и ЕДИНЫЙ тик ttl статусов (I4);
    # истёкшие статусы оставляют факт — клиент гасит бейдж/подсветку.
    for unit in ctx.units:
        unit.turns_on_field += 1
        before_ids = [status.id for status in unit.statuses]
        unit.statuses = tick_statuses(unit.statuses)
        after_ids = {status.id for status in unit.statuses}
        for status_id in before_ids:
            if status_id not in after_ids:
                events.append(
                    EngineEvent(kind="status_expired", unit_id=unit.id, status_id=status_id)
                )
    return events


def _draw_and_mana(
    ctx: EffectContext, *, turn: int, mana_gain: Callable[[int], int]
) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    for player in ctx.players:
        # Участник без deck-цикла (скриптовый бот MVP) не добирает.
        if (player.deck or player.hand) and len(player.hand) < HAND_CAP:
            if draw_card(player) is not None:
                events.append(EngineEvent(kind="card_drawn", player_id=player.id, amount=1))
        before = player.mana
        player.mana = min(ctx.mana_cap, player.mana + mana_gain(turn + 1))
        if player.mana != before:
            events.append(
                EngineEvent(
                    kind="mana_changed",
                    player_id=player.id,
                    amount=player.mana - before,
                    before=before,
                    after=player.mana,
                )
            )
    return events


# --- Волновая модель смертей (C5 + Q5) ---


def run_death_wave(ctx: EffectContext) -> list[EngineEvent]:
    """Волны на границе под-фазы: гибнут все с hp≤0 или doomed, разом.

    Помеченные удаляются ДО отыгрыша посмертных эффектов — воскрешений нет
    (посмертный хилл не может нацелиться в уже умершего). on_death — в
    порядке чтения поля, к текущему состоянию; новые hp≤0 — следующая волна.
    """
    events: list[EngineEvent] = []
    while True:
        wave = sorted(
            (unit for unit in ctx.units if unit.current_hp <= 0 or unit.doomed),
            key=lambda unit: (unit.row, unit.col),
        )
        if not wave:
            break
        for unit in wave:
            ctx.units.remove(unit)
            events.append(
                EngineEvent(
                    kind="unit_died",
                    unit_id=unit.id,
                    from_cell=(unit.row, unit.col),
                    before=max(0, unit.current_hp),
                    after=0,
                )
            )
        for unit in wave:
            events += _fire_abilities(ctx, unit, TriggerHook.ON_DEATH)
    return events
