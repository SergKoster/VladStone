from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.schemas import ResolveTurnRequest
from app.db.session import get_db
from app.domain.combat.engine.battle import create_v4_battle, resolve_v4_turn
from app.domain.combat.engine.intents import PlayerIntents, SpawnIntent, SpellIntent
from app.domain.combat.engine.payload import v4_catalog_payload, v4_combat_response
from app.domain.combat.helpers import human_players
from app.domain.combat.models import MatchLifecycleStatus
from app.realtime.match_channels import match_channel_manager
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.combat_matches import (
    create_combat_match_record,
    expire_combat_match_if_outdated,
    expire_combat_match_if_stale,
    expire_stale_combat_matches,
    expired_match_payload,
    get_combat_match_record,
    list_active_combat_match_records,
    load_v4_battle,
    save_v4_battle,
)
from app.services.combat_turn_timers import (
    ResolvedPlanningMatch,
    resolve_expired_planning_match,
)
from app.services.rewards import claim_combat_reward

router = APIRouter(prefix="/combat", tags=["combat"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]
STALE_MATCH_TTL_HOURS = 24


@router.get("/catalog")
def get_card_catalog() -> dict:
    return {"cards": v4_catalog_payload()}


@router.post("/start")
def start_combat(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    state = create_v4_battle(
        match_id=f"local_pve_{uuid4().hex}", user_id=user.id if user else None
    )
    create_combat_match_record(db, match=state, owner_user_id=user.id if user else None)
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
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if user is None:
        return {"matches": []}
    expired_count = expire_stale_combat_matches(
        db,
        older_than=_stale_match_cutoff(),
        owner_user_id=user.id,
    )
    if expired_count:
        audit(db, user.id, "combat.matches_expired", {"expired_count": expired_count})
        db.commit()
    records = list_active_combat_match_records(db, owner_user_id=user.id)
    # Ruleset gate: matches from an older ruleset are expired here instead of
    # being offered for restore (the client must never resume them).
    outdated_ids = [record.id for record in records if expire_combat_match_if_outdated(record)]
    if outdated_ids:
        for match_id in outdated_ids:
            audit(db, user.id, "combat.match_expired_ruleset", {"match_id": match_id})
        db.commit()
        records = [record for record in records if record.id not in outdated_ids]
    return {"matches": [v4_combat_response(load_v4_battle(record))["match"] for record in records]}


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
            events=resolved.events,
            resolved_turn=resolved.resolved_turn,
        )
    return v4_combat_response(load_v4_battle(record))


@router.post("/resolve")
async def resolve_combat_turn(
    payload: ResolveTurnRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    record = _get_authorized_record(db, payload.match_id, refresh_token)
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
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None

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

    acting_player = human_players(state)[0]
    intents = _build_intents(acting_player.id, payload)
    events = resolve_v4_turn(state, human_intents=intents)
    save_v4_battle(record, state)

    try:
        reward_claimed = user is not None and claim_combat_reward(
            db, match=state, user_id=user.id
        )
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
        viewer_id=acting_player.id,
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
    spawns = tuple(
        SpawnIntent(card_id=p.card_id, row=p.row, col=p.col) for p in payload.placements
    )
    spells = tuple(
        SpellIntent(card_id=s.card_id, row=s.row, col=s.col) for s in payload.spells
    )
    return PlayerIntents(player_id=player_id, spells=spells, spawns=spawns)


def _get_authorized_record(db: Session, match_id: str, refresh_token: str | None):
    record = get_combat_match_record(db, match_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Combat match not found"
        )
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if record.owner_user_id is not None and (user is None or record.owner_user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Combat match belongs to another user",
        )
    return record


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
