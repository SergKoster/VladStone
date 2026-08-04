"""Authenticated PvP lobby and invitation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.schemas import JoinMatchInviteRequest
from app.db.session import get_db
from app.domain.combat.engine.payload import v4_combat_response
from app.realtime.match_channels import match_channel_manager
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.combat_matches import (
    get_combat_match_participant,
    get_combat_match_record,
    load_v4_battle,
)
from app.services.match_invites import (
    InviteConflict,
    InviteForbidden,
    InviteGone,
    InviteNotFound,
    cancel_match_invite,
    create_match_invite,
    expire_invite_if_needed,
    get_match_invite,
    join_match_invite,
)
from app.services.profiles import display_handle_for_user

router = APIRouter(prefix="/matches", tags=["matches"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]


@router.post("/invite", status_code=status.HTTP_201_CREATED)
def create_invite(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    state, invite, token = create_match_invite(
        db,
        creator_user_id=user.id,
        creator_display_name=display_handle_for_user(db, user.id),
    )
    audit(db, user.id, "match.invite_created", {"match_id": state.id})
    db.commit()
    return {
        "match": v4_combat_response(state, viewer_id="p1")["match"],
        "invite": {
            "share_path": f"/#invite/{token}",
            "expires_at": invite.expires_at.isoformat(),
            "status": invite.status,
        },
    }


@router.post("/join")
async def join_invite(
    payload: JoinMatchInviteRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    try:
        state = join_match_invite(
            db,
            token=payload.token,
            user_id=user.id,
            display_name=display_handle_for_user(db, user.id),
        )
    except InviteNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        ) from None
    except InviteGone:
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired") from None
    except InviteConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None

    audit(db, user.id, "match.invite_joined", {"match_id": state.id})
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        # The invite row is locked in PostgreSQL; this is an additional guard
        # for an optimistic version conflict or a weaker local database.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invite was accepted concurrently",
        ) from None
    await match_channel_manager.broadcast_match_update(state)
    viewer_id = next(player.id for player in state.players if player.user_id == user.id)
    return v4_combat_response(state, viewer_id=viewer_id)


@router.get("/{match_id}/lobby")
def get_lobby(
    match_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    participant = get_combat_match_participant(db, match_id=match_id, user_id=user.id)
    if participant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a match participant")
    record = get_combat_match_record(db, match_id)
    invite = get_match_invite(db, match_id=match_id)
    if record is None or invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if expire_invite_if_needed(db, invite=invite):
        audit(db, invite.created_by_user_id, "match.invite_expired", {"match_id": match_id})
        db.commit()
    state = load_v4_battle(record)
    return {
        "match": v4_combat_response(state, viewer_id=participant.player_id)["match"],
        "invite": {"status": invite.status, "expires_at": invite.expires_at.isoformat()},
    }


@router.delete("/{match_id}/invite", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(
    match_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> Response:
    user = _require_user(db, refresh_token)
    try:
        changed = cancel_match_invite(db, match_id=match_id, user_id=user.id)
    except InviteNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        ) from None
    except InviteForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only creator can cancel invite",
        ) from None
    if changed:
        audit(db, user.id, "match.invite_cancelled", {"match_id": match_id})
        db.commit()
        await match_channel_manager.broadcast_expired(match_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _require_user(db: Session, refresh_token: str | None):
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
