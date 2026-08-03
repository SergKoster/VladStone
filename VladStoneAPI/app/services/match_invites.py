"""Lifecycle of a one-use PvP invite and its waiting combat lobby."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MatchInviteRecord
from app.domain.combat.engine.battle import (
    BattleStateV4,
    activate_v4_pvp_battle,
    create_v4_pvp_lobby,
)
from app.domain.combat.models import MatchLifecycleStatus
from app.services.combat_matches import (
    add_combat_match_participant,
    create_combat_match_record,
    get_combat_match_participant,
    get_combat_match_record,
    load_v4_battle,
    save_v4_battle,
)

INVITE_TTL = timedelta(hours=24)
INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_CANCELLED = "cancelled"
INVITE_EXPIRED = "expired"


class InviteError(Exception):
    pass


class InviteNotFound(InviteError):
    pass


class InviteGone(InviteError):
    pass


class InviteConflict(InviteError):
    pass


class InviteForbidden(InviteError):
    pass


def create_match_invite(
    db: Session,
    *,
    creator_user_id: int,
    now: datetime | None = None,
) -> tuple[BattleStateV4, MatchInviteRecord, str]:
    created_at = _as_utc(now or datetime.now(UTC))
    match_id = f"pvp_{uuid4().hex}"
    state = create_v4_pvp_lobby(match_id=match_id, creator_user_id=creator_user_id)
    create_combat_match_record(db, match=state, owner_user_id=creator_user_id)

    token = secrets.token_urlsafe(32)
    invite = MatchInviteRecord(
        id=uuid4().hex,
        match_id=match_id,
        created_by_user_id=creator_user_id,
        token_digest=_token_digest(token),
        status=INVITE_PENDING,
        expires_at=created_at + INVITE_TTL,
    )
    db.add(invite)
    return state, invite, token


def join_match_invite(
    db: Session,
    *,
    token: str,
    user_id: int,
    now: datetime | None = None,
) -> BattleStateV4:
    """Accept an invite once; repeated request by its acceptor is idempotent."""
    accepted_at = _as_utc(now or datetime.now(UTC))
    invite = db.scalar(
        select(MatchInviteRecord)
        .where(MatchInviteRecord.token_digest == _token_digest(token))
        .with_for_update()
    )
    if invite is None:
        raise InviteNotFound
    record = get_combat_match_record(db, invite.match_id)
    if record is None:
        raise InviteNotFound

    if invite.status == INVITE_ACCEPTED:
        if invite.accepted_by_user_id == user_id:
            return load_v4_battle(record)
        raise InviteConflict("Invite has already been accepted")
    if invite.status in {INVITE_CANCELLED, INVITE_EXPIRED}:
        raise InviteGone
    if invite.status != INVITE_PENDING:
        raise InviteConflict("Invite is not pending")
    if _as_utc(invite.expires_at) <= accepted_at:
        _expire_invite_and_lobby(invite, record)
        raise InviteGone
    if invite.created_by_user_id == user_id:
        raise InviteConflict("Cannot accept your own invite")
    if get_combat_match_participant(db, match_id=record.id, user_id=user_id) is not None:
        raise InviteConflict("User already participates in this match")

    state = load_v4_battle(record)
    if state.status != MatchLifecycleStatus.WAITING_FOR_OPPONENT:
        raise InviteConflict("Match is no longer waiting")
    activate_v4_pvp_battle(state, opponent_user_id=user_id, now=accepted_at)
    opponent = next(player for player in state.players if player.user_id == user_id)
    add_combat_match_participant(
        db,
        match_id=record.id,
        user_id=user_id,
        player_id=opponent.id,
        team=opponent.team,
    )
    invite.status = INVITE_ACCEPTED
    invite.accepted_at = accepted_at
    invite.accepted_by_user_id = user_id
    save_v4_battle(record, state)
    return state


def get_match_invite(db: Session, *, match_id: str) -> MatchInviteRecord | None:
    return db.scalar(select(MatchInviteRecord).where(MatchInviteRecord.match_id == match_id))


def expire_invite_if_needed(
    db: Session,
    *,
    invite: MatchInviteRecord,
    now: datetime | None = None,
) -> bool:
    if (
        invite.status != INVITE_PENDING
        or _as_utc(invite.expires_at) > _as_utc(now or datetime.now(UTC))
    ):
        return False
    record = get_combat_match_record(db, invite.match_id)
    if record is not None:
        _expire_invite_and_lobby(invite, record)
    else:
        invite.status = INVITE_EXPIRED
    return True


def cancel_match_invite(db: Session, *, match_id: str, user_id: int) -> bool:
    invite = get_match_invite(db, match_id=match_id)
    if invite is None:
        raise InviteNotFound
    if invite.created_by_user_id != user_id:
        raise InviteForbidden
    if invite.status != INVITE_PENDING:
        return False
    record = get_combat_match_record(db, match_id=match_id)
    if record is not None:
        invite.status = INVITE_CANCELLED
        _expire_waiting_lobby(record)
    else:
        invite.status = INVITE_CANCELLED
    return True


def _expire_invite_and_lobby(invite: MatchInviteRecord, record) -> None:
    invite.status = INVITE_EXPIRED
    _expire_waiting_lobby(record)


def _expire_waiting_lobby(record) -> None:
    state = load_v4_battle(record)
    if state.status == MatchLifecycleStatus.WAITING_FOR_OPPONENT:
        state.status = MatchLifecycleStatus.EXPIRED
        state.planning_deadline = None
        state.result.status = "expired"
        save_v4_battle(record, state)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
