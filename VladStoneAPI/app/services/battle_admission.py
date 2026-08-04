"""Transactional single-active-match admission for every authenticated account."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import CombatActiveSlot, CombatMatchRecord, User
from app.domain.combat.engine.battle import BattleStateV4
from app.services.combat_matches import (
    ACTIVE_MATCH_STATUSES,
    create_combat_match_record,
    expire_combat_match_if_outdated,
    expire_combat_match_if_stale,
)

ACTIVE_SLOT_STALE_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class AdmissionResult:
    record: CombatMatchRecord
    state: BattleStateV4 | None
    created: bool


class ActiveMatchExists(Exception):
    def __init__(self, record: CombatMatchRecord):
        self.record = record
        super().__init__(f"Account already has active match {record.id}")


class BattleAdmissionService:
    """Owns slot locking for PvE, invite lobbies and invite acceptance.

    A unique primary key on ``combat_active_slots.user_id`` is the final race
    guard.  The nested transaction makes a PostgreSQL unique-violation
    recoverable, after which the competing request reads the winner's slot.
    """

    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db = db
        self.now = _as_utc(now or datetime.now(UTC))

    def admit_new_match(
        self,
        *,
        user_id: int,
        owner_user_id: int,
        build_state: Callable[[], BattleStateV4],
    ) -> AdmissionResult:
        try:
            slot = self._reserve_available_slot(user_id)
        except ActiveMatchExists as existing:
            return AdmissionResult(record=existing.record, state=None, created=False)

        state = build_state()
        record = create_combat_match_record(
            self.db,
            match=state,
            owner_user_id=owner_user_id,
        )
        slot.match_id = record.id
        return AdmissionResult(record=record, state=state, created=True)

    def current_active_match(self, *, user_id: int) -> CombatMatchRecord | None:
        self._lock_users([user_id])
        return self._current_record(user_id)

    def reserve_participant_slot(self, *, user_id: int, match_id: str) -> CombatActiveSlot:
        """Reserve a joining account before it becomes a match participant."""
        current = self._current_record(user_id)
        if current is not None:
            if current.id == match_id:
                slot = self._locked_slot(user_id)
                assert slot is not None
                return slot
            raise ActiveMatchExists(current)
        slot = self._reserve_available_slot(user_id)
        slot.match_id = match_id
        return slot

    def _reserve_available_slot(self, user_id: int) -> CombatActiveSlot:
        self._lock_users([user_id])
        current = self._current_record(user_id)
        if current is not None:
            raise ActiveMatchExists(current)

        slot = CombatActiveSlot(user_id=user_id)
        try:
            with self.db.begin_nested():
                self.db.add(slot)
                self.db.flush()
        except IntegrityError:
            # A simultaneous request won the unique key.  Its transaction has
            # committed before the constraint error is observable, so a locked
            # re-read sees the canonical active match.
            current = self._current_record(user_id)
            if current is not None:
                raise ActiveMatchExists(current) from None
            # A previous crashed/terminal transaction can leave only a stale
            # slot; remove it and claim the now-free key in this transaction.
            stale = self._locked_slot(user_id)
            if stale is not None:
                self.db.delete(stale)
                self.db.flush()
            with self.db.begin_nested():
                self.db.add(slot)
                self.db.flush()
        return slot

    def _current_record(self, user_id: int) -> CombatMatchRecord | None:
        slot = self._locked_slot(user_id)
        if slot is None:
            return None
        if slot.match_id is None:
            # This cannot survive a completed admission transaction.  Treat it
            # as recoverable debris rather than blocking a player forever.
            self.db.delete(slot)
            self.db.flush()
            return None
        record = self.db.get(CombatMatchRecord, slot.match_id, with_for_update=True)
        if record is None:
            self.db.delete(slot)
            self.db.flush()
            return None
        if expire_combat_match_if_stale(
            record,
            older_than=self.now - ACTIVE_SLOT_STALE_TTL,
        ) or expire_combat_match_if_outdated(record):
            # The expiration helper also releases every slot for this match.
            return None
        if record.status not in ACTIVE_MATCH_STATUSES:
            self.db.delete(slot)
            self.db.flush()
            return None
        return record

    def _locked_slot(self, user_id: int) -> CombatActiveSlot | None:
        return self.db.scalar(
            select(CombatActiveSlot).where(CombatActiveSlot.user_id == user_id).with_for_update()
        )

    def _lock_users(self, user_ids: list[int]) -> None:
        # Keep this deterministic for future multi-user admission (quick match
        # and friend challenge) as documented in PLAYTEST_FIX_PLAN §4.3.
        locked_ids = list(
            self.db.scalars(
                select(User.id)
                .where(User.id.in_(sorted(set(user_ids))))
                .order_by(User.id)
                .with_for_update()
            )
        )
        if locked_ids != sorted(set(user_ids)):
            raise ValueError("Cannot admit an unknown user")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
