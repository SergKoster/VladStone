"""Authenticated friends, blocks and direct friend battle challenges."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.schemas import ChallengeCreateRequest, FriendRequestCreate
from app.db.session import get_db
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.social import (
    SocialError,
    SocialForbidden,
    SocialNotFound,
    accept_challenge,
    accept_friend,
    block_user,
    cancel_or_decline_challenge,
    cancel_or_decline_friend,
    challenge_payload,
    create_challenge,
    find_user_by_handle,
    remove_friend,
    request_friend,
    social_snapshot,
    unblock_user,
)

router = APIRouter(prefix="/social", tags=["social"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]


@router.get("")
def get_social(db: DbSession, refresh_token: RefreshTokenCookie = None) -> dict:
    user = _require_user(db, refresh_token)
    payload = social_snapshot(db, user_id=user.id)
    db.commit()
    return payload


@router.get("/search")
def search_handle(handle: str, db: DbSession, refresh_token: RefreshTokenCookie = None) -> dict:
    user = _require_user(db, refresh_token)
    found = find_user_by_handle(db, handle=handle)
    if found is None or found["user_id"] == user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return found


@router.post("/friend-requests", status_code=status.HTTP_201_CREATED)
def create_friend_request(
    payload: FriendRequestCreate,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    found = find_user_by_handle(db, handle=payload.handle)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    try:
        relationship_status = request_friend(db, user_id=user.id, target_user_id=found["user_id"])
        audit(
            db,
            user.id,
            f"social.friend_{relationship_status}",
            {"target_user_id": found["user_id"]},
        )
        _commit(db)
    except SocialError as error:
        _raise_social(error)
    return {"status": relationship_status, "user": found}


@router.post("/friend-requests/{user_id}/accept")
def accept_friend_request(
    user_id: int,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    try:
        accept_friend(db, user_id=user.id, requester_user_id=user_id)
        audit(db, user.id, "social.friend_accepted", {"requester_user_id": user_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)
    return {"ok": True}


@router.delete("/friend-requests/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend_request(
    user_id: int,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> None:
    user = _require_user(db, refresh_token)
    try:
        cancel_or_decline_friend(db, user_id=user.id, other_user_id=user_id)
        audit(db, user.id, "social.friend_request_removed", {"other_user_id": user_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)


@router.delete("/friends/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_friend(user_id: int, db: DbSession, refresh_token: RefreshTokenCookie = None) -> None:
    user = _require_user(db, refresh_token)
    try:
        remove_friend(db, user_id=user.id, other_user_id=user_id)
        audit(db, user.id, "social.friend_removed", {"other_user_id": user_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)


@router.post("/blocks/{user_id}")
def create_block(user_id: int, db: DbSession, refresh_token: RefreshTokenCookie = None) -> dict:
    user = _require_user(db, refresh_token)
    try:
        block_user(db, user_id=user.id, target_user_id=user_id)
        audit(db, user.id, "social.user_blocked", {"target_user_id": user_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)
    return {"ok": True}


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(user_id: int, db: DbSession, refresh_token: RefreshTokenCookie = None) -> None:
    user = _require_user(db, refresh_token)
    try:
        unblock_user(db, user_id=user.id, target_user_id=user_id)
        audit(db, user.id, "social.user_unblocked", {"target_user_id": user_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)


@router.post("/challenges", status_code=status.HTTP_201_CREATED)
def send_challenge(
    payload: ChallengeCreateRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    try:
        challenge = create_challenge(
            db,
            challenger_user_id=user.id,
            challenged_user_id=payload.user_id,
        )
        audit(db, user.id, "social.challenge_created", {"challenge_id": challenge.id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)
    return challenge_payload(db, challenge=challenge, viewer_user_id=user.id)


@router.post("/challenges/{challenge_id}/accept")
def accept_friend_challenge(
    challenge_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    try:
        challenge = accept_challenge(db, challenge_id=challenge_id, user_id=user.id)
        audit(db, user.id, "social.challenge_accepted", {"challenge_id": challenge.id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)
    return {"match_id": challenge.match_id}


@router.delete("/challenges/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_challenge(
    challenge_id: str,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> None:
    user = _require_user(db, refresh_token)
    try:
        cancel_or_decline_challenge(db, challenge_id=challenge_id, user_id=user.id)
        audit(db, user.id, "social.challenge_removed", {"challenge_id": challenge_id})
        _commit(db)
    except SocialError as error:
        _raise_social(error)


def _require_user(db: Session, refresh_token: str | None):
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def _commit(db: Session) -> None:
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Social action changed; retry",
        ) from None


def _raise_social(error: SocialError) -> None:
    if isinstance(error, SocialNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, SocialForbidden):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=code, detail=str(error)) from None
