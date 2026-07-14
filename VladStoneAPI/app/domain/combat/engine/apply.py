"""Исполнение примитивов Effect над состоянием боя (ARCH §5.1).

Правила, зашитые здесь и не зависящие от карт:
- цели всегда обходятся в порядке чтения поля (ряд, колонка) — единый
  тайбрейк всего боя;
- урон уводит HP в минус, смертей внутри эффекта нет — их проверяют волны на
  границах под-фаз (C3/C5, резолвер P2.10);
- структуры (тег structure) иммунны к урону эффектов по умолчанию (F4),
  неподвижные (immovable) — к смене стойки и пушу (F3);
- каждый применённый примитив оставляет EngineEvent-факты — сырьё для
  клиентских combat-событий (P2.12).
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.combat.deck import draw_card
from app.domain.combat.engine.abilities import SpellScript
from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.effects import (
    ApplyStatus,
    BuffStats,
    ChangeStance,
    DealDamage,
    DrawCard,
    Effect,
    Execute,
    GrantTag,
    Heal,
    KillIf,
    ModifyBudget,
    ModifyMana,
    Push,
    SpawnToken,
)
from app.domain.combat.engine.patterns import forward_direction
from app.domain.combat.engine.stances import Stance
from app.domain.combat.engine.statuses import Status, apply_forced_stance
from app.domain.combat.engine.tags import (
    TAG_IMMOVABLE,
    TAG_STRUCTURE,
    TAG_TOWER,
    validate_tags,
)
from app.domain.combat.engine.targeting import TargetSelector, TargetSide
from app.domain.combat.engine.units import (
    UnitBlueprint,
    UnitState,
    current_stance,
    effective_stats,
    spawn_unit,
    unit_tags,
)
from app.domain.combat.models import PlayerSide, PlayerState

# Кэп руки v4 (§18.2/E3): добор при полной руке пропускается, карта остаётся
# в колоде.
HAND_CAP = 6


class EngineEvent(BaseModel):
    """Факт движка — сырьё для combat-событий клиента (P2.12, translate.py)."""

    kind: Literal[
        "damage",
        "heal",
        "status_applied",
        "status_expired",
        "stance_changed",
        "tag_granted",
        "pushed",
        "killed",
        "token_spawned",
        "card_drawn",
        "mana_changed",
        "fizzled",
        "stat_buffed",
        "budget_modified",
        # Факты резолвера (P2.10):
        "spell_cast",
        "spawned",
        "attack",
        "moved",
        "collision",
        "unit_died",
        "ability_triggered",
    ]
    unit_id: str | None = None
    # Второй участник факта: цель атаки/коллизии.
    target_id: str | None = None
    player_id: str | None = None
    # Числовые before/after — всегда про ВЕЛИЧИНУ (HP, мана), не координаты.
    amount: int | None = None
    before: int | None = None
    after: int | None = None
    status_id: str | None = None
    stance: Stance | None = None
    tag: str | None = None
    # Хук, породивший факт (ability_triggered).
    trigger: str | None = None
    # Клетки «откуда/куда»: атака — клетка актора → клетка цели; движение/
    # толчок — путь юнита; спавн — to_cell; смерть — from_cell.
    from_cell: tuple[int, int] | None = None
    to_cell: tuple[int, int] | None = None
    card_id: str | None = None
    # Проставляются резолвером: фаза хода и номер итерации внутри фазы 4.
    phase: str | None = None
    iteration: int | None = None
    # Полная область визуального эффекта (включая пустые клетки). Это только
    # наблюдаемость для клиента: правила и выбор реальных целей не меняет.
    affected_cells: list[tuple[int, int]] = Field(default_factory=list)
    snapshot: dict = Field(default_factory=dict)


@dataclass
class EffectContext:
    """Рантайм-срез боя, над которым исполняются эффекты.

    players — R12-участники (мана/колода/рука живут на них); units — юниты v4.
    Резолвер (P2.10) собирает контекст из MatchState и разбирает обратно.
    """

    rows: int
    cols: int
    units: list[UnitState]
    players: list[PlayerState]
    blueprints: dict[str, UnitBlueprint]
    cards: dict[str, CardDefinition] = field(default_factory=dict)
    spells: dict[str, SpellScript] = field(default_factory=dict)
    mana_cap: int = 10
    # Счётчик токенов матча — детерминированные id призванных юнитов.
    token_seq: int = 0

    def blueprint_of(self, unit: UnitState) -> UnitBlueprint:
        return self.blueprints[unit.blueprint_id]

    def player_by_id(self, player_id: str) -> PlayerState:
        for player in self.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Unknown player {player_id}")

    def unit_at(self, row: int, col: int) -> UnitState | None:
        for unit in self.units:
            if unit.row == row and unit.col == col:
                return unit
        return None

    def opponents_of(self, player_id: str) -> list[PlayerState]:
        me = self.player_by_id(player_id)
        return [player for player in self.players if player.team != me.team]


def board_snapshot(ctx: EffectContext) -> dict:
    """Лёгкий снимок живой доски в момент эмиссии события (A1)."""
    # Локальный импорт разрывает цикл content -> towers -> apply.
    from app.domain.combat.engine.content import CARDS

    units = []
    for unit in sorted(ctx.units, key=lambda item: item.id):
        if unit.current_hp <= 0 or unit.doomed:
            continue
        blueprint = ctx.blueprint_of(unit)
        units.append(
            {
                "id": unit.id,
                "card_id": unit.blueprint_id if unit.blueprint_id in CARDS else None,
                "side": unit.side.value,
                "row": unit.row,
                "col": unit.col,
                "current_hp": unit.current_hp,
                "max_hp": effective_stats(unit, blueprint).hp,
                "stance": current_stance(unit, blueprint).value,
                "is_tower": TAG_TOWER in unit_tags(unit, blueprint),
            }
        )
    return {
        "units": units,
        "players": [{"id": player.id, "mana": player.mana} for player in ctx.players],
    }


def _event(ctx: EffectContext, **data) -> EngineEvent:
    """Создать факт и сразу зафиксировать состояние после его мутации."""
    return EngineEvent(**data, snapshot=board_snapshot(ctx))


def select_targets(
    selector: TargetSelector,
    ctx: EffectContext,
    *,
    caster_side: PlayerSide,
    origin: tuple[int, int] | None = None,
) -> list[UnitState]:
    """Юниты-цели селектора в каноническом порядке чтения поля (ряд, колонка).

    origin — точка применения (клетка каста / клетка юнита-носителя);
    для scope="board" не нужна. Паттерн разворачивается от origin по стороне
    кастера (H7: вперёд — от стороны, колонки абсолютны).
    """
    if selector.scope == "board":
        candidates = list(ctx.units)
    else:
        if origin is None:
            raise ValueError(f"scope={selector.scope!r} requires an origin cell")
        if selector.scope in ("cell", "self"):
            # self — клетка носителя способности (origin и есть его клетка).
            cells = {origin}
        else:
            assert selector.pattern is not None  # гарантировано валидатором
            cells = set(
                selector.pattern.resolve(
                    row=origin[0],
                    col=origin[1],
                    side=caster_side,
                    rows=ctx.rows,
                    cols=ctx.cols,
                )
            )
        candidates = [unit for unit in ctx.units if (unit.row, unit.col) in cells]

    result = []
    for unit in candidates:
        if selector.side == TargetSide.ALLY and unit.side != caster_side:
            continue
        if selector.side == TargetSide.ENEMY and unit.side == caster_side:
            continue
        if selector.tag is not None and selector.tag not in unit_tags(
            unit, ctx.blueprint_of(unit)
        ):
            continue
        result.append(unit)
    return sorted(result, key=lambda unit: (unit.row, unit.col))


def affected_cells(
    selector: TargetSelector,
    ctx: EffectContext,
    *,
    caster_side: PlayerSide,
    origin: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """Клетки области эффекта для клиентской анимации, включая пустые."""
    if selector.scope == "board":
        return [(row, col) for row in range(ctx.rows) for col in range(ctx.cols)]
    if origin is None:
        return []
    if selector.scope in ("cell", "self"):
        cells = [origin]
    else:
        assert selector.pattern is not None
        cells = selector.pattern.resolve(
            row=origin[0],
            col=origin[1],
            side=caster_side,
            rows=ctx.rows,
            cols=ctx.cols,
        )
    # Башни живут на призрачных рядах -1/rows, но клеточный overlay рисуется
    # только над самим полем.
    return sorted((row, col) for row, col in cells if 0 <= row < ctx.rows)


def apply_effect(
    effect: Effect,
    ctx: EffectContext,
    *,
    caster_id: str,
    targets: list[UnitState] | None = None,
    cell: tuple[int, int] | None = None,
) -> list[EngineEvent]:
    """Применить один примитив; вернуть факты для событий.

    targets — юниты из select_targets (юнит-скоуп примитивы); cell — клетка
    применения (spawn_token); player-скоуп примитивы (draw_card, modify_mana)
    работают от caster_id и игнорируют targets.
    """
    if isinstance(effect, DealDamage):
        return _deal_damage(effect, ctx, targets or [])
    if isinstance(effect, Heal):
        return _heal(effect, ctx, targets or [])
    if isinstance(effect, ApplyStatus):
        return _apply_status(effect, ctx, targets or [])
    if isinstance(effect, ChangeStance):
        return _change_stance(effect, ctx, targets or [])
    if isinstance(effect, GrantTag):
        return _grant_tag(effect, ctx, targets or [])
    if isinstance(effect, Push):
        return _push(effect, ctx, targets or [])
    if isinstance(effect, KillIf):
        return _kill_if(effect, ctx, targets or [])
    if isinstance(effect, Execute):
        return _execute(ctx, targets or [])
    if isinstance(effect, BuffStats):
        return _buff_stats(effect, ctx, targets or [])
    if isinstance(effect, ModifyBudget):
        return _modify_budget(effect, ctx, targets or [])
    if isinstance(effect, SpawnToken):
        return _spawn_token(effect, ctx, caster_id=caster_id, cell=cell)
    if isinstance(effect, DrawCard):
        return _draw_card(effect, ctx, caster_id=caster_id)
    if isinstance(effect, ModifyMana):
        return _modify_mana(effect, ctx, caster_id=caster_id)
    raise TypeError(f"Unknown effect {effect!r}")  # недостижимо при валидном союзе


def _deal_damage(
    effect: DealDamage, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        # F4: структуры не получают урон от эффектов, пока карта не пробивает
        # это явно (affects_structures).
        if not effect.affects_structures and TAG_STRUCTURE in unit_tags(
            unit, ctx.blueprint_of(unit)
        ):
            continue
        before = unit.current_hp
        unit.current_hp -= effect.amount  # минус легален внутри итерации (C3)
        events.append(
            _event(
                ctx,
                kind="damage",
                unit_id=unit.id,
                amount=effect.amount,
                before=before,
                after=unit.current_hp,
            )
        )
    return events


def _heal(
    effect: Heal, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        before = unit.current_hp
        unit.current_hp += effect.amount  # потолка нет (Q4)
        events.append(
            _event(
                ctx,
                kind="heal",
                unit_id=unit.id,
                amount=effect.amount,
                before=before,
                after=unit.current_hp,
            )
        )
    return events


def _apply_status(
    effect: ApplyStatus, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        # F4-расширение: статусы эффектов не липнут к структурам — иначе яд
        # обошёл бы иммунитет башен к урону заклинаний (тик яда бьёт напрямую).
        # Карта, которой нужно травить башни, получит явный флаг при дизайне.
        if TAG_STRUCTURE in unit_tags(unit, ctx.blueprint_of(unit)):
            continue
        existing = next((s for s in unit.statuses if s.id == effect.status_id), None)
        if existing is None:
            unit.statuses.append(
                Status(id=effect.status_id, stacks=effect.stacks, ttl=effect.ttl)
            )
        else:
            # Стаки складываются (канон яда §5); срок — больший из двух,
            # None (постоянный) побеждает. Дизайн конкретных статусов может
            # уточнить это правило вместе с картами.
            merged_ttl = (
                None
                if existing.ttl is None or effect.ttl is None
                else max(existing.ttl, effect.ttl)
            )
            merged = Status(
                id=existing.id,
                stacks=existing.stacks + effect.stacks,
                ttl=merged_ttl,
                stance=existing.stance,
            )
            unit.statuses[unit.statuses.index(existing)] = merged
        events.append(
            _event(
                ctx,
                kind="status_applied",
                unit_id=unit.id,
                status_id=effect.status_id,
                amount=effect.stacks,
            )
        )
    return events


def _change_stance(
    effect: ChangeStance, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        # F3: неподвижные (башни) не переводятся — башня не должна «поехать».
        if TAG_IMMOVABLE in unit_tags(unit, ctx.blueprint_of(unit)):
            continue
        unit.statuses = apply_forced_stance(unit.statuses, stance=effect.stance, ttl=effect.ttl)
        events.append(
            _event(ctx, kind="stance_changed", unit_id=unit.id, stance=effect.stance)
        )
    return events


def _grant_tag(effect: GrantTag, ctx: EffectContext, targets: list[UnitState]) -> list[EngineEvent]:
    events = []
    for unit in targets:
        if effect.tag in unit_tags(unit, ctx.blueprint_of(unit)):
            continue  # уже есть — идемпотентно, без события
        unit.granted_tags = validate_tags((*unit.granted_tags, effect.tag))
        events.append(_event(ctx, kind="tag_granted", unit_id=unit.id, tag=effect.tag))
    return events


def _push(effect: Push, ctx: EffectContext, targets: list[UnitState]) -> list[EngineEvent]:
    events = []
    for unit in targets:
        if TAG_IMMOVABLE in unit_tags(unit, ctx.blueprint_of(unit)):
            continue
        step = forward_direction(unit.side)
        if effect.direction == "backward":
            step = -step
        moved = 0
        row = unit.row
        # Двигаем клетка за клеткой; упёрлись в юнита/край — остановка (как у
        # спавн-толчка H9: препятствие не пробивается).
        for _ in range(effect.cells):
            next_row = row + step
            if not (0 <= next_row < ctx.rows) or ctx.unit_at(next_row, unit.col) is not None:
                break
            row = next_row
            moved += 1
        if moved == 0:
            events.append(_event(ctx, kind="fizzled", unit_id=unit.id))
            continue
        before_row = unit.row
        unit.row = row
        events.append(
            _event(
                ctx,
                kind="pushed",
                unit_id=unit.id,
                from_cell=(before_row, unit.col),
                to_cell=(row, unit.col),
            )
        )
    return events


def _kill_if(
    effect: KillIf, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        if unit.doomed:
            continue  # уже казнён — волна добьёт (C5)
        # F4-расширение: казнь не берёт структуры — иначе «Жнец» сносил бы
        # башни (винкон) в обход иммунитета к урону заклинаний.
        if TAG_STRUCTURE in unit_tags(unit, ctx.blueprint_of(unit)):
            continue
        condition = True
        if effect.status_id is not None:
            status = next((s for s in unit.statuses if s.id == effect.status_id), None)
            condition = status is not None and status.stacks >= effect.min_stacks
        if condition and effect.max_hp is not None:
            condition = unit.current_hp <= effect.max_hp
        if not condition:
            continue
        # Q5: казнь неотменяема — пометка «обречён», волна на границе под-фазы
        # убивает помеченных независимо от HP; лечение не спасает (в отличие
        # от урона, где вампиризм может вытащить из минуса — C3).
        unit.doomed = True
        events.append(
            _event(
                ctx,
                kind="killed",
                unit_id=unit.id,
                before=unit.current_hp,
                after=0,
            )
        )
    return events


def _execute(ctx: EffectContext, targets: list[UnitState]) -> list[EngineEvent]:
    events = []
    for unit in targets:
        if unit.doomed:
            continue
        # F4: казнь структуры не берёт — как и kill_if.
        if TAG_STRUCTURE in unit_tags(unit, ctx.blueprint_of(unit)):
            continue
        unit.doomed = True  # Q5: неотменяемо, волна добьёт независимо от HP
        events.append(
            _event(
                ctx,
                kind="killed",
                unit_id=unit.id,
                before=unit.current_hp,
                after=0,
            )
        )
    return events


def _buff_stats(
    effect: BuffStats, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        bonus = unit.permanent_bonuses
        unit.permanent_bonuses = bonus.model_copy(
            update={
                "hp": bonus.hp + effect.hp,
                "damage": bonus.damage + effect.damage,
                "attacks_per_turn": bonus.attacks_per_turn + effect.attacks_per_turn,
                "move_steps": bonus.move_steps + effect.move_steps,
            }
        )
        if effect.hp:
            unit.current_hp += effect.hp  # бафф здоровья лечит на ту же величину
        events.append(
            _event(
                ctx,
                kind="stat_buffed",
                unit_id=unit.id,
                amount=effect.hp or effect.damage or effect.attacks_per_turn
                or effect.move_steps,
            )
        )
    return events


def _modify_budget(
    effect: ModifyBudget, ctx: EffectContext, targets: list[UnitState]
) -> list[EngineEvent]:
    events = []
    for unit in targets:
        unit.remaining_steps = max(0, unit.remaining_steps + effect.steps)
        unit.remaining_attacks = max(0, unit.remaining_attacks + effect.attacks)
        events.append(
            _event(
                ctx,
                kind="budget_modified",
                unit_id=unit.id,
                amount=effect.steps or effect.attacks,
            )
        )
    return events


def _spawn_token(
    effect: SpawnToken,
    ctx: EffectContext,
    *,
    caster_id: str,
    cell: tuple[int, int] | None,
) -> list[EngineEvent]:
    if cell is None:
        raise ValueError("spawn_token requires a target cell")
    card = ctx.cards.get(effect.card_id)
    if card is None or card.card_type != CardType.UNIT:
        # Битая ссылка — баг контента: падаем громко (I7), не тихо в бою.
        raise ValueError(f"spawn_token references invalid card {effect.card_id!r}")
    row, col = cell
    if not (0 <= row < ctx.rows and 0 <= col < ctx.cols) or ctx.unit_at(row, col) is not None:
        # I5: клетка занята/вне поля — эффект детерминированно фейлится.
        return [
            _event(ctx, kind="fizzled", card_id=effect.card_id, to_cell=(row, col))
        ]
    assert card.blueprint_id is not None  # гарантировано валидатором карты
    blueprint = ctx.blueprints[card.blueprint_id]
    owner = ctx.player_by_id(caster_id)
    ctx.token_seq += 1
    token = spawn_unit(
        blueprint,
        unit_id=f"{caster_id}_{card.id}_{ctx.token_seq}",
        owner_id=owner.id,
        side=owner.side,
        row=row,
        col=col,
    )
    ctx.units.append(token)
    return [
        _event(
            ctx,
            kind="token_spawned",
            unit_id=token.id,
            player_id=owner.id,
            card_id=card.id,
            to_cell=(row, col),
        )
    ]


def _draw_card(effect: DrawCard, ctx: EffectContext, *, caster_id: str) -> list[EngineEvent]:
    events = []
    caster = ctx.player_by_id(caster_id)
    receivers = [caster] if effect.who == "self" else ctx.opponents_of(caster_id)
    for player in receivers:
        for _ in range(effect.count):
            # Кэп руки (E3): полная рука — добор пропущен, карта не сгорает.
            if len(player.hand) >= HAND_CAP:
                break
            # Участник без deck-цикла (скриптовый бот MVP): добор — no-op,
            # иначе перетасовка выдала бы ему колоду из воздуха.
            if not player.deck and not player.hand:
                break
            if draw_card(player) is None:
                break
            events.append(_event(ctx, kind="card_drawn", player_id=player.id, amount=1))
    return events


def _modify_mana(effect: ModifyMana, ctx: EffectContext, *, caster_id: str) -> list[EngineEvent]:
    events = []
    caster = ctx.player_by_id(caster_id)
    receivers = [caster] if effect.who == "self" else ctx.opponents_of(caster_id)
    for player in receivers:
        before = player.mana
        player.mana = max(0, min(ctx.mana_cap, player.mana + effect.amount))
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
