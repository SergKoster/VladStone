from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.schemas import ReadyTurnRequest, ResolveTurnRequest
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.combat.engine.battle import (
    create_v4_battle,
    resolve_v4_turn,
    set_player_ready,
    store_pending_plan,
    surrender_v4_battle,
)
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.payload import (
    v4_catalog_payload,
    v4_combat_response,
    v4_status_catalog_payload,
)
from app.domain.combat.helpers import human_players
from app.domain.combat.models import MatchLifecycleStatus
from app.realtime.match_channels import match_channel_manager
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.battle_admission import BattleAdmissionService
from app.services.combat_matches import (
    create_combat_match_record,
    expire_combat_match_if_outdated,
    expire_combat_match_if_stale,
    expired_match_payload,
    get_combat_match_participant,
    get_combat_match_record,
    load_v4_battle,
    save_v4_battle,
)
from app.services.combat_turn_timers import (
    ResolvedPlanningMatch,
    resolve_expired_planning_match,
)
from app.services.profiles import display_handle_for_user
from app.services.rate_limit import allow_attempt
from app.services.rewards import claim_combat_reward

router = APIRouter(prefix="/combat", tags=["combat"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]
STALE_MATCH_TTL_HOURS = 24
EXTERNAL_ENVIRONMENTS = {"production", "staging"}
START_LIMIT = 10
TURN_ACTION_LIMIT = 60


@router.get("/catalog")
def get_card_catalog() -> dict:
    return {"cards": v4_catalog_payload(), "statuses": v4_status_catalog_payload()}


@router.post("/start")
def start_combat(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _combat_user_or_401(db, refresh_token)
    _require_combat_rate(f"combat-start:{user.id if user else 'local'}", limit=START_LIMIT)
    if user is None:
        state = create_v4_battle(match_id=f"local_pve_{uuid4().hex}")
        create_combat_match_record(db, match=state, owner_user_id=None)
    else:
        admitted = BattleAdmissionService(db).admit_new_match(
            user_id=user.id,
            owner_user_id=user.id,
            build_state=lambda: create_v4_battle(
                match_id=f"local_pve_{uuid4().hex}",
                user_id=user.id,
                display_name=display_handle_for_user(db, user.id),
            ),
        )
        if not admitted.created:
            raise _active_match_conflict(admitted.record.id)
        assert admitted.state is not None
        state = admitted.state
    audit(
        db,
        user.id if user else None,
        "combat.match_started",
        {"match_id": state.id, "status": state.status.value},
    )
    db.commit()
    return v4_combat_response(state)


@router.get("/active")
def list_active_combat(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _combat_user_or_401(db, refresh_token)
    if user is None:
        return {"matches": []}
    record = BattleAdmissionService(db).current_active_match(user_id=user.id)
    # The service may have reconciled a stale/ruleset-expired slot. Commit its
    # cleanup before returning so every tab observes the same active match.
    db.commit()
    return {
        "matches": [
            v4_combat_response(
                load_v4_battle(record),
                viewer_id=_viewer_id_for_record(db, load_v4_battle(record), record, refresh_token),
            )["match"]
            for record in [record]
            if record is not None
        ]
    }


@router.get("/{match_id}")
async def get_combat_match(
    match_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    record = _get_authorized_record(db, match_id, refresh_token)
    if _expire_record_if_stale(db, record) or _expire_record_if_outdated(db, record):
        await match_channel_manager.broadcast_expired(match_id)
        return expired_match_payload(match_id)
    resolved = _resolve_expired_record_if_needed(db, record)
    if resolved is not None:
        await match_channel_manager.broadcast_match_update(
            resolved.state,
            events=resolved.events,
            resolved_turn=resolved.resolved_turn,
        )
        return v4_combat_response(
            resolved.state,
            viewer_id=_viewer_id_for_record(db, resolved.state, record, refresh_token),
            events=resolved.events,
            resolved_turn=resolved.resolved_turn,
        )
    state = load_v4_battle(record)
    return v4_combat_response(
        state,
        viewer_id=_viewer_id_for_record(db, state, record, refresh_token),
    )


@router.post("/plan")
async def submit_turn_plan(
    payload: ResolveTurnRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    """V3: интент-стриминг — сохранить последний план хода (без резолва).

    Дедлайн/ранний резолв применят именно этот план; клиент шлёт его по мере
    планирования с debounce. Просроченный ход — 409, результат придёт по WS.
    """
    state, record, viewer_id = await _load_planning_state_or_409(db, payload, refresh_token)
    _require_combat_rate(
        _turn_rate_key(db, refresh_token),
        limit=TURN_ACTION_LIMIT,
    )
    store_pending_plan(state, viewer_id, _build_intents(viewer_id, payload))
    _save_state_or_409(db, record, state)
    return {"ok": True, "turn": state.turn}


@router.post("/ready")
async def set_turn_readiness(
    payload: ReadyTurnRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    """V3: «Готов» (с финальным планом атомарно) или снятие готовности.

    Резолв здесь НЕ происходит: когда готовы все люди, бот «жмёт Готов» через
    BOT_READY_DELAY_SECONDS (окно отмены), после чего ход дорезолвит
    таймер-воркер/ленивый путь и разошлёт результат по WS.
    """
    state, record, viewer_id = await _load_planning_state_or_409(db, payload, refresh_token)
    _require_combat_rate(
        _turn_rate_key(db, refresh_token),
        limit=TURN_ACTION_LIMIT,
    )
    store_pending_plan(state, viewer_id, _build_intents(viewer_id, payload))
    set_player_ready(state, viewer_id, ready=payload.ready, now=datetime.now(UTC))
    audit(
        db,
        record.owner_user_id,
        "combat.turn_ready" if payload.ready else "combat.turn_unready",
        {"match_id": state.id, "turn": state.turn},
    )
    _save_state_or_409(db, record, state)
    # Ready is public lobby state, unlike the private plan itself. This lets a
    # PvP opponent see confirmation promptly without learning any placements.
    await match_channel_manager.broadcast_match_update(state)
    return {"ok": True, "turn": state.turn, "ready": payload.ready}


@router.post("/{match_id}/surrender")
async def surrender_combat_match(
    match_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    """Authenticated, idempotent-through-optimistic-lock surrender transition."""
    user = _combat_user_or_401(db, refresh_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    _require_combat_rate(_turn_rate_key(db, refresh_token), limit=TURN_ACTION_LIMIT)
    record = _get_authorized_record(db, match_id, refresh_token)
    if _expire_record_if_stale(db, record) or _expire_record_if_outdated(db, record):
        await match_channel_manager.broadcast_expired(match_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Combat match is unavailable"
        )
    if _resolve_expired_record_if_needed(db, record) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Combat turn deadline has passed"
        )
    state = load_v4_battle(record)
    viewer_id = _viewer_id_for_record(db, state, record, refresh_token)
    try:
        surrender_v4_battle(state, surrendered_player_id=viewer_id or "")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    save_v4_battle(record, state)
    winner = next(
        (player for player in state.players if player.team == state.result.winner_team), None
    )
    try:
        if winner is not None and winner.user_id is not None:
            claim_combat_reward(db, match=state, user_id=winner.user_id)
        audit(db, user.id, "combat.match_surrendered", {"match_id": match_id, "turn": state.turn})
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Combat match ended elsewhere"
        ) from None
    response = v4_combat_response(state, viewer_id=viewer_id)
    await match_channel_manager.broadcast_match_update(state)
    return response


async def _load_planning_state_or_409(
    db: Session,
    payload: ResolveTurnRequest,
    refresh_token: str | None,
):
    """Общие ворота /plan и /ready: гейты, ленивый дорезолв, актуальность хода."""
    record = _get_authorized_record(db, payload.match_id, refresh_token)
    if _expire_record_if_stale(db, record) or _expire_record_if_outdated(db, record):
        await match_channel_manager.broadcast_expired(payload.match_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat ruleset changed; match expired",
        )
    resolved = _resolve_expired_record_if_needed(db, record)
    if resolved is not None:
        await match_channel_manager.broadcast_match_update(
            resolved.state,
            events=resolved.events,
            resolved_turn=resolved.resolved_turn,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn deadline has passed",
        )
    state = load_v4_battle(record)
    if state.status != MatchLifecycleStatus.PLANNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Combat match is {state.status.value}",
        )
    if payload.turn != state.turn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn is no longer current",
        )
    return state, record, _viewer_id_for_record(db, state, record, refresh_token)


def _save_state_or_409(db: Session, record, state) -> None:
    save_v4_battle(record, state)
    try:
        db.commit()
    except StaleDataError:
        # Ход конкурентно дорезолвлен (воркер/дедлайн) — план опоздал; клиент
        # получит результат по WS и пришлёт план следующего хода.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn was already resolved elsewhere",
        ) from None


@router.post("/resolve")
async def resolve_combat_turn(
    payload: ResolveTurnRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    record = _get_authorized_record(db, payload.match_id, refresh_token)
    _require_combat_rate(
        _turn_rate_key(db, refresh_token),
        limit=TURN_ACTION_LIMIT,
    )
    if _expire_record_if_stale(db, record) or _expire_record_if_outdated(db, record):
        await match_channel_manager.broadcast_expired(payload.match_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat ruleset changed; match expired",
        )
    deadline_resolved = _resolve_expired_record_if_needed(db, record)
    if deadline_resolved is not None:
        await match_channel_manager.broadcast_match_update(
            deadline_resolved.state,
            events=deadline_resolved.events,
            resolved_turn=deadline_resolved.resolved_turn,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn deadline has passed",
        )
    user = _combat_user_or_401(db, refresh_token)

    state = load_v4_battle(record)
    if state.status != MatchLifecycleStatus.PLANNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Combat match is {state.status.value}",
        )
    if payload.turn != state.turn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn is no longer current",
        )

    if len(human_players(state)) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manual resolve is unavailable for PvP matches",
        )
    acting_player_id = _viewer_id_for_record(db, state, record, refresh_token)
    intents = _build_intents(acting_player_id, payload)
    events = resolve_v4_turn(state, human_intents=intents)
    save_v4_battle(record, state)

    try:
        reward_claimed = user is not None and claim_combat_reward(db, match=state, user_id=user.id)
        audit(
            db,
            user.id if user else None,
            "combat.turn_resolved",
            {
                "match_id": state.id,
                "turn": payload.turn,
                "next_turn": state.turn,
                "status": state.status.value,
                "events_count": len(events),
            },
        )
        if state.result.status == "finished":
            audit(
                db,
                user.id if user else None,
                "combat.match_finished",
                {
                    "match_id": state.id,
                    "winner_team": state.result.winner_team,
                    "reward_coins": state.result.reward_coins,
                },
            )
        if reward_claimed:
            audit(
                db,
                user.id if user else None,
                "combat.reward_claimed",
                {"match_id": state.id, "coins": state.result.reward_coins},
            )
        db.commit()
    except StaleDataError:
        # A concurrent resolver (timer worker or a duplicate request) saved
        # this match first; drop our attempt — their result is authoritative.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn was already resolved elsewhere",
        ) from None

    response = v4_combat_response(
        state,
        viewer_id=acting_player_id,
        events=events,
        resolved_turn=payload.turn,
    )
    await match_channel_manager.broadcast_match_update(
        state,
        events=events,
        resolved_turn=payload.turn,
    )
    return response


def _build_intents(player_id: str, payload: ResolveTurnRequest) -> PlayerIntents:
    spawns = tuple(SpawnIntent(card_id=p.card_id, row=p.row, col=p.col) for p in payload.placements)
    spells = tuple(SpellIntent(card_id=s.card_id, row=s.row, col=s.col) for s in payload.spells)
    return PlayerIntents(player_id=player_id, spells=spells, spawns=spawns)


def _get_authorized_record(db: Session, match_id: str, refresh_token: str | None):
    record = get_combat_match_record(db, match_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combat match not found")
    user = _combat_user_or_401(db, refresh_token)
    if user is not None:
        participant = get_combat_match_participant(db, match_id=match_id, user_id=user.id)
        # owner fallback keeps active matches created before participant
        # projection usable after deploy; new matches always have a row.
        if participant is None and record.owner_user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Combat match belongs to another user",
            )
    elif record.owner_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Combat match belongs to another user",
        )
    return record


def _viewer_id_for_record(
    db: Session,
    state,
    record,
    refresh_token: str | None,
) -> str | None:
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if user is not None:
        participant = get_combat_match_participant(db, match_id=record.id, user_id=user.id)
        if participant is not None:
            return participant.player_id
        player = next((item for item in state.players if item.user_id == user.id), None)
        if player is not None:
            return player.id
    humans = human_players(state)
    return humans[0].id if humans else None


def _combat_user_or_401(db: Session, refresh_token: str | None):
    """Внешний бой требует сессию; local сохраняет отдельный demo-путь."""
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if get_settings().environment in EXTERNAL_ENVIRONMENTS and user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def _turn_rate_key(db: Session, refresh_token: str | None) -> str:
    """Limit each authenticated actor independently, including PvP joiners."""
    user = _combat_user_or_401(db, refresh_token)
    return f"combat-turn:{user.id if user else 'local'}"


def _require_combat_rate(key: str, *, limit: int) -> None:
    # Локальные тесты/ручная отладка не должны делить глобальное in-memory окно.
    if get_settings().environment not in EXTERNAL_ENVIRONMENTS:
        return
    if not allow_attempt(key, limit=limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts",
        )


def _active_match_conflict(match_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "active_match_exists", "current_match_id": match_id},
    )


def _expire_record_if_stale(db: Session, record) -> bool:
    if not expire_combat_match_if_stale(record, older_than=_stale_match_cutoff()):
        return False
    audit(db, record.owner_user_id, "combat.match_expired", {"match_id": record.id})
    db.commit()
    return True


def _expire_record_if_outdated(db: Session, record) -> bool:
    if not expire_combat_match_if_outdated(record):
        return False
    audit(db, record.owner_user_id, "combat.match_expired_ruleset", {"match_id": record.id})
    db.commit()
    return True


def _resolve_expired_record_if_needed(
    db: Session,
    record,
) -> ResolvedPlanningMatch | None:
    try:
        resolved = resolve_expired_planning_match(db, record)
        if resolved is None:
            return None
        audit(
            db,
            record.owner_user_id,
            "combat.turn_deadline_resolved",
            {
                "match_id": resolved.state.id,
                "turn": resolved.resolved_turn,
                "status": resolved.state.status.value,
            },
        )
        db.commit()
    except StaleDataError:
        # Someone else resolved this match first; re-read their state and
        # behave as if no deadline resolve was needed here.
        db.rollback()
        db.refresh(record)
        return None
    return resolved


def _stale_match_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(hours=STALE_MATCH_TTL_HOURS)
