from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IdentityProvider(StrEnum):
    EMAIL = "email"
    GOOGLE = "google"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    profile: Mapped["PlayerProfile"] = relationship(back_populates="user", uselist=False)


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_auth_identities_provider_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(320), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class EmailLoginCode(Base):
    __tablename__ = "email_login_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[str] = mapped_column(String(2048), default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(32), default="Player")
    avatar_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    coins: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="profile")


class CardDefinition(Base):
    __tablename__ = "card_definitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    cost: Mapped[int] = mapped_column(Integer)
    hp: Mapped[int] = mapped_column(Integer)
    damage: Mapped[int] = mapped_column(Integer)
    attack_range: Mapped[int] = mapped_column(Integer)
    move_steps: Mapped[int] = mapped_column(Integer)
    attacks: Mapped[int] = mapped_column(Integer)
    action_priority: Mapped[str] = mapped_column(String(32), default="attack_first")


class PlayerCard(Base):
    __tablename__ = "player_cards"
    __table_args__ = (
        UniqueConstraint("user_id", "card_id", "ascension", name="uq_player_cards_user_card_asc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("card_definitions.id"), index=True)
    ascension: Mapped[str] = mapped_column(String(32), default="default")
    copies: Mapped[int] = mapped_column(Integer, default=0)


class CombatRewardClaim(Base):
    __tablename__ = "combat_reward_claims"
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_combat_reward_claims_user_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    match_id: Mapped[str] = mapped_column(String(64), index=True)
    coins: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class CombatMatchRecord(Base):
    __tablename__ = "combat_matches"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    # Optimistic lock: every UPDATE goes out as "... WHERE version = <loaded>",
    # so of two concurrent resolvers (route vs timer worker) only the first
    # write lands; the loser gets StaleDataError instead of silently
    # overwriting the state (ARCHITECTURE §8.6).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    state_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    winner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __mapper_args__ = {"version_id_col": version}


class CombatMatchParticipant(Base):
    """Indexed account ↔ seat membership for authorization and reconnect."""

    __tablename__ = "combat_match_participants"
    __table_args__ = (
        UniqueConstraint("match_id", "user_id", name="uq_match_participants_match_user"),
        UniqueConstraint("match_id", "player_id", name="uq_match_participants_match_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("combat_matches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    player_id: Mapped[str] = mapped_column(String(64))
    team: Mapped[int] = mapped_column(Integer)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class MatchInviteRecord(Base):
    """Single-use invitation capability. Only its SHA-256 digest is persisted."""

    __tablename__ = "match_invites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("combat_matches.id"),
        unique=True,
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
