from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session

from app.db.models import CombatActiveSlot, CombatMatchParticipant, CombatMatchRecord
from app.domain.combat.constants import RULESET_VERSION
from app.domain.combat.engine.battle import BattleStateV4
from app.domain.combat.models import MatchLifecycleStatus, MatchState

ACTIVE_MATCH_STATUSES = (
    MatchLifecycleStatus.WAITING_FOR_OPPONENT.value,
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
        # ``CombatMatchParticipant.match_id`` is a scalar FK rather than an ORM
        # relationship.  Flush the parent explicitly so PostgreSQL never tries
        # to insert a seat before its match record during the transaction.
        self.db.flush()
        for player in match.players:
            if player.user_id is not None:
                self.db.add(
                    CombatMatchParticipant(
                        match_id=match.id,
                        user_id=player.user_id,
                        player_id=player.id,
                        team=player.team,
                    )
                )
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
        query = select(CombatMatchRecord).where(CombatMatchRecord.status.in_(ACTIVE_MATCH_STATUSES))
        if owner_user_id is not None:
            query = query.where(CombatMatchRecord.owner_user_id == owner_user_id)

        expired_count = 0
        for record in self.db.scalars(query):
            if _as_utc(record.updated_at) >= older_than:
                continue
            _mark_record_expired_raw(record)
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


def list_active_combat_match_records_for_user(
    db: Session,
    *,
    user_id: int,
) -> list[CombatMatchRecord]:
    return list(
        db.scalars(
            select(CombatMatchRecord)
            .join(CombatActiveSlot, CombatActiveSlot.match_id == CombatMatchRecord.id)
            .where(
                CombatActiveSlot.user_id == user_id,
            )
            .where(CombatMatchRecord.status.in_(ACTIVE_MATCH_STATUSES))
        )
    )


def get_combat_match_participant(
    db: Session,
    *,
    match_id: str,
    user_id: int,
) -> CombatMatchParticipant | None:
    return db.scalar(
        select(CombatMatchParticipant).where(
            CombatMatchParticipant.match_id == match_id,
            CombatMatchParticipant.user_id == user_id,
        )
    )


def add_combat_match_participant(
    db: Session,
    *,
    match_id: str,
    user_id: int,
    player_id: str,
    team: int,
) -> CombatMatchParticipant:
    participant = CombatMatchParticipant(
        match_id=match_id,
        user_id=user_id,
        player_id=player_id,
        team=team,
    )
    db.add(participant)
    return participant


def load_match(record: CombatMatchRecord) -> MatchState:
    return MatchState.model_validate_json(record.state_json)


def save_match(record: CombatMatchRecord, match: MatchState) -> None:
    record.state_json = _dump_match(match)
    record.status = match.status.value
    record.winner_id = match.result.winner_id
    _release_slots_when_terminal(record)


def load_v4_battle(record: CombatMatchRecord) -> BattleStateV4:
    return BattleStateV4.model_validate_json(record.state_json)


def save_v4_battle(record: CombatMatchRecord, state: BattleStateV4) -> None:
    record.state_json = state.model_dump_json()
    record.status = state.status.value
    record.winner_id = state.result.winner_id
    _release_slots_when_terminal(record)


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


def expire_combat_match_if_outdated(record: CombatMatchRecord) -> bool:
    """Gate: a match saved under another RULESET_VERSION never reaches the resolver.

    Rules change between deploys (v4 rework); replaying an old JSON state with a
    new resolver is undefined behaviour (ARCH §8.7). Such a match is gracefully
    expired instead: result.status "expired" (not a loss), a player-facing log
    line, no rewards.

    Version is PEEKED from raw JSON (not a full model parse): the state shape
    changes between rulesets, so a v2 (MVP) record must not be parsed with the
    v4 model just to read its version. Returns True if the record was expired.
    """
    if record.status not in ACTIVE_MATCH_STATUSES:
        return False
    raw = json.loads(record.state_json)
    if raw.get("ruleset_version") == RULESET_VERSION:
        return False
    _expire_raw_state(record, raw)
    return True


def expire_combat_match_unreadable(record: CombatMatchRecord) -> None:
    """Погасить запись, чей state не парсится ТЕКУЩЕЙ моделью (V3-фикс).

    Тот же принцип, что ruleset-гейт §8.7: нечитаемый state = чужой формат,
    матч корректно гаснет (expired, не поражение). Случай из жизни: MVP-форма
    состояния, ошибочно сохранённая с текущим `ruleset_version` в переходном
    окне подмены движка, — такая запись проходит version-гейт, а её парс
    убивал таймер-воркер целиком.
    """
    raw = json.loads(record.state_json)
    _expire_raw_state(record, raw)


def _expire_raw_state(record: CombatMatchRecord, raw: dict) -> None:
    # Patch the raw state shape-agnostically — works for any past version.
    raw["status"] = MatchLifecycleStatus.EXPIRED.value
    raw["planning_deadline"] = None
    raw.setdefault("result", {})["status"] = "expired"
    raw.setdefault("log", []).append({"message": RULESET_EXPIRED_MESSAGE})
    record.state_json = json.dumps(raw, ensure_ascii=False)
    record.status = MatchLifecycleStatus.EXPIRED.value
    _release_slots_when_terminal(record)


def expired_match_payload(match_id: str) -> dict:
    """Минимальный payload закрытого гейтом матча (WS/HTTP) без парса состояния."""
    return {
        "match": {
            "id": match_id,
            "status": MatchLifecycleStatus.EXPIRED.value,
            "result": {"status": "expired", "winner_id": None, "winner_team": None},
            "log": [{"message": RULESET_EXPIRED_MESSAGE}],
        },
        "events": [],
        "resolved_turn": None,
        "last_sequence": None,
    }


def expire_combat_match_if_stale(record: CombatMatchRecord, *, older_than: datetime) -> bool:
    if record.status not in ACTIVE_MATCH_STATUSES:
        return False
    if _as_utc(record.updated_at) >= older_than:
        return False
    _mark_record_expired_raw(record)
    return True


def _mark_record_expired_raw(record: CombatMatchRecord) -> None:
    """Пометить запись EXPIRED без парса состояния — устойчиво к смене формата."""
    raw = json.loads(record.state_json)
    raw["status"] = MatchLifecycleStatus.EXPIRED.value
    record.state_json = json.dumps(raw, ensure_ascii=False)
    record.status = MatchLifecycleStatus.EXPIRED.value
    _release_slots_when_terminal(record)


def _release_slots_when_terminal(record: CombatMatchRecord) -> None:
    """Release every participant's active slot in the same DB transaction."""
    if record.status in ACTIVE_MATCH_STATUSES:
        return
    db = object_session(record)
    if db is not None:
        db.execute(delete(CombatActiveSlot).where(CombatActiveSlot.match_id == record.id))


def _dump_match(match: MatchState) -> str:
    return match.model_dump_json()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
