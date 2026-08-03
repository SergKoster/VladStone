from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlayerCard, PlayerProfile
from app.db.session import get_db
from app.domain.combat.engine.payload import v4_catalog_payload
from app.services.auth import get_user_by_refresh_token

router = APIRouter(prefix="/me", tags=["me"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]


@router.get("")
def get_me(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    profile = db.scalar(select(PlayerProfile).where(PlayerProfile.user_id == user.id))
    return {
        "id": user.id,
        "email": user.email,
        "nickname": profile.nickname if profile else "Player",
        "coins": profile.coins if profile else 0,
        "created_at": user.created_at.isoformat(),
    }


@router.get("/collection")
def get_collection(
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    return _collection_payload(db, user.id)


def _collection_payload(db: Session, user_id: int) -> dict:
    copies_by_id = dict(
        db.execute(
            select(PlayerCard.card_id, PlayerCard.copies).where(
                PlayerCard.user_id == user_id,
                PlayerCard.ascension == "default",
                PlayerCard.copies > 0,
            )
        ).all()
    )

    return {
        "cards": [
            {**card, "copies": copies_by_id[card["id"]]}
            for card in v4_catalog_payload()
            if card["id"] in copies_by_id
        ]
    }


def _require_user(db: Session, refresh_token: str | None):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = get_user_by_refresh_token(db, refresh_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
