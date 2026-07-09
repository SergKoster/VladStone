from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.schemas import ResolveTurnRequest
from app.db.session import get_db
from app.domain.catalog import starter_catalog_payload
from app.domain.combat.deck import covers_hand
from app.domain.combat.models import MatchLifecycleStatus, MatchState, PlayerSide, Position
from app.domain.combat.rules import (
    apply_placements,
    apply_simple_bot_turn,
    create_demo_match,
    create_player_match,
    resolve_turn,
)
from app.realtime.match_channels import match_channel_manager
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.combat_matches import (
    create_combat_match_record,
    expire_combat_match_if_outdated,
    expire_combat_match_if_stale,
    expire_stale_combat_matches,
    get_combat_match_record,
    list_active_combat_match_records,
    load_match,
    save_match,
)
from app.services.combat_payloads import combat_response
from app.services.combat_turn_timers import resolve_expired_planning_match
from app.services.dev_logging import append_dev_log
from app.services.rewards import claim_combat_reward

router = APIRouter(prefix="/combat", tags=["combat"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]
STALE_MATCH_TTL_HOURS = 24


@router.get("/catalog")
def get_card_catalog() -> dict:
    return {"cards": starter_catalog_payload()}


@router.get("/demo")
def get_combat_demo() -> dict:
    match = create_demo_match()
    resolved = resolve_turn(match)
    return {
        "initial": combat_response(match),
        "resolved": combat_response(resolved),
    }


@router.post("/start")
def start_combat(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    match = create_player_match()
    create_combat_match_record(db, match=match, owner_user_id=user.id if user else None)
    audit(
        db,
        user.id if user else None,
        "combat.match_started",
        {"match_id": match.id, "status": match.status.value},
    )
    db.commit()
    append_dev_log("combat-server.jsonl", "combat_start", {"match": _match_snapshot(match)})
    return combat_response(match)


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
        audit(
            db,
            user.id,
            "combat.matches_expired",
            {"expired_count": expired_count},
        )
        db.commit()
        append_dev_log(
            "combat-server.jsonl",
            "combat_matches_expired",
            {"user_id": user.id, "expired_count": expired_count},
        )
    records = list_active_combat_match_records(db, owner_user_id=user.id)
    # Ruleset gate: matches from an older ruleset are expired here instead of
    # being offered for restore (the client must never resume them).
    outdated_ids = [
        record.id for record in records if expire_combat_match_if_outdated(record) is not None
    ]
    if outdated_ids:
        for match_id in outdated_ids:
            audit(db, user.id, "combat.match_expired_ruleset", {"match_id": match_id})
        db.commit()
        append_dev_log(
            "combat-server.jsonl",
            "combat_matches_expired_ruleset",
            {"user_id": user.id, "match_ids": outdated_ids},
        )
        records = [record for record in records if record.id not in outdated_ids]
    return {
        "matches": [
            combat_response(load_match(record))["match"]
            for record in records
        ]
    }


@router.get("/{match_id}")
async def get_combat_match(
    match_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    record = _get_authorized_record(db, match_id, refresh_token)
    _expire_record_if_stale(db, record)
    resolved = _resolve_expired_record_if_needed(db, record)
    if resolved is not None:
        await match_channel_manager.broadcast_match_update(resolved)
        return combat_response(resolved)
    return combat_response(load_match(record))


@router.post("/resolve")
async def resolve_combat_turn(
    payload: ResolveTurnRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    record = _get_authorized_record(db, payload.match_id, refresh_token)
    _expire_record_if_stale(db, record)
    deadline_resolved = _resolve_expired_record_if_needed(db, record)
    if deadline_resolved is not None:
        await match_channel_manager.broadcast_match_update(deadline_resolved)
        if deadline_resolved.status == MatchLifecycleStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Combat ruleset changed; match expired",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combat turn deadline has passed",
        )
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None

    match = load_match(record)
    match.events = []
    # Fresh event stream for this turn: setup spawns below are iteration 0.
    match.current_iteration = 0
    append_dev_log(
        "combat-server.jsonl",
        "combat_resolve_request",
        {
            "match": _match_snapshot(match),
            "turn": payload.turn,
            "placements": [placement.model_dump(mode="json") for placement in payload.placements],
        },
    )
    if match.status == MatchLifecycleStatus.PLANNING:
        if payload.turn != match.turn:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Combat turn is no longer current",
            )
        # The hand is server-authoritative: every placement must reference a card
        # that is actually in the player's hand this turn.
        if not covers_hand(match, [p.card_id for p in payload.placements]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Placement uses a card that is not in hand",
            )
        placements = [
            (placement.card_id, Position(row=placement.row, col=placement.col))
            for placement in payload.placements
        ]
        # from_hand: each successful spawn consumes its card from the hand
        # (skipped placements keep theirs).
        match = apply_placements(
            match,
            placements,
            owner_id="player",
            side=PlayerSide.BOTTOM,
            from_hand=True,
        )
        match = apply_simple_bot_turn(match)
        resolved = resolve_turn(match)
        save_match(record, resolved)
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Combat match is {match.status}",
        )

    try:
        reward_claimed = user is not None and claim_combat_reward(
            db, match=resolved, user_id=user.id
        )
        audit(
            db,
            user.id if user else None,
            "combat.turn_resolved",
            {
                "match_id": resolved.id,
                "turn": payload.turn,
                "next_turn": resolved.turn,
                "status": resolved.status.value,
                "events_count": len(resolved.events),
            },
        )
        if resolved.result.status == "finished":
            audit(
                db,
                user.id if user else None,
                "combat.match_finished",
                {
                    "match_id": resolved.id,
                    "winner_id": resolved.result.winner_id,
                    "reward_coins": resolved.result.reward_coins,
                },
            )
        if reward_claimed:
            audit(
                db,
                user.id if user else None,
                "combat.reward_claimed",
                {
                    "match_id": resolved.id,
                    "coins": resolved.result.reward_coins,
                },
            )
            append_dev_log(
                "combat-server.jsonl",
                "combat_reward_claimed",
                {
                    "match_id": resolved.id,
                    "user_id": user.id,
                    "coins": resolved.result.reward_coins,
                },
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
    append_dev_log(
        "combat-server.jsonl",
        "combat_resolve_response",
        {"match": _match_snapshot(resolved)},
    )
    response = combat_response(resolved)
    await match_channel_manager.broadcast_match_update(resolved)
    return response


def _get_authorized_record(
    db: Session,
    match_id: str,
    refresh_token: str | None,
):
    record = get_combat_match_record(db, match_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat match not found",
        )

    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if record.owner_user_id is not None and (user is None or record.owner_user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Combat match belongs to another user",
        )
    return record


def _expire_record_if_stale(db: Session, record) -> None:
    if not expire_combat_match_if_stale(record, older_than=_stale_match_cutoff()):
        return
    audit(
        db,
        record.owner_user_id,
        "combat.match_expired",
        {"match_id": record.id},
    )
    db.commit()
    append_dev_log(
        "combat-server.jsonl",
        "combat_match_expired",
        {"match_id": record.id, "owner_user_id": record.owner_user_id},
    )


def _resolve_expired_record_if_needed(db: Session, record) -> MatchState | None:
    try:
        resolved = resolve_expired_planning_match(db, record)
        if resolved is None:
            return None
        # The ruleset gate also lands here: an old-version match comes back
        # EXPIRED (never resolved) and gets its own audit trail.
        expired_by_gate = resolved.status == MatchLifecycleStatus.EXPIRED
        audit(
            db,
            record.owner_user_id,
            "combat.match_expired_ruleset" if expired_by_gate else "combat.turn_deadline_resolved",
            {
                "match_id": resolved.id,
                "turn": resolved.turn,
                "status": resolved.status.value,
            },
        )
        db.commit()
    except StaleDataError:
        # Someone else resolved this match first; re-read their state and
        # behave as if no deadline resolve was needed here.
        db.rollback()
        db.refresh(record)
        return None
    append_dev_log(
        "combat-server.jsonl",
        "combat_match_expired_ruleset" if expired_by_gate else "combat_turn_deadline_resolved",
        {"match": _match_snapshot(resolved)},
    )
    return resolved


def _stale_match_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(hours=STALE_MATCH_TTL_HOURS)


def _match_snapshot(match: MatchState) -> dict:
    return {
        "id": match.id,
        "turn": match.turn,
        "players": [
            {
                "id": player.id,
                "side": player.side,
                "mana": player.mana,
                "hero_hp": player.hero.hp,
            }
            for player in match.players
        ],
        "units": [
            {
                "id": unit.id,
                "side": unit.side,
                "card_id": unit.card_id,
                "row": unit.position.row,
                "col": unit.position.col,
                "hp": unit.current_hp,
                "steps": unit.remaining_steps,
                "attacks": unit.remaining_attacks,
            }
            for unit in match.units
        ],
        "log_tail": [entry.message for entry in match.log[-10:]],
        "events_tail": [
            {
                "type": event.type,
                "message": event.message,
                "actor_id": event.actor_id,
                "target_id": event.target_id,
                "target_kind": event.target_kind,
                "damage": event.damage,
                "from_position": event.from_position.model_dump() if event.from_position else None,
                "to_position": event.to_position.model_dump() if event.to_position else None,
                "before_hp": event.before_hp,
                "after_hp": event.after_hp,
                "sequence": event.sequence,
                "micro_step": event.micro_step,
            }
            for event in match.events[-20:]
        ],
        "result": match.result.model_dump(mode="json"),
    }
