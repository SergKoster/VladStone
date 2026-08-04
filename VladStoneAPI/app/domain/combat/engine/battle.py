"""Живой матч v4: персистентное состояние боя + оркестрация хода (этап 15в).

BattleStateV4 — то, что сериализуется в БД (движок работает над EffectContext,
который собирается из этого состояния и статичного контента content.py и
разбирается обратно). Здесь же — создание матча, резолв хода (боты + резолвер
+ винкон/суд), таймер планирования. Клиентский payload — engine/payload.py.
"""

import random
import secrets
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.domain.combat.constants import (
    MANA_CAP,
    RULESET_VERSION,
)
from app.domain.combat.engine.apply import EffectContext, EngineEvent
from app.domain.combat.engine.bot import plan_bot_intents
from app.domain.combat.engine.content import (
    BLUEPRINTS,
    CARDS,
    DECK_CARD_IDS_V4,
    SPELLS,
    V4_COLS,
    V4_ROWS,
    v4_mana_gain,
)
from app.domain.combat.engine.factory import create_participant, deal_v4_hand
from app.domain.combat.engine.intents import PlayerIntents
from app.domain.combat.engine.resolver import resolve_turn_v4
from app.domain.combat.engine.towers import (
    add_towers,
    all_teams_eliminated,
    run_judgement,
    towers_of,
    winner_team_by_towers,
)
from app.domain.combat.engine.units import UnitState
from app.domain.combat.models import (
    CombatLogEntry,
    MatchLifecycleStatus,
    MatchResult,
    PlayerState,
)
from app.domain.combat.timing import resolution_buffer_seconds, turn_duration_seconds

HAND_START_SIZE = 3
# Ход, на котором наступает «суд» (§17, решение владельца — O10-ручка).
JUDGEMENT_TURN = 50
# V3 (решение владельца): бот «жмёт Готов» через N секунд после игрока —
# окно, в котором игрок может снять готовность и поменять план.
BOT_READY_DELAY_SECONDS = 2


class BattleStateV4(BaseModel):
    id: str
    ruleset_version: int = RULESET_VERSION
    status: MatchLifecycleStatus = MatchLifecycleStatus.PLANNING
    turn: int = Field(default=1, ge=1)
    rows: int = V4_ROWS
    cols: int = V4_COLS
    mana_cap: int = MANA_CAP
    # Монетка 1-го хода: индекс игрока, кастующего заклинания первым (C1).
    spell_coin: int = 0
    # Счётчик призванных юнитов — детерминированные id токенов.
    token_seq: int = 0
    # PvP lobby creates this once and activation uses it for fair, reproducible
    # initial hands and first-spell order. It stays server-side.
    rng_seed: int | None = None
    planning_deadline: datetime | None = None
    players: list[PlayerState]
    units: list[UnitState] = Field(default_factory=list)
    log: list[CombatLogEntry] = Field(default_factory=list)
    result: MatchResult = Field(default_factory=MatchResult)
    # Последняя полная лента нужна для 409/lazy GET/reconnect: клиент не должен
    # терять реплей, если HTTP-ответ или живой WS-broadcast его не достигли.
    last_resolved_turn: int | None = Field(default=None, ge=1)
    last_events: list[EngineEvent] = Field(default_factory=list)
    # PVP-6: полный server-side снимок ДО последнего резолва. В payload он
    # сериализуется per-viewer только как resume-старт анимации; колоды остаются
    # секретом в state и никогда не уходят клиенту целиком.
    last_turn_start: dict | None = None
    # V3 — интент-стриминг (ARCH §5.2): последний присланный план каждого
    # игрока; дедлайн резолвит ЕГО, а не пустой ход. Готовность — список id;
    # ready_since ставится, когда готовы ВСЕ люди: спустя BOT_READY_DELAY_
    # SECONDS боты «жмут Готов» и наступает ранний резолв (окно отмены).
    pending_plans: dict[str, PlayerIntents] = Field(default_factory=dict)
    ready_player_ids: list[str] = Field(default_factory=list)
    ready_since: datetime | None = None
    completed_turns_by_player: dict[str, int] = Field(default_factory=dict)
    played_cards_by_player: dict[str, int] = Field(default_factory=dict)


def build_context(
    state: BattleStateV4,
    *,
    rng: random.Random | None = None,
) -> EffectContext:
    """Собрать рантайм-контекст из персистентного состояния + статичный контент.

    Контент (чертежи/карты/спеллы) не хранится в матче — подхватывается из
    content.py. deep-копий нет: резолвер мутирует контекст, apply_context
    пишет результат обратно.
    """
    return EffectContext(
        rows=state.rows,
        cols=state.cols,
        units=list(state.units),
        players=list(state.players),
        blueprints=dict(BLUEPRINTS),
        cards=dict(CARDS),
        spells=dict(SPELLS),
        deck_card_ids=tuple(DECK_CARD_IDS_V4),
        rng=rng,
        mana_cap=state.mana_cap,
        token_seq=state.token_seq,
    )


def apply_context(state: BattleStateV4, ctx: EffectContext) -> None:
    """Записать результат резолва обратно в персистентное состояние."""
    state.units = list(ctx.units)
    state.players = list(ctx.players)
    state.token_seq = ctx.token_seq


def create_v4_battle(
    *,
    match_id: str,
    user_id: int | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> BattleStateV4:
    """Новый PvE-матч v4: человек p1 (низ) против бота p2 (верх), 5 башен у каждого."""
    started_at = _as_utc(now or datetime.now(UTC))
    human = create_participant(
        player_id="p1", team=0, user_id=user_id, mana=v4_mana_gain(1)
    )
    bot = create_participant(player_id="p2", team=1, is_bot=True, mana=v4_mana_gain(1))
    deal_v4_hand(human, rng=rng)
    deal_v4_hand(bot, rng=rng)

    state = BattleStateV4(
        id=match_id,
        players=[bot, human],
        # Детерминированная монетка из id матча (не salted-hash): очередь
        # заклинаний 1-го хода публична и воспроизводима (C1, A2).
        spell_coin=_coin_from_id(match_id, len([bot, human])),
    )
    ctx = build_context(state)
    for player in state.players:
        add_towers(ctx, player)
    apply_context(state, ctx)
    state.planning_deadline = started_at + timedelta(seconds=turn_duration_seconds(1))
    return state


def create_v4_pvp_lobby(*, match_id: str, creator_user_id: int) -> BattleStateV4:
    """Create an unplayable 1v1 lobby; activation starts the actual battle.

    The second human seat deliberately has no account, cards or towers yet.
    This keeps a pending invite outside the timer worker and prevents a player
    from interacting with the board before an opponent has accepted.
    """
    creator = create_participant(
        player_id="p1", team=0, user_id=creator_user_id, mana=0
    )
    opponent = create_participant(player_id="p2", team=1, mana=0)
    return BattleStateV4(
        id=match_id,
        status=MatchLifecycleStatus.WAITING_FOR_OPPONENT,
        players=[opponent, creator],
        rng_seed=secrets.randbits(63),
    )


def activate_v4_pvp_battle(
    state: BattleStateV4,
    *,
    opponent_user_id: int,
    now: datetime | None = None,
) -> None:
    """Atomically turn a pending lobby into a playable two-human match."""
    if state.status != MatchLifecycleStatus.WAITING_FOR_OPPONENT:
        raise ValueError("PvP lobby is not waiting for an opponent")
    opponent = next((p for p in state.players if p.user_id is None and not p.is_bot), None)
    if opponent is None:
        raise ValueError("PvP lobby has no vacant human seat")

    started_at = _as_utc(now or datetime.now(UTC))
    rng = random.Random(state.rng_seed)
    opponent.user_id = opponent_user_id
    for player in state.players:
        player.mana = v4_mana_gain(1)
        deal_v4_hand(player, rng=rng)
    state.spell_coin = rng.randrange(len(state.players))
    ctx = build_context(state)
    for player in state.players:
        add_towers(ctx, player)
    apply_context(state, ctx)
    state.status = MatchLifecycleStatus.PLANNING
    state.planning_deadline = started_at + timedelta(seconds=turn_duration_seconds(1))


def store_pending_plan(
    state: BattleStateV4, player_id: str, intents: PlayerIntents
) -> None:
    """Запомнить последний план игрока (перезапись целиком, V3)."""
    state.pending_plans[player_id] = intents


def set_player_ready(
    state: BattleStateV4, player_id: str, *, ready: bool, now: datetime
) -> None:
    """Выставить/снять готовность; ready_since живёт, пока готовы ВСЕ люди."""
    ready_ids = set(state.ready_player_ids)
    if ready:
        ready_ids.add(player_id)
    else:
        ready_ids.discard(player_id)
    state.ready_player_ids = sorted(ready_ids)
    humans = [p.id for p in state.players if not p.is_bot]
    all_humans_ready = bool(humans) and all(pid in ready_ids for pid in humans)
    state.ready_since = _as_utc(now) if all_humans_ready else None


def is_early_resolve_due(state: BattleStateV4, *, now: datetime) -> bool:
    """Early resolve for all humans; only bot matches retain an undo window."""
    if state.ready_since is None:
        return False
    if not any(player.is_bot for player in state.players):
        return True
    return _as_utc(now) >= state.ready_since + timedelta(seconds=BOT_READY_DELAY_SECONDS)


def pending_intents_for(state: BattleStateV4, player_id: str) -> PlayerIntents:
    """Последний присланный план игрока; нет плана — пустой ход."""
    return state.pending_plans.get(player_id) or PlayerIntents(player_id=player_id)


def resolve_v4_turn(
    state: BattleStateV4,
    *,
    human_intents: PlayerIntents | None = None,
    human_intents_by_player: dict[str, PlayerIntents] | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[EngineEvent]:
    """Разыграть ход: намерения человека + боты, резолвер, винкон/суд, таймер.

    Возвращает список фактов движка (EngineEvent) — переводятся в клиентские
    события в payload-слое. Мутирует state.
    """
    checked_at = _as_utc(now or datetime.now(UTC))
    resolved_turn = state.turn
    # Снимок нужен reconnect-клиенту, который пропустил WS-ленту. Исключаем
    # прежний resume и уже законченную ленту, чтобы JSON состояния не рос от
    # хода к ходу: для старта анимации нужны только собственно match-данные.
    state.last_turn_start = state.model_dump(
        mode="json",
        exclude={"last_turn_start", "last_events", "last_resolved_turn"},
    )
    ctx = build_context(state, rng=rng)
    submitted = dict(human_intents_by_player or {})
    if human_intents is not None:
        submitted[human_intents.player_id] = human_intents
    intents = [
        submitted.get(player.id) or PlayerIntents(player_id=player.id)
        for player in state.players
        if not player.is_bot
    ]
    for player in state.players:
        if player.is_bot:
            intents.append(plan_bot_intents(ctx, player.id))

    # План 50-го хода обязан полностью разыграться. Суд наступает только
    # ПОСЛЕ его результата; до этого момента суд не заменяет ход пустой лентой.
    judgement_due_after_turn = state.turn >= JUDGEMENT_TURN
    events = resolve_turn_v4(
        ctx,
        turn=state.turn,
        spell_coin=state.spell_coin,
        intents=intents,
        mana_gain=v4_mana_gain,
    )
    apply_context(state, ctx)
    state.last_resolved_turn = resolved_turn
    state.last_events = events
    for player in state.players:
        completed = state.completed_turns_by_player.get(player.id, 0)
        state.completed_turns_by_player[player.id] = completed + 1
    for event in events:
        if event.kind in {"spawned", "spell_cast"} and event.player_id is not None:
            played = state.played_cards_by_player.get(event.player_id, 0)
            state.played_cards_by_player[event.player_id] = played + 1
    # V3: планы и готовность живут в рамках одного хода.
    state.pending_plans = {}
    state.ready_player_ids = []
    state.ready_since = None

    _advance_turn_and_check_end(
        state,
        ctx,
        judgement_due_after_turn=judgement_due_after_turn,
        num_events=len(events),
        now=checked_at,
    )
    return events


def _advance_turn_and_check_end(
    state: BattleStateV4,
    ctx: EffectContext,
    *,
    judgement_due_after_turn: bool,
    num_events: int,
    now: datetime,
) -> None:
    winner = winner_team_by_towers(ctx)
    if winner is not None or all_teams_eliminated(ctx):
        # Уничтожение башен всегда приоритетнее суда, включая 50-й ход.
        _finish(state, winner, end_reason="all_towers_destroyed")
        return
    if judgement_due_after_turn:
        # Дошли до суда без нокаута — лестница §17 решает исход.
        winner = run_judgement(
            {
                player.team: [t.current_hp for t in towers_of(ctx, player.id)]
                for player in state.players
            }
        )
        _finish(state, winner, end_reason="judgement")
        return

    state.turn += 1
    state.status = MatchLifecycleStatus.PLANNING
    buffer = resolution_buffer_seconds(num_events)
    # Эндшпильное сжатие таймера (DESIGN §3.5): длительность зависит от номера
    # хода; буфер анимации прибавляется сверху, как раньше.
    state.planning_deadline = now + timedelta(
        seconds=buffer + turn_duration_seconds(state.turn)
    )


def _finish(state: BattleStateV4, winner_team: int | None, *, end_reason: str) -> None:
    state.status = MatchLifecycleStatus.FINISHED
    state.planning_deadline = None
    winners = [p for p in state.players if p.team == winner_team]
    human_won = any(not p.is_bot for p in winners)
    state.result.status = "finished"
    state.result.end_reason = end_reason
    state.result.winner_team = winner_team
    state.result.winner_id = winners[0].id if len(winners) == 1 else None
    state.result.reward_coins = 5 if (winner_team is not None and human_won) else 1


def surrender_v4_battle(state: BattleStateV4, *, surrendered_player_id: str) -> None:
    """Finish an active match on a server-validated surrender request."""
    if state.status != MatchLifecycleStatus.PLANNING:
        raise ValueError(f"Combat match is {state.status.value}")
    surrendered = next(
        (player for player in state.players if player.id == surrendered_player_id), None
    )
    if surrendered is None:
        raise ValueError("Player is not a match participant")
    winner_team = next(
        (player.team for player in state.players if player.team != surrendered.team), None
    )
    _finish(state, winner_team, end_reason="surrender")
    state.result.surrendered_player_id = surrendered.id
    eligible = (
        state.completed_turns_by_player.get(surrendered.id, 0) >= 5
        and state.played_cards_by_player.get(surrendered.id, 0) > 0
    )
    state.result.reward_coins = 5 if eligible and winner_team is not None else 0


def _coin_from_id(match_id: str, num_players: int) -> int:
    digits = "".join(ch for ch in match_id if ch.isdigit()) or "0"
    return int(digits[-6:]) % num_players


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
