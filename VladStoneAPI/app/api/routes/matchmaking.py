"""Authenticated FIFO quick-match endpoints."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db.session import get_db
from app.services.accounts import audit
from app.services.auth import get_user_by_refresh_token
from app.services.quick_matchmaking import (
    cancel_quick_matchmaking,
    get_quick_matchmaking_status,
    join_quick_matchmaking,
)

router = APIRouter(prefix="/matchmaking", tags=["matchmaking"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]


@router.post("/quick")
def join_quick(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    payload = join_quick_matchmaking(db, user_id=user.id)
    audit(db, user.id, "matchmaking.quick_joined", {"status": payload["status"]})
    _commit_or_conflict(db)
    return payload


@router.get("/quick")
def get_quick(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    payload = get_quick_matchmaking_status(db, user_id=user.id)
    _commit_or_conflict(db)
    return payload


@router.delete("/quick")
def cancel_quick(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    payload = cancel_quick_matchmaking(db, user_id=user.id)
    if payload["status"] == "idle":
        audit(db, user.id, "matchmaking.quick_cancelled", {})
    _commit_or_conflict(db)
    return payload


def _require_user(db: Session, refresh_token: str | None):
    user = get_user_by_refresh_token(db, refresh_token) if refresh_token else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quick matchmaking changed concurrently; retry status",
        ) from None
