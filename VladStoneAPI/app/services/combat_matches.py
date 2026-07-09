from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CombatMatchRecord
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.models import CombatLogEntry, MatchLifecycleStatus, MatchState

ACTIVE_MATCH_STATUSES = (
    MatchLifecycleStatus.PLANNING.value,
    MatchLifecycleStatus.RESOLVING.value,
)

# Player-facing note appended to the log when the ruleset gate expires a match.
RULESET_EXPIRED_MESSAGE = "Правила боя обновились — матч завершён. Начни новый бой."


class CombatMatchStore(Protocol):
    def create(self, *, match: MatchState, owner_user_id: int | None) -> CombatMatchRecord:
        raise NotImplementedError

    def get(self, match_id: str) -> CombatMatchRecord | None:
        raise NotImplementedError

    def list_active(self, *, owner_user_id: int) -> list[CombatMatchRecord]:
        raise NotImplementedError

    def save(self, record: CombatMatchRecord, match: MatchState) -> None:
        raise NotImplementedError

    def expire_stale(self, *, older_than: datetime, owner_user_id: int | None = None) -> int:
        raise NotImplementedError


class SqlAlchemyCombatMatchStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, match: MatchState, owner_user_id: int | None) -> CombatMatchRecord:
        record = CombatMatchRecord(
            id=match.id,
            owner_user_id=owner_user_id,
            state_json=_dump_match(match),
            status=match.status.value,
            winner_id=match.result.winner_id,
        )
        self.db.add(record)
        return record

    def get(self, match_id: str) -> CombatMatchRecord | None:
        return self.db.get(CombatMatchRecord, match_id)

    def list_active(self, *, owner_user_id: int) -> list[CombatMatchRecord]:
        return list(
            self.db.scalars(
                select(CombatMatchRecord)
                .where(CombatMatchRecord.owner_user_id == owner_user_id)
                .where(CombatMatchRecord.status.in_(ACTIVE_MATCH_STATUSES))
                .order_by(CombatMatchRecord.updated_at.desc())
            )
        )

    def save(self, record: CombatMatchRecord, match: MatchState) -> None:
        record.state_json = _dump_match(match)
        record.status = match.status.value
        record.winner_id = match.result.winner_id

    def expire_stale(self, *, older_than: datetime, owner_user_id: int | None = None) -> int:
        query = select(CombatMatchRecord).where(
            CombatMatchRecord.status.in_(ACTIVE_MATCH_STATUSES)
        )
        if owner_user_id is not None:
            query = query.where(CombatMatchRecord.owner_user_id == owner_user_id)

        expired_count = 0
        for record in self.db.scalars(query):
            if _as_utc(record.updated_at) >= older_than:
                continue
            match = load_match(record)
            match.status = MatchLifecycleStatus.EXPIRED
            self.save(record, match)
            expired_count += 1
        return expired_count


def create_combat_match_record(
    db: Session,
    *,
    match: MatchState,
    owner_user_id: int | None,
) -> CombatMatchRecord:
    return SqlAlchemyCombatMatchStore(db).create(match=match, owner_user_id=owner_user_id)


def get_combat_match_record(db: Session, match_id: str) -> CombatMatchRecord | None:
    return SqlAlchemyCombatMatchStore(db).get(match_id)


def list_active_combat_match_records(db: Session, *, owner_user_id: int) -> list[CombatMatchRecord]:
    return SqlAlchemyCombatMatchStore(db).list_active(owner_user_id=owner_user_id)


def load_match(record: CombatMatchRecord) -> MatchState:
    return MatchState.model_validate_json(record.state_json)


def save_match(record: CombatMatchRecord, match: MatchState) -> None:
    record.state_json = _dump_match(match)
    record.status = match.status.value
    record.winner_id = match.result.winner_id


def expire_stale_combat_matches(
    db: Session,
    *,
    older_than: datetime,
    owner_user_id: int | None = None,
) -> int:
    return SqlAlchemyCombatMatchStore(db).expire_stale(
        older_than=older_than,
        owner_user_id=owner_user_id,
    )


def expire_combat_match_if_outdated(record: CombatMatchRecord) -> MatchState | None:
    """Gate: a match saved under another RULESET_VERSION never reaches the resolver.

    Rules change between deploys (v4 rework); replaying an old JSON state with a
    new resolver is undefined behaviour (ARCH §8.7). Such a match is gracefully
    expired instead: result.status "expired" (not a loss), a player-facing log
    line, no rewards. Returns the expired state so callers can broadcast it,
    or None when the version matches (or the match is already over).
    """
    if record.status not in ACTIVE_MATCH_STATUSES:
        return None
    match = load_match(record)
    if match.ruleset_version == RULESET_VERSION:
        return None
    match.status = MatchLifecycleStatus.EXPIRED
    match.planning_deadline = None
    match.result.status = "expired"
    match.log.append(CombatLogEntry(message=RULESET_EXPIRED_MESSAGE))
    save_match(record, match)
    return match


def expire_combat_match_if_stale(record: CombatMatchRecord, *, older_than: datetime) -> bool:
    if record.status not in ACTIVE_MATCH_STATUSES:
        return False
    if _as_utc(record.updated_at) >= older_than:
        return False
    match = load_match(record)
    match.status = MatchLifecycleStatus.EXPIRED
    save_match(record, match)
    return True


def _dump_match(match: MatchState) -> str:
    return match.model_dump_json()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
