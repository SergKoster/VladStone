"""Durable FIFO quick-match queue and atomic conversion into a PvP battle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import CombatMatchRecord, QuickMatchmakingEntry
from app.domain.combat.engine.battle import (
    BattleStateV4,
    activate_v4_pvp_battle,
    create_v4_pvp_lobby,
)
from app.domain.combat.models import MatchLifecycleStatus
from app.services.battle_admission import BattleAdmissionService
from app.services.profiles import display_handle_for_user

QUICK_WAITING = "waiting"
QUICK_MATCHED = "matched"
QUICK_HEARTBEAT_TTL = timedelta(seconds=45)
QUICK_MATCH_LEASE = timedelta(seconds=10)


def join_quick_matchmaking(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> dict:
    checked_at = _as_utc(now or datetime.now(UTC))
    _discard_stale_waiters(db, now=checked_at)

    current = BattleAdmissionService(db, now=checked_at).current_active_match(user_id=user_id)
    if current is not None:
        _remove_waiting_entry(db, user_id=user_id)
        return _matched_payload(current.id)

    entry = db.scalar(
        select(QuickMatchmakingEntry)
        .where(QuickMatchmakingEntry.user_id == user_id)
        .with_for_update()
    )
    if entry is not None and entry.status == QUICK_MATCHED:
        if _is_active_match(db, entry.matched_match_id):
            return _matched_payload(entry.matched_match_id)
        db.delete(entry)
        db.flush()
        entry = None

    if entry is None:
        entry = QuickMatchmakingEntry(
            user_id=user_id,
            status=QUICK_WAITING,
            joined_at=checked_at,
            heartbeat_at=checked_at,
        )
        db.add(entry)
    else:
        entry.heartbeat_at = checked_at
        entry.lease_expires_at = None
    db.flush()

    _match_first_pair(db, now=checked_at)
    db.flush()
    refreshed = db.get(QuickMatchmakingEntry, user_id)
    return (
        _entry_payload(refreshed) if refreshed is not None else {"status": "idle", "match_id": None}
    )


def get_quick_matchmaking_status(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> dict:
    checked_at = _as_utc(now or datetime.now(UTC))
    _discard_stale_waiters(db, now=checked_at)
    entry = db.get(QuickMatchmakingEntry, user_id)
    if entry is not None and entry.status == QUICK_WAITING:
        entry.heartbeat_at = checked_at
        entry.lease_expires_at = None
    _match_first_pair(db, now=checked_at)
    entry = db.get(QuickMatchmakingEntry, user_id)
    if entry is None:
        return {"status": "idle", "match_id": None}
    return _entry_payload(entry)


def cancel_quick_matchmaking(db: Session, *, user_id: int) -> dict:
    entry = db.scalar(
        select(QuickMatchmakingEntry)
        .where(QuickMatchmakingEntry.user_id == user_id)
        .with_for_update()
    )
    if entry is None:
        return {"status": "idle", "match_id": None}
    if entry.status == QUICK_MATCHED:
        return _entry_payload(entry)
    db.delete(entry)
    return {"status": "idle", "match_id": None}


def _match_first_pair(db: Session, *, now: datetime) -> str | None:
    # Read FIFO candidates first, then lock their accounts before taking queue
    # rows.  Every other admission path uses the same user → queue order, so a
    # simultaneous PvE/invite cannot deadlock with a matcher worker.
    candidate_ids = list(
        db.scalars(
            select(QuickMatchmakingEntry.user_id)
            .where(QuickMatchmakingEntry.status == QUICK_WAITING)
            .where(QuickMatchmakingEntry.heartbeat_at >= now - QUICK_HEARTBEAT_TTL)
            .where(
                or_(
                    QuickMatchmakingEntry.lease_expires_at.is_(None),
                    QuickMatchmakingEntry.lease_expires_at <= now,
                )
            )
            .order_by(QuickMatchmakingEntry.joined_at, QuickMatchmakingEntry.user_id)
            .limit(2)
        )
    )
    if len(candidate_ids) < 2:
        return None
    admission = BattleAdmissionService(db, now=now)
    admission.lock_users(candidate_ids)
    candidates = list(
        db.scalars(
            select(QuickMatchmakingEntry)
            .where(QuickMatchmakingEntry.user_id.in_(candidate_ids))
            .where(QuickMatchmakingEntry.status == QUICK_WAITING)
            .where(QuickMatchmakingEntry.heartbeat_at >= now - QUICK_HEARTBEAT_TTL)
            .where(
                or_(
                    QuickMatchmakingEntry.lease_expires_at.is_(None),
                    QuickMatchmakingEntry.lease_expires_at <= now,
                )
            )
            .order_by(QuickMatchmakingEntry.joined_at, QuickMatchmakingEntry.user_id)
            .with_for_update(skip_locked=True)
        )
    )
    if len(candidates) != 2:
        return None

    for entry in candidates:
        entry.lease_expires_at = now + QUICK_MATCH_LEASE
    db.flush()

    user_ids = [entry.user_id for entry in candidates]
    creator_user_id, opponent_user_id = user_ids
    admitted = admission.admit_new_match_for_users(
        user_ids=user_ids,
        owner_user_id=creator_user_id,
        preserve_queue_entries=True,
        build_state=lambda: _create_quick_match(
            db,
            creator_user_id=creator_user_id,
            opponent_user_id=opponent_user_id,
            now=now,
        ),
    )
    if not admitted.created:
        for entry in candidates:
            if entry.user_id == admitted.blocked_user_id:
                db.delete(entry)
            else:
                entry.lease_expires_at = None
        return None

    for entry in candidates:
        entry.status = QUICK_MATCHED
        entry.matched_match_id = admitted.record.id
        entry.lease_expires_at = None
    return admitted.record.id


def _create_quick_match(
    db: Session,
    *,
    creator_user_id: int,
    opponent_user_id: int,
    now: datetime,
) -> BattleStateV4:
    state = create_v4_pvp_lobby(
        match_id=f"quick_pvp_{uuid4().hex}",
        creator_user_id=creator_user_id,
        creator_display_name=display_handle_for_user(db, creator_user_id),
    )
    activate_v4_pvp_battle(
        state,
        opponent_user_id=opponent_user_id,
        opponent_display_name=display_handle_for_user(db, opponent_user_id),
        now=now,
    )
    return state


def _discard_stale_waiters(db: Session, *, now: datetime) -> None:
    db.execute(
        delete(QuickMatchmakingEntry).where(
            QuickMatchmakingEntry.status == QUICK_WAITING,
            QuickMatchmakingEntry.heartbeat_at < now - QUICK_HEARTBEAT_TTL,
        )
    )


def _remove_waiting_entry(db: Session, *, user_id: int) -> None:
    db.execute(
        delete(QuickMatchmakingEntry).where(
            QuickMatchmakingEntry.user_id == user_id,
            QuickMatchmakingEntry.status == QUICK_WAITING,
        )
    )


def _is_active_match(db: Session, match_id: str | None) -> bool:
    if match_id is None:
        return False
    return (
        db.scalar(
            select(CombatMatchRecord.id).where(
                CombatMatchRecord.id == match_id,
                CombatMatchRecord.status.in_(
                    (
                        MatchLifecycleStatus.WAITING_FOR_OPPONENT.value,
                        MatchLifecycleStatus.PLANNING.value,
                        MatchLifecycleStatus.RESOLVING.value,
                    )
                ),
            )
        )
        is not None
    )


def _entry_payload(entry: QuickMatchmakingEntry) -> dict:
    if entry.status == QUICK_MATCHED and entry.matched_match_id is not None:
        return _matched_payload(entry.matched_match_id)
    return {"status": QUICK_WAITING, "match_id": None}


def _matched_payload(match_id: str) -> dict:
    return {"status": QUICK_MATCHED, "match_id": match_id}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
