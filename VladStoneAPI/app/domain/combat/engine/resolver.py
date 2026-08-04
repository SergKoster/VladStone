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
from app.domain.combat.engine.abilities import TriggerHook
from app.domain.combat.engine.apply import (
    HAND_CAP,
    EffectContext,
    EngineEvent,
    affected_cells,
    apply_effect,
    board_snapshot,
    select_targets,
)
from app.domain.combat.engine.cards import CardType
from app.domain.combat.engine.deck import draw_v4_card
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.patterns import forward_direction
from app.domain.combat.engine.stances import Stance
from app.domain.combat.engine.statuses import (
    QuestCondition,
    StatusDecay,
    status_spec,
    tick_statuses,
)
from app.domain.combat.engine.tags import TAG_STRUCTURE, TAG_TOWER
from app.domain.combat.engine.units import (
    UnitState,
    current_stance,
    effective_stats,
    spawn_unit,
    unit_tags,
)
from app.domain.combat.engine.validation import validate_state
from app.domain.combat.models import PlayerSide, PlayerState, UnitWaitReason

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

    # Бюджеты действий обновляются В НАЧАЛЕ хода (не в фазе итераций!):
    # временные бафы бюджета из спелл-фазы (Самурай) должны дожить до
    # итераций, а не стираться сбросом.
    for unit in ctx.units:
        stats = effective_stats(unit, ctx.blueprint_of(unit))
        unit.remaining_steps = stats.move_steps
        unit.remaining_attacks = stats.attacks_per_turn

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
    # Накопленные факты хода передаются внутрь: квест-условия (§14.1
    # «Задание») проверяются по ним.
    events += _stamp(_end_of_turn_effects(ctx, events), "end")
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


def _event(ctx: EffectContext, **data) -> EngineEvent:
    """Создать факт резолвера со снимком доски в текущий момент."""
    return EngineEvent(**data, snapshot=board_snapshot(ctx))


# --- Фаза 1: заклинания ---


def _cast_spell(ctx: EffectContext, player: PlayerState, intent: SpellIntent):
    card = ctx.cards.get(intent.card_id)
    if card is None or card.card_type != CardType.SPELL or card.spell_id not in ctx.spells:
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    if intent.card_id not in player.hand or player.mana < card.cost:
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    origin = (intent.row, intent.col) if intent.row is not None and intent.col is not None else None
    script = ctx.spells[card.spell_id]
    if origin is None and any(action.target.scope != "board" for action in script.actions):
        # Точечному скрипту нужна точка применения — намерение битое.
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]

    player.hand.remove(intent.card_id)
    player.mana -= card.cost
    visual_cells = sorted(
        {
            cell
            for action in script.actions
            for cell in affected_cells(
                action.target, ctx, caster_side=player.side, origin=origin
            )
        }
    )
    events = [
        _event(
            ctx,
            kind="spell_cast",
            player_id=player.id,
            card_id=card.id,
            to_cell=origin,
            affected_cells=visual_cells,
        )
    ]
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
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    if intent.card_id not in player.hand or player.mana < card.cost:
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]
    blueprint = ctx.blueprints[card.blueprint_id]
    allowed_rows = blueprint.spawn_zone.resolve(side=player.side, rows=ctx.rows)
    if intent.row not in allowed_rows or not 0 <= intent.col < ctx.cols:
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]

    push_events = _resolve_spawn_push(ctx, player.side, intent.row, intent.col)
    if push_events is None:
        return [_event(ctx, kind="fizzled", player_id=player.id, card_id=intent.card_id)]

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
        _event(
            ctx,
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
        visual_cells = affected_cells(
            ability.target,
            ctx,
            caster_side=unit.side,
            origin=(unit.row, unit.col),
        )
        events.append(
            _event(
                ctx,
                kind="ability_triggered",
                unit_id=unit.id,
                trigger=trigger.value,
                effect_kind=ability.effect.kind,
                from_cell=(unit.row, unit.col),
                affected_cells=visual_cells,
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
            _event(
                ctx,
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
            _event(
                ctx,
                kind="pushed",
                unit_id=unit.id,
                from_cell=(before, col),
                to_cell=(unit.row, col),
            )
        )
    return events


# --- Фаза 4: итерации юнитов ---


def _run_iterations(ctx: EffectContext) -> list[EngineEvent]:
    # Бюджеты выданы в начале хода (см. resolve_turn_v4) и при спавне —
    # здесь их не трогаем, чтобы не стереть временные бафы спелл-фазы.
    events: list[EngineEvent] = []
    acted_unit_ids: set[str] = set()
    for iteration in range(1, ctx.rows * ITERATION_SAFETY_FACTOR + 1):
        acted, iteration_events = _run_single_iteration(ctx)
        acted_unit_ids.update(_acted_unit_ids(iteration_events))
        events += _stamp(iteration_events, "iterations", iteration)
        if not acted:
            # U1: объяснение добавляется один раз в конце фазы итераций, а не
            # в каждой пустой микроитерации. Оно не меняет ни бюджет, ни поле.
            events += _stamp(
                _unit_wait_events(ctx, acted_unit_ids), "iterations", iteration
            )
            break
        # Граница итерации — волна смертей (C5); внутри итерации никто не
        # умирал (C3), волна собирает всех ушедших в минус разом.
        events += _stamp(run_death_wave(ctx), "iterations", iteration)
        validate_state(ctx, checkpoint=f"iteration:{iteration}")
    return events


def _acted_unit_ids(events: list[EngineEvent]) -> set[str]:
    """Участники реального действия фазы итераций, не наблюдатели его факта."""
    ids: set[str] = set()
    for event in events:
        if event.kind in {"attack", "moved"} and event.unit_id is not None:
            ids.add(event.unit_id)
        elif event.kind == "collision":
            if event.unit_id is not None:
                ids.add(event.unit_id)
            if event.target_id is not None:
                ids.add(event.target_id)
    return ids


def _unit_wait_events(ctx: EffectContext, acted_unit_ids: set[str]) -> list[EngineEvent]:
    """Один серверный факт U1 для каждого живого юнита без действия за ход."""
    events: list[EngineEvent] = []
    for unit in sorted(ctx.units, key=lambda item: (item.row, item.col, item.id)):
        if unit.id in acted_unit_ids:
            continue
        blueprint = ctx.blueprint_of(unit)
        # Структуры (башни) не ходят по определению — их «ожидание» не факт
        # для игрока, а шум: раздувает ленту и анимационный буфер дедлайна.
        if TAG_STRUCTURE in unit_tags(unit, blueprint):
            continue
        events.append(
            _event(
                ctx,
                kind="unit_waited",
                unit_id=unit.id,
                wait_reason=_unit_wait_reason(ctx, unit, current_stance(unit, blueprint)),
                from_cell=(unit.row, unit.col),
            )
        )
    return events


def _unit_wait_reason(
    ctx: EffectContext, unit: UnitState, stance: Stance
) -> UnitWaitReason:
    if unit.remaining_attacks <= 0 and unit.remaining_steps <= 0:
        return UnitWaitReason.NO_ACTION_BUDGET
    if stance == Stance.DEFENSE:
        return UnitWaitReason.DEFENSE_NO_TARGET
    if unit.remaining_steps <= 0:
        return UnitWaitReason.ATTACK_NO_TARGET
    ahead = (unit.row + forward_direction(unit.side), unit.col)
    if not (0 <= ahead[0] < ctx.rows) or ctx.unit_at(*ahead) is not None:
        return UnitWaitReason.PATH_BLOCKED
    # При ненулевом бюджете и свободном пути сюда по правилам не попасть:
    # юнит должен был бы сделать ход. Оставляем серверный fallback, а не
    # заставляем клиент угадывать причину.
    return UnitWaitReason.ATTACK_NO_TARGET


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
        # Урон — только через effective_stats: стойко-зависимые статы и
        # перманентные бафы (расширение №3) обязаны учитываться.
        damage = effective_stats(attacker, ctx.blueprint_of(attacker)).damage
        before = target.current_hp
        target.current_hp -= damage  # минус легален (C3)
        events.append(
            _event(
                ctx,
                kind="attack",
                unit_id=attacker.id,
                target_id=target.id,
                amount=damage,
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
                _event(
                    ctx,
                    kind="moved",
                    unit_id=unit.id,
                    from_cell=(before, unit.col),
                    to_cell=cell,
                )
            )
            acted = True
            continue
        # Коллизия: двое в одну пустую клетку (C4 гарантирует, что это
        # единственный вид коллизии). Оба остаются, шаг потрачен. Урон наносит
        # только участник с оставшейся атакой — и тратит её ровно один раз.
        # При вертикальном движении претендентов
        # больше двух не бывает — если будущая механика (диагонали?) это
        # сломает, падаем громко, а не тихо теряем чей-то ход.
        if len(claimants) != 2:
            raise AssertionError(
                f"Collision at {cell} has {len(claimants)} claimants; "
                "the resolver only knows head-on pairs"
            )
        first, second = sorted(claimants, key=lambda u: (u.row, u.col))
        for unit in (first, second):
            unit.remaining_steps -= 1
        events.append(
            _event(
                ctx,
                kind="collision",
                unit_id=first.id,
                target_id=second.id,
                to_cell=cell,
            )
        )
        for attacker, target in ((first, second), (second, first)):
            if attacker.remaining_attacks <= 0:
                continue
            attacker.remaining_attacks -= 1
            damage = effective_stats(attacker, ctx.blueprint_of(attacker)).damage
            before = target.current_hp
            target.current_hp -= damage
            events.append(
                _event(
                    ctx,
                    kind="damage",
                    unit_id=target.id,
                    amount=damage,
                    before=before,
                    after=target.current_hp,
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


def _end_of_turn_effects(ctx: EffectContext, turn_events: list[EngineEvent]) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    # 1) Тики статусов по спекам (яд §14.1: −1 HP; будущие регены — tick_heal),
    # порядок чтения поля.
    for unit in sorted(ctx.units, key=lambda u: (u.row, u.col)):
        for status in list(unit.statuses):
            spec = status_spec(status.id)
            if spec.tick_damage:
                before = unit.current_hp
                unit.current_hp -= spec.tick_damage
                events.append(
                    _event(
                        ctx,
                        kind="damage",
                        unit_id=unit.id,
                        amount=spec.tick_damage,
                        before=before,
                        after=unit.current_hp,
                        status_id=status.id,
                    )
                )
            if spec.tick_heal:
                before = unit.current_hp
                unit.current_hp += spec.tick_heal
                events.append(
                    _event(
                        ctx,
                        kind="heal",
                        unit_id=unit.id,
                        amount=spec.tick_heal,
                        before=before,
                        after=unit.current_hp,
                        status_id=status.id,
                    )
                )
    # 2) Квесты (слот «отложенных», D3): условие проверяется по фактам хода;
    # выполнил — награда и клеймо снимается; клеймо истекает этим ходом без
    # выполнения — кара (§14.1 «Задание»).
    events += _run_quests(ctx, turn_events + events)
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
                    _event(
                        ctx,
                        kind="status_expired",
                        unit_id=unit.id,
                        status_id=status_id,
                    )
                )
    return events


def _run_quests(ctx: EffectContext, facts: list[EngineEvent]) -> list[EngineEvent]:
    """Квест-статусы (§14.1): проверка условий по фактам хода в фазе 5.

    Выполнил — награда (эффекты on_success на носителя) и клеймо снимается;
    не выполнил и клеймо истекает этим ходом (ttl 1) — кара (on_fail).
    """
    events: list[EngineEvent] = []
    for unit in sorted(list(ctx.units), key=lambda u: (u.row, u.col)):
        for status in list(unit.statuses):
            spec = status_spec(status.id)
            if spec.quest is None:
                continue
            fulfilled = _quest_condition_met(spec.quest.condition, unit, facts)
            expiring = spec.decay == StatusDecay.TTL and status.ttl == 1
            if not fulfilled and not expiring:
                continue  # клеймо ещё висит — проверим в следующем ходу
            outcome = spec.quest.on_success if fulfilled else spec.quest.on_fail
            events.append(
                _event(
                    ctx,
                    kind="ability_triggered",
                    unit_id=unit.id,
                    trigger=f"quest:{status.id}:{'success' if fulfilled else 'fail'}",
                    from_cell=(unit.row, unit.col),
                )
            )
            for effect in outcome:
                events += apply_effect(effect, ctx, caster_id=unit.owner_id, targets=[unit])
            if fulfilled:
                unit.statuses = [s for s in unit.statuses if s is not status]
                events.append(
                    _event(
                        ctx,
                        kind="status_expired",
                        unit_id=unit.id,
                        status_id=status.id,
                    )
                )
    return events


def _quest_condition_met(
    condition: QuestCondition, unit: UnitState, facts: list[EngineEvent]
) -> bool:
    if condition == QuestCondition.ATTACKED_UNIT_THAT_DIED_THIS_TURN:
        # Только явные атаки (коллизии — не «атаковал»); цель умерла в этот ход.
        died = {fact.unit_id for fact in facts if fact.kind == "unit_died"}
        return any(
            fact.kind == "attack" and fact.unit_id == unit.id and fact.target_id in died
            for fact in facts
        )
    raise ValueError(f"Unknown quest condition {condition!r}")  # недостижимо при валидном enum


def _draw_and_mana(
    ctx: EffectContext, *, turn: int, mana_gain: Callable[[int], int]
) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    for player in ctx.players:
        if len(player.hand) < HAND_CAP:
            if draw_v4_card(player, card_ids=ctx.deck_card_ids, rng=ctx.rng) is not None:
                events.append(_event(ctx, kind="card_drawn", player_id=player.id, amount=1))
        before = player.mana
        player.mana = min(ctx.mana_cap, player.mana + mana_gain(turn + 1))
        if player.mana != before:
            events.append(
                _event(
                    ctx,
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
                _event(
                    ctx,
                    kind="unit_died",
                    unit_id=unit.id,
                    from_cell=(unit.row, unit.col),
                    before=max(0, unit.current_hp),
                    after=0,
                )
            )
        for unit in wave:
            events += _fire_abilities(ctx, unit, TriggerHook.ON_DEATH)
        # Наблюдатели смерти (§14.1 Самурай): за КАЖДУЮ смерть врага в текущем
        # покрытии живого наблюдателя — его способность срабатывает. Порядок:
        # умершие в порядке волны, наблюдатели — по чтению поля.
        for dead in wave:
            for observer in sorted(ctx.units, key=lambda u: (u.row, u.col)):
                if observer.side == dead.side:
                    continue
                blueprint = ctx.blueprint_of(observer)
                if all(
                    ability.trigger != TriggerHook.ON_ENEMY_DEATH_IN_COVERAGE
                    for ability in blueprint.abilities
                ):
                    continue
                coverage = blueprint.coverage(current_stance(observer, blueprint)).resolve(
                    row=observer.row,
                    col=observer.col,
                    side=observer.side,
                    rows=ctx.rows,
                    cols=ctx.cols,
                )
                if (dead.row, dead.col) not in coverage:
                    continue
                events += _fire_abilities(
                    ctx, observer, TriggerHook.ON_ENEMY_DEATH_IN_COVERAGE
                )
    return events
