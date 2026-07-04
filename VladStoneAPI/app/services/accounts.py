from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    AuthIdentity,
    CardDefinition,
    IdentityProvider,
    PlayerCard,
    PlayerProfile,
    User,
)
from app.domain.catalog import STARTER_CARD_COPIES
from app.domain.combat.rules import STARTER_CARDS


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_seed_cards(db: Session) -> None:
    for card in STARTER_CARDS:
        existing = db.get(CardDefinition, card.id)
        if existing is not None:
            continue
        db.add(
            CardDefinition(
                id=card.id,
                name=card.name,
                cost=card.cost,
                hp=card.stats.hp,
                damage=card.stats.damage,
                attack_range=card.stats.attack_range,
                move_steps=card.stats.move_steps,
                attacks=card.stats.attacks,
                action_priority=card.stats.action_priority.value,
            )
        )


def get_or_create_user_for_identity(
    db: Session,
    *,
    email: str,
    provider: IdentityProvider,
    provider_user_id: str,
) -> User:
    normalized_email = normalize_email(email)
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider.value,
            AuthIdentity.provider_user_id == provider_user_id,
        )
    )
    if identity is not None:
        user = db.get(User, identity.user_id)
        # Idempotent top-up: existing accounts receive any starter cards that
        # were added to the catalog after they signed up.
        grant_starter_collection(db, user.id)
        return user

    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(email=normalized_email)
        db.add(user)
        db.flush()
        db.add(PlayerProfile(user_id=user.id))
        audit(db, user.id, "user.created", {"provider": provider.value})
    grant_starter_collection(db, user.id)

    db.add(
        AuthIdentity(
            user_id=user.id,
            provider=provider.value,
            provider_user_id=provider_user_id,
        )
    )
    audit(db, user.id, "auth.identity_linked", {"provider": provider.value})
    return user


def grant_starter_collection(db: Session, user_id: int) -> None:
    ensure_seed_cards(db)
    for card_id, copies in STARTER_CARD_COPIES.items():
        player_card = db.scalar(
            select(PlayerCard).where(
                PlayerCard.user_id == user_id,
                PlayerCard.card_id == card_id,
                PlayerCard.ascension == "default",
            )
        )
        if player_card is None:
            db.add(
                PlayerCard(
                    user_id=user_id,
                    card_id=card_id,
                    ascension="default",
                    copies=copies,
                )
            )


def audit(db: Session, user_id: int | None, action: str, metadata: dict) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            created_at=datetime.now(UTC),
        )
    )

