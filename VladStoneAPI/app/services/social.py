"""Transactional friendships, blocks and direct friend challenges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import BattleChallenge, FriendRelationship, ProfileHandle, User, UserBlock
from app.domain.combat.engine.battle import activate_v4_pvp_battle, create_v4_pvp_lobby
from app.services.battle_admission import BattleAdmissionService
from app.services.profiles import display_handle_for_user, handle_key

FRIEND_PENDING = "pending"
FRIEND_ACCEPTED = "accepted"
CHALLENGE_PENDING = "pending"
CHALLENGE_ACCEPTED = "accepted"
CHALLENGE_DECLINED = "declined"
CHALLENGE_CANCELLED = "cancelled"
CHALLENGE_EXPIRED = "expired"
CHALLENGE_TTL = timedelta(hours=24)


class SocialError(Exception):
    pass


class SocialNotFound(SocialError):
    pass


class SocialConflict(SocialError):
    pass


class SocialForbidden(SocialError):
    pass


def find_user_by_handle(db: Session, *, handle: str) -> dict | None:
    try:
        key = handle_key(handle)
    except ValueError:
        return None
    profile_handle = db.scalar(
        select(ProfileHandle).where(
            ProfileHandle.handle_key == key,
            ProfileHandle.is_current.is_(True),
        )
    )
    if profile_handle is None:
        return None
    return {"user_id": profile_handle.user_id, "handle": profile_handle.display_handle}


def social_snapshot(db: Session, *, user_id: int, now: datetime | None = None) -> dict:
    checked_at = _as_utc(now or datetime.now(UTC))
    _expire_challenges(db, user_id=user_id, now=checked_at)
    relationships = list(
        db.scalars(
            select(FriendRelationship).where(
                or_(
                    FriendRelationship.user_low_id == user_id,
                    FriendRelationship.user_high_id == user_id,
                )
            )
        )
    )
    friends: list[dict] = []
    incoming_requests: list[dict] = []
    outgoing_requests: list[dict] = []
    for relationship in relationships:
        other_id = _other_id(relationship, user_id)
        person = _person_payload(db, other_id)
        if relationship.status == FRIEND_ACCEPTED:
            friends.append(person)
        elif relationship.requested_by_user_id == user_id:
            outgoing_requests.append(person)
        else:
            incoming_requests.append(person)

    blocked = [
        _person_payload(db, blocked_id)
        for blocked_id in db.scalars(
            select(UserBlock.blocked_user_id).where(UserBlock.blocker_user_id == user_id)
        )
    ]
    challenges = list(
        db.scalars(
            select(BattleChallenge).where(
                BattleChallenge.status == CHALLENGE_PENDING,
                or_(
                    BattleChallenge.challenger_user_id == user_id,
                    BattleChallenge.challenged_user_id == user_id,
                ),
            )
        )
    )
    incoming_challenges = [
        _challenge_payload(db, challenge, other_user_id=challenge.challenger_user_id)
        for challenge in challenges
        if challenge.challenged_user_id == user_id
    ]
    outgoing_challenges = [
        _challenge_payload(db, challenge, other_user_id=challenge.challenged_user_id)
        for challenge in challenges
        if challenge.challenger_user_id == user_id
    ]
    return {
        "friends": sorted(friends, key=lambda person: person["handle"].lower()),
        "incoming_requests": sorted(incoming_requests, key=lambda person: person["handle"].lower()),
        "outgoing_requests": sorted(outgoing_requests, key=lambda person: person["handle"].lower()),
        "blocked": sorted(blocked, key=lambda person: person["handle"].lower()),
        "incoming_challenges": incoming_challenges,
        "outgoing_challenges": outgoing_challenges,
    }


def request_friend(db: Session, *, user_id: int, target_user_id: int) -> str:
    _validate_other_user(db, user_id=user_id, target_user_id=target_user_id)
    _lock_pair(db, user_id, target_user_id)
    _require_not_blocked(db, user_id, target_user_id)
    relationship = _locked_relationship(db, user_id, target_user_id)
    if relationship is None:
        low_id, high_id = _pair(user_id, target_user_id)
        db.add(
            FriendRelationship(
                user_low_id=low_id,
                user_high_id=high_id,
                status=FRIEND_PENDING,
                requested_by_user_id=user_id,
            )
        )
        return FRIEND_PENDING
    if relationship.status == FRIEND_ACCEPTED:
        return FRIEND_ACCEPTED
    if relationship.requested_by_user_id == user_id:
        return FRIEND_PENDING
    relationship.status = FRIEND_ACCEPTED
    return FRIEND_ACCEPTED


def accept_friend(db: Session, *, user_id: int, requester_user_id: int) -> None:
    _validate_other_user(db, user_id=user_id, target_user_id=requester_user_id)
    _lock_pair(db, user_id, requester_user_id)
    _require_not_blocked(db, user_id, requester_user_id)
    relationship = _locked_relationship(db, user_id, requester_user_id)
    if relationship is None or relationship.status != FRIEND_PENDING:
        raise SocialNotFound("Friend request not found")
    if relationship.requested_by_user_id == user_id:
        raise SocialConflict("Cannot accept your own friend request")
    relationship.status = FRIEND_ACCEPTED


def cancel_or_decline_friend(db: Session, *, user_id: int, other_user_id: int) -> None:
    _lock_pair(db, user_id, other_user_id)
    relationship = _locked_relationship(db, user_id, other_user_id)
    if relationship is None or relationship.status != FRIEND_PENDING:
        raise SocialNotFound("Friend request not found")
    db.delete(relationship)


def remove_friend(db: Session, *, user_id: int, other_user_id: int) -> None:
    _lock_pair(db, user_id, other_user_id)
    relationship = _locked_relationship(db, user_id, other_user_id)
    if relationship is None or relationship.status != FRIEND_ACCEPTED:
        raise SocialNotFound("Friendship not found")
    db.delete(relationship)


def block_user(db: Session, *, user_id: int, target_user_id: int) -> None:
    _validate_other_user(db, user_id=user_id, target_user_id=target_user_id)
    _lock_pair(db, user_id, target_user_id)
    block = db.scalar(
        select(UserBlock)
        .where(
            UserBlock.blocker_user_id == user_id,
            UserBlock.blocked_user_id == target_user_id,
        )
        .with_for_update()
    )
    if block is None:
        db.add(UserBlock(blocker_user_id=user_id, blocked_user_id=target_user_id))
    relationship = _locked_relationship(db, user_id, target_user_id)
    if relationship is not None:
        db.delete(relationship)
    db.execute(
        update(BattleChallenge)
        .where(
            BattleChallenge.status == CHALLENGE_PENDING,
            _challenge_pair_condition(user_id, target_user_id),
        )
        .values(status=CHALLENGE_CANCELLED)
    )


def unblock_user(db: Session, *, user_id: int, target_user_id: int) -> None:
    block = db.scalar(
        select(UserBlock)
        .where(
            UserBlock.blocker_user_id == user_id,
            UserBlock.blocked_user_id == target_user_id,
        )
        .with_for_update()
    )
    if block is None:
        raise SocialNotFound("Block not found")
    db.delete(block)


def create_challenge(
    db: Session, *, challenger_user_id: int, challenged_user_id: int, now: datetime | None = None
) -> BattleChallenge:
    created_at = _as_utc(now or datetime.now(UTC))
    _validate_other_user(db, user_id=challenger_user_id, target_user_id=challenged_user_id)
    _lock_pair(db, challenger_user_id, challenged_user_id)
    _require_not_blocked(db, challenger_user_id, challenged_user_id)
    relationship = _locked_relationship(db, challenger_user_id, challenged_user_id)
    if relationship is None or relationship.status != FRIEND_ACCEPTED:
        raise SocialForbidden("Only friends can send a battle challenge")
    existing = db.scalar(
        select(BattleChallenge)
        .where(
            _challenge_pair_condition(challenger_user_id, challenged_user_id),
            BattleChallenge.status == CHALLENGE_PENDING,
        )
        .with_for_update()
    )
    if existing is not None and _as_utc(existing.expires_at) > created_at:
        return existing
    if existing is not None:
        existing.status = CHALLENGE_EXPIRED
    challenge = BattleChallenge(
        id=f"challenge_{uuid4().hex}",
        challenger_user_id=challenger_user_id,
        challenged_user_id=challenged_user_id,
        status=CHALLENGE_PENDING,
        expires_at=created_at + CHALLENGE_TTL,
    )
    db.add(challenge)
    return challenge


def accept_challenge(
    db: Session, *, challenge_id: str, user_id: int, now: datetime | None = None
) -> BattleChallenge:
    accepted_at = _as_utc(now or datetime.now(UTC))
    peek = db.get(BattleChallenge, challenge_id)
    if peek is None:
        raise SocialNotFound("Challenge not found")
    _lock_pair(db, peek.challenger_user_id, peek.challenged_user_id)
    challenge = db.scalar(
        select(BattleChallenge).where(BattleChallenge.id == challenge_id).with_for_update()
    )
    if challenge is None:
        raise SocialNotFound("Challenge not found")
    if challenge.status == CHALLENGE_ACCEPTED and challenge.challenged_user_id == user_id:
        return challenge
    if challenge.challenged_user_id != user_id:
        raise SocialForbidden("Only challenged player can accept")
    if challenge.status != CHALLENGE_PENDING:
        raise SocialConflict("Challenge is no longer pending")
    if _as_utc(challenge.expires_at) <= accepted_at:
        challenge.status = CHALLENGE_EXPIRED
        raise SocialConflict("Challenge has expired")
    _require_not_blocked(db, challenge.challenger_user_id, challenge.challenged_user_id)
    relationship = _locked_relationship(
        db,
        challenge.challenger_user_id,
        challenge.challenged_user_id,
    )
    if relationship is None or relationship.status != FRIEND_ACCEPTED:
        challenge.status = CHALLENGE_CANCELLED
        raise SocialForbidden("Friendship is no longer active")
    admitted = BattleAdmissionService(db, now=accepted_at).admit_new_match_for_users(
        user_ids=[challenge.challenger_user_id, challenge.challenged_user_id],
        owner_user_id=challenge.challenger_user_id,
        build_state=lambda: _new_challenge_battle(db, challenge=challenge, now=accepted_at),
    )
    if not admitted.created:
        raise SocialConflict("A participant already has an active match")
    challenge.status = CHALLENGE_ACCEPTED
    challenge.match_id = admitted.record.id
    return challenge


def cancel_or_decline_challenge(db: Session, *, challenge_id: str, user_id: int) -> None:
    challenge = db.get(BattleChallenge, challenge_id)
    if challenge is None:
        raise SocialNotFound("Challenge not found")
    _lock_pair(db, challenge.challenger_user_id, challenge.challenged_user_id)
    challenge = db.scalar(
        select(BattleChallenge).where(BattleChallenge.id == challenge_id).with_for_update()
    )
    if challenge is None:
        raise SocialNotFound("Challenge not found")
    if challenge.status != CHALLENGE_PENDING:
        raise SocialConflict("Challenge is no longer pending")
    if user_id == challenge.challenger_user_id:
        challenge.status = CHALLENGE_CANCELLED
    elif user_id == challenge.challenged_user_id:
        challenge.status = CHALLENGE_DECLINED
    else:
        raise SocialForbidden("Not a challenge participant")


def challenge_payload(db: Session, *, challenge: BattleChallenge, viewer_user_id: int) -> dict:
    return _challenge_payload(
        db,
        challenge,
        other_user_id=(
            challenge.challenged_user_id
            if challenge.challenger_user_id == viewer_user_id
            else challenge.challenger_user_id
        ),
    )


def _new_challenge_battle(db: Session, *, challenge: BattleChallenge, now: datetime):
    state = create_v4_pvp_lobby(
        match_id=f"friend_pvp_{uuid4().hex}",
        creator_user_id=challenge.challenger_user_id,
        creator_display_name=display_handle_for_user(db, challenge.challenger_user_id),
    )
    activate_v4_pvp_battle(
        state,
        opponent_user_id=challenge.challenged_user_id,
        opponent_display_name=display_handle_for_user(db, challenge.challenged_user_id),
        now=now,
    )
    return state


def _expire_challenges(db: Session, *, user_id: int, now: datetime) -> None:
    for challenge in db.scalars(
        select(BattleChallenge)
        .where(
            BattleChallenge.status == CHALLENGE_PENDING,
            BattleChallenge.expires_at <= now,
            or_(
                BattleChallenge.challenger_user_id == user_id,
                BattleChallenge.challenged_user_id == user_id,
            ),
        )
        .with_for_update()
    ):
        challenge.status = CHALLENGE_EXPIRED


def _challenge_payload(db: Session, challenge: BattleChallenge, *, other_user_id: int) -> dict:
    return {
        "id": challenge.id,
        "user": _person_payload(db, other_user_id),
        "expires_at": challenge.expires_at.isoformat(),
    }


def _person_payload(db: Session, user_id: int) -> dict:
    return {"user_id": user_id, "handle": display_handle_for_user(db, user_id)}


def _validate_other_user(db: Session, *, user_id: int, target_user_id: int) -> None:
    if user_id == target_user_id:
        raise SocialConflict("Cannot target yourself")
    if db.get(User, target_user_id) is None:
        raise SocialNotFound("User not found")


def _lock_pair(db: Session, first_id: int, second_id: int) -> None:
    BattleAdmissionService(db).lock_users([first_id, second_id])


def _require_not_blocked(db: Session, first_id: int, second_id: int) -> None:
    blocked = db.scalar(
        select(UserBlock.blocker_user_id).where(
            or_(
                and_(UserBlock.blocker_user_id == first_id, UserBlock.blocked_user_id == second_id),
                and_(UserBlock.blocker_user_id == second_id, UserBlock.blocked_user_id == first_id),
            )
        )
    )
    if blocked is not None:
        raise SocialForbidden("Social action is blocked")


def _locked_relationship(db: Session, first_id: int, second_id: int) -> FriendRelationship | None:
    low_id, high_id = _pair(first_id, second_id)
    return db.scalar(
        select(FriendRelationship)
        .where(
            FriendRelationship.user_low_id == low_id,
            FriendRelationship.user_high_id == high_id,
        )
        .with_for_update()
    )


def _challenge_pair_condition(first_id: int, second_id: int):
    return or_(
        and_(
            BattleChallenge.challenger_user_id == first_id,
            BattleChallenge.challenged_user_id == second_id,
        ),
        and_(
            BattleChallenge.challenger_user_id == second_id,
            BattleChallenge.challenged_user_id == first_id,
        ),
    )


def _other_id(relationship: FriendRelationship, user_id: int) -> int:
    return (
        relationship.user_high_id
        if relationship.user_low_id == user_id
        else relationship.user_low_id
    )


def _pair(first_id: int, second_id: int) -> tuple[int, int]:
    return (first_id, second_id) if first_id < second_id else (second_id, first_id)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
