from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import AscendCardRequest
from app.db.models import CardDefinition, PlayerCard, PlayerProfile
from app.db.session import get_db
from app.domain.catalog import ASCENSION_LABELS
from app.domain.combat.cards import CARD_BY_ID
from app.domain.combat.models import Rarity
from app.services.auth import get_user_by_refresh_token

router = APIRouter(prefix="/me", tags=["me"])
DbSession = Annotated[Session, Depends(get_db)]
RefreshTokenCookie = Annotated[str | None, Cookie()]
ASCENSION_ORDER = ["default", "ascended", "ascended_plus"]


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


@router.post("/collection/{card_id}/ascend")
def ascend_card(
    card_id: str,
    payload: AscendCardRequest,
    db: DbSession,
    refresh_token: RefreshTokenCookie = None,
) -> dict:
    user = _require_user(db, refresh_token)
    if payload.ascension not in ASCENSION_ORDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ascension")
    current_index = ASCENSION_ORDER.index(payload.ascension)
    if current_index >= len(ASCENSION_ORDER) - 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Max ascension reached")

    current_card = db.scalar(
        select(PlayerCard).where(
            PlayerCard.user_id == user.id,
            PlayerCard.card_id == card_id,
            PlayerCard.ascension == payload.ascension,
        )
    )
    if current_card is None or current_card.copies < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough copies")

    next_ascension = ASCENSION_ORDER[current_index + 1]
    next_card = db.scalar(
        select(PlayerCard).where(
            PlayerCard.user_id == user.id,
            PlayerCard.card_id == card_id,
            PlayerCard.ascension == next_ascension,
        )
    )
    current_card.copies -= 2
    if next_card is None:
        db.add(
            PlayerCard(
                user_id=user.id,
                card_id=card_id,
                ascension=next_ascension,
                copies=1,
            )
        )
    else:
        next_card.copies += 1
    db.commit()
    return _collection_payload(db, user.id)


def _collection_payload(db: Session, user_id: int) -> dict:
    rows = db.execute(
        select(PlayerCard, CardDefinition)
        .join(CardDefinition, CardDefinition.id == PlayerCard.card_id)
        .where(PlayerCard.user_id == user_id, PlayerCard.copies > 0)
        .order_by(CardDefinition.cost)
    ).all()

    return {
        "cards": [
            {
                "id": definition.id,
                "name": definition.name,
                "cost": definition.cost,
                "rarity": _card_rarity(definition.id),
                "hp": definition.hp,
                "damage": definition.damage,
                "range": definition.attack_range,
                "steps": definition.move_steps,
                "attacks": definition.attacks,
                "copies": card.copies,
                "ascension": ASCENSION_LABELS.get(card.ascension, card.ascension),
            }
            for card, definition in rows
        ]
    }


def _card_rarity(card_id: str) -> str:
    # Rarity is static card metadata; the domain catalog is its source of truth.
    card = CARD_BY_ID.get(card_id)
    return (card.rarity if card else Rarity.COMMON).value


def _require_user(db: Session, refresh_token: str | None):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = get_user_by_refresh_token(db, refresh_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
