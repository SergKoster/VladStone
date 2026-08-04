"""Transactional public handles and viewer-safe profile payloads."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PlayerCard, PlayerProfile, ProfileHandle, User
from app.domain.combat.engine.catalog import collectible_v4_cards

HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,25}$")


class InvalidHandle(ValueError):
    pass


class HandleUnavailable(ValueError):
    pass


def handle_key(handle: str) -> str:
    if HANDLE_RE.fullmatch(handle) is None:
        raise InvalidHandle("Handle must contain 3-25 ASCII letters, digits or underscore")
    return handle.lower()


def current_handle(db: Session, user_id: int) -> ProfileHandle | None:
    return db.scalar(
        select(ProfileHandle).where(
            ProfileHandle.user_id == user_id,
            ProfileHandle.is_current.is_(True),
        )
    )


def display_handle_for_user(db: Session, user_id: int) -> str:
    current = current_handle(db, user_id)
    return current.display_handle if current is not None else "Игрок"


def set_profile_handle(db: Session, *, user_id: int, handle: str) -> ProfileHandle:
    key = handle_key(handle)
    profile = db.scalar(
        select(PlayerProfile).where(PlayerProfile.user_id == user_id).with_for_update()
    )
    if profile is None:
        profile = PlayerProfile(user_id=user_id)
        db.add(profile)
        db.flush()

    active = current_handle(db, user_id)
    if active is not None and active.handle_key == key:
        active.display_handle = handle
        profile.nickname = handle
        profile.onboarding_required = False
        return active

    if db.scalar(select(ProfileHandle.id).where(ProfileHandle.handle_key == key)) is not None:
        raise HandleUnavailable("Handle is already reserved")

    now = datetime.now(UTC)
    if active is not None:
        active.is_current = False
        active.retired_at = now
        db.flush()

    created = ProfileHandle(
        user_id=user_id,
        handle_key=key,
        display_handle=handle,
        is_current=True,
        created_at=now,
    )
    db.add(created)
    profile.nickname = handle
    profile.onboarding_required = False
    db.flush()
    return created


def private_profile_payload(db: Session, *, user: User) -> dict:
    profile = db.scalar(select(PlayerProfile).where(PlayerProfile.user_id == user.id))
    current = current_handle(db, user.id)
    return {
        "id": user.id,
        "email": user.email,
        "nickname": current.display_handle if current else "Player",
        "handle": current.display_handle if current else None,
        "onboarding_required": profile is None or profile.onboarding_required or current is None,
        "coins": profile.coins if profile else 0,
        "created_at": user.created_at.isoformat(),
    }


def public_profile_payload(db: Session, *, user_id: int) -> dict | None:
    user = db.get(User, user_id)
    profile = db.scalar(select(PlayerProfile).where(PlayerProfile.user_id == user_id))
    current = current_handle(db, user_id)
    if user is None or profile is None or current is None:
        return None
    owned = db.scalar(
        select(func.count(PlayerCard.id)).where(
            PlayerCard.user_id == user_id,
            PlayerCard.ascension == "default",
            PlayerCard.copies > 0,
        )
    )
    return {
        "handle": current.display_handle,
        "avatar_key": profile.avatar_key,
        "created_at": user.created_at.isoformat(),
        "collection": {"owned": owned or 0, "total": len(collectible_v4_cards())},
    }
